import { defineConfig } from "vite";
import crypto from "crypto";
import fs from "fs";
import path from "path";
import { spawn } from "child_process";

// WEREWOLF_VIDEOS_DIR points the server at another library (e.g. a demo one)
const videosDir = process.env.WEREWOLF_VIDEOS_DIR
  ? path.resolve(process.env.WEREWOLF_VIDEOS_DIR)
  : path.resolve(__dirname, "../videos");
const processingDir = path.resolve(__dirname, "../processing");
// WEREWOLF_DEMO=1: search lists the rendered demo games (processing/demo)
// and "downloads" copy them in; analysis runs for real on them
const DEMO = !!process.env.WEREWOLF_DEMO;
const demoDir = path.join(processingDir, "demo", "library");
const venvPython = path.join(processingDir, "venv", "bin", "python3");
// Prefer the venv's yt-dlp (kept up to date via pip) over PATH
const venvYtDlp = path.join(processingDir, "venv", "bin", "yt-dlp");
const ytDlpBin = fs.existsSync(venvYtDlp) ? venvYtDlp : "yt-dlp";

// ── Jobs ──
// One job per video at a time, several videos at once. A download job runs
// download.py then analyze.py; an analyze job runs analyze.py only. Jobs
// wait in a FIFO queue for a slot: downloads are network-bound, analyses
// CPU-bound (3 scan threads + an OCR subprocess each, ~4-5 cores), so each
// has its own limit (override with WEREWOLF_MAX_DOWNLOADS / _ANALYSES).
// Finished jobs stay listed for a while so a polling client sees the end.
const MAX_DOWNLOADS = Math.max(1, parseInt(process.env.WEREWOLF_MAX_DOWNLOADS, 10) || 3);
const MAX_ANALYSES = Math.max(1, parseInt(process.env.WEREWOLF_MAX_ANALYSES, 10) || 2);
const JOB_RETENTION_MS = 10 * 60 * 1000;
const jobs = new Map(); // videoId -> job

// Cached channel upload list for /api/search (the yt-dlp fetch takes seconds)
let channelCache = { fetchedAt: 0, videos: null };
const CHANNEL_CACHE_TTL = 5 * 60 * 1000;

const CHANNEL_URL = "https://www.youtube.com/@JCDSS";
const RECENT_LIMIT = 200;    // recent-uploads window (~2 months at 3 games/day)
const SEARCH_TAB_LIMIT = 50; // YouTube caps the channel search tab at ~20 anyway

// Run yt-dlp --flat-playlist on a channel tab URL and resolve the entries.
// Rejects only if yt-dlp fails to start.
function ytDlpFlatList(listUrl, limit) {
  return new Promise((resolve, reject) => {
    const args = ["--flat-playlist", "--dump-json", "--playlist-end", String(limit), listUrl];
    const proc = spawn(ytDlpBin, args, { stdio: ["ignore", "pipe", "pipe"] });
    let output = "";
    proc.stdout.on("data", (d) => (output += d));
    proc.stderr.on("data", () => {});
    proc.on("error", reject);
    proc.on("close", () => {
      const videos = output
        .trim()
        .split("\n")
        .filter(Boolean)
        .map((line) => {
          try {
            const j = JSON.parse(line);
            return { id: j.id, title: j.title, duration: j.duration };
          } catch { return null; }
        })
        .filter((v) => v && v.id && v.title);
      resolve(videos);
    });
  });
}

// YouTube video IDs are 11 chars of [A-Za-z0-9_-]; allow a small range for
// safety. Rejects path traversal (slashes, dots) in videoId outright.
const VIDEO_ID_RE = /^[A-Za-z0-9_-]{6,20}$/;

function jsonResponse(res, status, data) {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(data));
}

// Extract the most useful error lines from a job log: prefer explicit
// ERROR lines (yt-dlp and Python print those) over the tail, which for a
// Python failure is just the traceback's last frames.
function errorTail(log) {
  // Split on \r too: yt-dlp progress updates are \r-separated, and the
  // ERROR line lands on the same "line" as hundreds of progress ticks
  const lines = log.join("").split(/\r?\n|\r/).filter((l) => l.trim());
  const errors = lines.filter((l) => /\bERROR\b/i.test(l));
  return (errors.length ? errors : lines).slice(-3).join("\n").trim();
}

// Phases: download jobs go queued -> downloading -> waiting -> processing ->
// done; analyze jobs start at waiting. phaseStartedAt restarts per phase.
function newJob(videoId, kind) {
  const now = Date.now();
  return {
    videoId, kind, proc: null, log: [],
    phase: kind === "download" ? "queued" : "waiting",
    done: false, error: null, stopped: false,
    createdAt: now, phaseStartedAt: now, finishedAt: null,
    timings: { download: null, analysis: null },
  };
}

function setPhase(job, phase) {
  job.phase = phase;
  job.phaseStartedAt = Date.now();
}

// A job's process callbacks only count while the job is still the live
// entry for its video (a stop or a replacement makes them stale)
function isCurrent(job) {
  return jobs.get(job.videoId) === job && !job.done;
}

function finishJob(job, error) {
  if (job.done) return;
  job.error = error || null;
  job.done = true;
  job.proc = null;
  job.finishedAt = Date.now();
  setPhase(job, "done");
  scheduleJobs();
}

// Spawn a processing script for a job in its own process group (so a stop
// can kill python and its yt-dlp/analyze children together), collecting
// output into the job log.
function spawnForJob(job, args, onClose) {
  const proc = spawn(venvPython, args, {
    cwd: processingDir,
    stdio: ["ignore", "pipe", "pipe"],
    detached: true,
  });
  job.proc = proc;
  proc.stdout.on("data", (d) => job.log.push(d.toString()));
  proc.stderr.on("data", (d) => job.log.push(d.toString()));
  proc.on("error", (err) => {
    if (isCurrent(job)) finishJob(job, `Failed to start ${path.basename(args[0])}: ${err.message}`);
  });
  proc.on("close", (code) => {
    if (isCurrent(job)) onClose(code);
  });
}

function runDownload(job) {
  setPhase(job, "downloading");
  spawnForJob(job, [
    path.join(processingDir, DEMO ? "demo/fake_download.py" : "download.py"),
    `--video-id=${job.videoId}`, "--quality=1080",
    "--output-dir", path.join(videosDir, job.videoId),
  ], (code) => {
    if (code !== 0) return finishJob(job, errorTail(job.log) || `Download failed (exit ${code})`);
    job.timings.download = Date.now() - job.phaseStartedAt;
    setPhase(job, "waiting");
    scheduleJobs();
  });
}

function runAnalysis(job) {
  setPhase(job, "processing");
  job.log.push("--- Starting analysis ---\n");
  spawnForJob(job, [
    path.join(processingDir, "analyze.py"),
    `--video-id=${job.videoId}`,
  ], (code) => {
    if (code !== 0) return finishJob(job, errorTail(job.log) || `Analysis failed (exit ${code})`);
    job.timings.analysis = Date.now() - job.phaseStartedAt;
    finishJob(job, null);
  });
}

function pruneJobs() {
  const now = Date.now();
  for (const [id, job] of jobs) {
    if (job.done && now - job.finishedAt > JOB_RETENTION_MS) jobs.delete(id);
  }
}

function sortedJobs() {
  return [...jobs.values()].sort((a, b) => a.createdAt - b.createdAt);
}

// Start waiting jobs while slots are free, oldest first
function scheduleJobs() {
  pruneJobs();
  const all = sortedJobs();
  let downloads = all.filter((j) => j.phase === "downloading").length;
  let analyses = all.filter((j) => j.phase === "processing").length;
  for (const job of all) {
    if (job.phase === "queued" && downloads < MAX_DOWNLOADS) {
      downloads++;
      runDownload(job);
    } else if (job.phase === "waiting" && analyses < MAX_ANALYSES) {
      analyses++;
      runAnalysis(job);
    }
  }
}

// What /api/job-status reports per job. Elapsed time is sent as a duration
// (not a timestamp) so LAN clients with a different clock stay accurate.
function jobView(job) {
  const all = sortedJobs();
  const queued = job.phase === "queued" || job.phase === "waiting";
  return {
    videoId: job.videoId,
    kind: job.kind,
    phase: job.phase,
    active: !job.done,
    done: job.done,
    error: job.error,
    stopped: job.stopped,
    phaseElapsedMs: Date.now() - job.phaseStartedAt,
    timings: job.timings,
    queuePosition: queued
      ? all.filter((j) => j.phase === job.phase && j.createdAt < job.createdAt).length + 1
      : null,
  };
}

function stopJob(job) {
  if (job.done) return false;
  if (job.proc) {
    // Kill the whole process group (python + yt-dlp/analyze subprocesses)
    try { process.kill(-job.proc.pid, "SIGTERM"); } catch {}
  }
  // A stop while downloading discards the partial directory. A stop during
  // (or while waiting for) analysis keeps the expensive finished download;
  // re-running analysis is cheap.
  if (job.phase === "queued" || job.phase === "downloading") {
    const jobDir = path.join(videosDir, job.videoId);
    if (fs.existsSync(jobDir)) fs.rmSync(jobDir, { recursive: true, force: true });
  }
  job.stopped = true;
  finishJob(job, "Stopped by user");
  return true;
}

// Browsers attach an Origin header to cross-site POSTs (including
// preflight-free text/plain ones), so a malicious page on the LAN could
// otherwise trigger downloads/deletes. Same-origin requests and curl pass.
function blockCrossOrigin(req, res) {
  const origin = req.headers.origin;
  if (!origin) return false;
  try {
    if (new URL(origin).host === req.headers.host) return false;
  } catch {}
  jsonResponse(res, 403, { error: "Cross-origin request rejected" });
  return true;
}

const MAX_BODY_BYTES = 1_000_000;

// ── Viewer state: bookmark flag + resume point per game ──
// Stored next to the video (videos/<id>/viewer_state.json) so it is shared
// by every device on the LAN, untouched by re-analysis (which rewrites only
// metadata.json) and removed together with the game.
// Version of a metadata.json (its content), served with it and checked on save
function metadataVersion(buffer) {
  return crypto.createHash("sha1").update(buffer).digest("hex").slice(0, 16);
}

const VIEWER_STATE_FILE = "viewer_state.json";
const MAX_MEDIA_SECONDS = 48 * 3600;

function readViewerState(dir) {
  try {
    const s = JSON.parse(fs.readFileSync(path.join(dir, VIEWER_STATE_FILE), "utf-8"));
    return s && typeof s === "object" && !Array.isArray(s) ? s : {};
  } catch {
    return {};
  }
}

// What /api/videos exposes per game and /api/state answers with
function viewerStateView(s) {
  return {
    bookmarked: s.bookmarked === true,
    position: Number.isFinite(s.position) ? s.position : null,
    duration: Number.isFinite(s.duration) ? s.duration : null,
    watchedAt: Number.isFinite(s.watchedAt) ? s.watchedAt : null,
  };
}

// Parse a JSON body. Resolves null (after answering 413) when the body is
// over the cap, so handlers must bail out on null.
function readBody(req, res) {
  return new Promise((resolve) => {
    let body = "";
    let tooBig = false;
    req.on("data", (c) => {
      if (tooBig) return;
      body += c;
      if (body.length > MAX_BODY_BYTES) {
        tooBig = true;
        body = "";
        try { jsonResponse(res, 413, { error: "Body too large" }); } catch {}
        req.destroy();
        resolve(null);
      }
    });
    req.on("end", () => {
      if (tooBig) return;
      try { resolve(JSON.parse(body)); } catch { resolve({}); }
    });
    req.on("error", () => { if (!tooBig) resolve({}); });
  });
}

export default defineConfig({
  server: {
    host: "0.0.0.0",
    port: 5173,
    allowedHosts: true,
  },
  plugins: [
    {
      name: "serve-videos",
      configureServer(server) {
        server.middlewares.use(async (req, res, next) => {
          let url;
          try {
            url = decodeURIComponent(req.url.split("?")[0]);
          } catch {
            // Malformed percent-encoding; don't let the throw escape the
            // async middleware (it would kill the dev server)
            return jsonResponse(res, 400, { error: "Malformed URL" });
          }

          // API: list available videos (dirs with metadata.json)
          if (url === "/api/videos") {
            try {
              const dirs = fs.readdirSync(videosDir, { withFileTypes: true })
                .filter((d) => d.isDirectory())
                .filter((d) => fs.existsSync(path.join(videosDir, d.name, "metadata.json")))
                .map((d) => {
                  const dir = path.join(videosDir, d.name);
                  let title = d.name;
                  const infoPath = path.join(dir, "info.json");
                  if (fs.existsSync(infoPath)) {
                    try {
                      const info = JSON.parse(fs.readFileSync(infoPath, "utf-8"));
                      title = info.title || d.name;
                    } catch {}
                  }
                  let hiddenRoles = false;
                  try {
                    const meta = JSON.parse(fs.readFileSync(path.join(dir, "metadata.json"), "utf-8"));
                    hiddenRoles = !!meta.hidden_roles;
                  } catch {}
                  // h264: the game has download.py's H.264 + AAC copy, which
                  // browsers that cannot play the AV1/Opus original get
                  const h264 = fs.existsSync(path.join(dir, "video.h264.mp4"));
                  return { id: d.name, title, hiddenRoles, h264, ...viewerStateView(readViewerState(dir)) };
                });
              res.writeHead(200, { "Content-Type": "application/json" });
              res.end(JSON.stringify(dirs));
            } catch (err) {
              res.writeHead(500, { "Content-Type": "application/json" });
              res.end(JSON.stringify({ error: err.message }));
            }
            return;
          }

          // API: search YouTube (restricted to @JCDSS channel)
          // Two sources, merged: (1) the channel's recent uploads (cached),
          // which covers broad queries that YouTube's search tab would cap
          // at ~20 results; (2) the channel search tab, which finds older
          // episodes that have aged out of the recent window (the channel
          // posts ~3 games/day, so 200 uploads is only ~2 months).
          if (url === "/api/search" && req.method === "POST") {
            if (blockCrossOrigin(req, res)) return;
            const body = await readBody(req, res);
            if (!body) return;
            const { query } = body;
            if (!query) return jsonResponse(res, 400, { error: "Missing query" });
            if (DEMO) {
              try {
                const all = JSON.parse(fs.readFileSync(path.join(demoDir, "catalogue.json"), "utf-8"));
                const kws = query.toLowerCase().split(/\s+/).filter(Boolean);
                return jsonResponse(res, 200, all.filter((v) => kws.every((k) => v.title.toLowerCase().includes(k))));
              } catch (err) {
                return jsonResponse(res, 500, { error: `Demo catalogue missing: ${err.message}` });
              }
            }

            // Split query into keywords; video must contain ALL keywords
            const keywords = query.toLowerCase().split(/\s+/).filter(Boolean);
            const matches = (v) => keywords.every((kw) => v.title.toLowerCase().includes(kw));
            const settle = (p) => p.then((videos) => ({ videos }), (err) => ({ error: err.message }));

            const cacheFresh = channelCache.videos && Date.now() - channelCache.fetchedAt < CHANNEL_CACHE_TTL;
            const [recentRes, searchRes] = await Promise.all([
              cacheFresh
                ? Promise.resolve({ videos: channelCache.videos })
                : settle(ytDlpFlatList(`${CHANNEL_URL}/videos`, RECENT_LIMIT)),
              settle(ytDlpFlatList(`${CHANNEL_URL}/search?query=${encodeURIComponent(query)}`, SEARCH_TAB_LIMIT)),
            ]);
            if (recentRes.error && searchRes.error) {
              return jsonResponse(res, 500, { error: `yt-dlp failed to start: ${recentRes.error}` });
            }
            if (!cacheFresh && recentRes.videos && recentRes.videos.length > 0) {
              channelCache = { fetchedAt: Date.now(), videos: recentRes.videos };
            }

            const seen = new Set();
            const results = [];
            for (const v of [...(recentRes.videos || []), ...(searchRes.videos || [])]) {
              if (seen.has(v.id) || !matches(v)) continue;
              seen.add(v.id);
              results.push(v);
            }
            // Sort by title for chronological upload order (S21E01, S21E02, ...)
            results.sort((a, b) => a.title.localeCompare(b.title, "zh"));
            return jsonResponse(res, 200, results);
          }

          // API: start download + process (queued when the download slots are busy)
          if (url === "/api/download" && req.method === "POST") {
            if (blockCrossOrigin(req, res)) return;
            const body = await readBody(req, res);
            if (!body) return;
            const { videoId } = body;
            if (!videoId || !VIDEO_ID_RE.test(videoId)) return jsonResponse(res, 400, { error: "Invalid videoId" });
            const existing = jobs.get(videoId);
            if (existing && !existing.done) return jsonResponse(res, 409, { error: "A job for this video is already running", phase: existing.phase });
            const job = newJob(videoId, "download");
            jobs.set(videoId, job);
            scheduleJobs();
            return jsonResponse(res, 200, { started: true, videoId, phase: job.phase });
          }

          // API: re-run analysis on an already-downloaded video (e.g. after
          // detection improvements) without re-downloading it
          if (url === "/api/analyze" && req.method === "POST") {
            if (blockCrossOrigin(req, res)) return;
            const body = await readBody(req, res);
            if (!body) return;
            const { videoId } = body;
            if (!videoId || !VIDEO_ID_RE.test(videoId)) return jsonResponse(res, 400, { error: "Invalid videoId" });
            const existing = jobs.get(videoId);
            if (existing && !existing.done) return jsonResponse(res, 409, { error: "A job for this video is already running", phase: existing.phase });
            if (!fs.existsSync(path.join(videosDir, videoId, "video.mp4"))) return jsonResponse(res, 404, { error: "Video not downloaded" });
            const job = newJob(videoId, "analyze");
            jobs.set(videoId, job);
            scheduleJobs();
            return jsonResponse(res, 200, { started: true, videoId, phase: job.phase });
          }

          // API: status of every job (running, queued, recently finished)
          if (url === "/api/job-status") {
            pruneJobs();
            const list = sortedJobs().map(jobView);
            return jsonResponse(res, 200, {
              jobs: list,
              active: list.filter((j) => j.active).length,
              limits: { downloads: MAX_DOWNLOADS, analyses: MAX_ANALYSES },
            });
          }

          // API: stop one job (body: {videoId})
          if (url === "/api/stop" && req.method === "POST") {
            if (blockCrossOrigin(req, res)) return;
            const body = await readBody(req, res);
            if (!body) return;
            const { videoId } = body;
            if (!videoId || !VIDEO_ID_RE.test(videoId)) return jsonResponse(res, 400, { error: "Invalid videoId" });
            const job = jobs.get(videoId);
            return jsonResponse(res, 200, { stopped: job ? stopJob(job) : false });
          }

          // API: delete a video
          if (url === "/api/delete" && req.method === "POST") {
            if (blockCrossOrigin(req, res)) return;
            const body = await readBody(req, res);
            if (!body) return;
            const { videoId } = body;
            if (!videoId || !VIDEO_ID_RE.test(videoId)) return jsonResponse(res, 400, { error: "Invalid videoId" });
            const job = jobs.get(videoId);
            if (job && !job.done) return jsonResponse(res, 409, { error: "A job is running for this video; stop it first" });
            const dir = path.join(videosDir, videoId);
            if (!fs.existsSync(dir)) return jsonResponse(res, 404, { error: "Not found" });
            fs.rmSync(dir, { recursive: true, force: true });
            // A finished job for a deleted video must not keep showing "Done" in the search rows
            if (job) jobs.delete(videoId);
            return jsonResponse(res, 200, { deleted: true });
          }

          // API: persist edited night phases / name masks to metadata.json.
          // The auto-detected values are preserved in original_* fields on
          // first save so the player's Reset buttons can restore them.
          if (url === "/api/metadata" && req.method === "POST") {
            if (blockCrossOrigin(req, res)) return;
            const body = await readBody(req, res);
            if (!body) return;
            const { videoId, version, night_phases, name_masks } = body;
            if (!videoId || !VIDEO_ID_RE.test(videoId)) return jsonResponse(res, 400, { error: "Invalid videoId" });
            const phasesOk = Array.isArray(night_phases) && night_phases.every(
              (p) => p && Number.isFinite(p.start) && Number.isFinite(p.end));
            const masksOk = Array.isArray(name_masks) && name_masks.every(
              (m) => m && Number.isFinite(m.x) && Number.isFinite(m.y)
                && Number.isFinite(m.w) && Number.isFinite(m.h));
            if (!phasesOk || !masksOk) return jsonResponse(res, 400, { error: "Malformed night_phases/name_masks" });

            const metaPath = path.join(videosDir, videoId, "metadata.json");
            if (!fs.existsSync(metaPath)) return jsonResponse(res, 404, { error: "Not found" });
            try {
              const current = fs.readFileSync(metaPath);
              // The page sends the version it loaded: if the file changed since
              // (re-analysed, or saved from another tab or device), its copy of
              // the nights and masks is stale and writing it would undo that
              if (version !== undefined && version !== metadataVersion(current)) {
                return jsonResponse(res, 409, { error: "Metadata changed since it was loaded", stale: true });
              }
              const meta = JSON.parse(current.toString("utf-8"));
              meta.original_night_phases ??= meta.night_phases;
              meta.original_name_masks ??= meta.name_masks;
              meta.night_phases = night_phases.map((p) => ({ start: p.start, end: p.end }));
              meta.name_masks = name_masks.map((m) => ({ x: m.x, y: m.y, w: m.w, h: m.h }));
              const text = JSON.stringify(meta, null, 2);
              const tmpPath = metaPath + ".tmp";
              fs.writeFileSync(tmpPath, text);
              fs.renameSync(tmpPath, metaPath);
              return jsonResponse(res, 200, { saved: true, version: metadataVersion(Buffer.from(text)) });
            } catch (err) {
              return jsonResponse(res, 500, { error: err.message });
            }
          }

          // API: update a game's viewer state (body: {videoId, bookmarked?,
          // position?, duration?}); fields are merged into viewer_state.json.
          // The read-modify-write below is synchronous, so two requests can't
          // interleave and lose each other's fields.
          if (url === "/api/state" && req.method === "POST") {
            if (blockCrossOrigin(req, res)) return;
            const body = await readBody(req, res);
            if (!body) return;
            const { videoId, bookmarked, position, duration } = body;
            if (!videoId || !VIDEO_ID_RE.test(videoId)) return jsonResponse(res, 400, { error: "Invalid videoId" });
            const dir = path.join(videosDir, videoId);
            if (!fs.existsSync(path.join(dir, "video.mp4"))) return jsonResponse(res, 404, { error: "Not found" });
            const update = {};
            if (bookmarked !== undefined) {
              if (typeof bookmarked !== "boolean") return jsonResponse(res, 400, { error: "bookmarked must be true or false" });
              update.bookmarked = bookmarked;
              update.bookmarkedAt = bookmarked ? Date.now() : null;
            }
            if (duration !== undefined && position === undefined) {
              return jsonResponse(res, 400, { error: "duration is only accepted with position" });
            }
            if (position !== undefined) {
              const ok = (x) => typeof x === "number" && Number.isFinite(x) && x >= 0 && x <= MAX_MEDIA_SECONDS;
              if (!ok(position)) return jsonResponse(res, 400, { error: "position must be seconds between 0 and 48h" });
              if (duration !== undefined && (!ok(duration) || duration === 0)) {
                return jsonResponse(res, 400, { error: "duration must be seconds between 0 and 48h" });
              }
              update.position = Math.round(position * 10) / 10;
              if (duration !== undefined) update.duration = Math.round(duration * 10) / 10;
              update.watchedAt = Date.now();
            }
            if (!Object.keys(update).length) return jsonResponse(res, 400, { error: "Nothing to update" });
            try {
              const statePath = path.join(dir, VIEWER_STATE_FILE);
              const state = { ...readViewerState(dir), ...update };
              const tmpPath = statePath + ".tmp";
              fs.writeFileSync(tmpPath, JSON.stringify(state, null, 2));
              fs.renameSync(tmpPath, statePath);
              return jsonResponse(res, 200, { videoId, ...viewerStateView(state) });
            } catch (err) {
              return jsonResponse(res, 500, { error: err.message });
            }
          }

          // API: check which video IDs are downloaded
          if (url === "/api/downloaded") {
            try {
              const dirs = fs.readdirSync(videosDir, { withFileTypes: true })
                .filter((d) => d.isDirectory())
                .map((d) => {
                  const dir = path.join(videosDir, d.name);
                  return {
                    id: d.name,
                    hasVideo: fs.existsSync(path.join(dir, "video.mp4")),
                    hasMetadata: fs.existsSync(path.join(dir, "metadata.json")),
                  };
                });
              jsonResponse(res, 200, dirs);
            } catch (err) {
              jsonResponse(res, 500, { error: err.message });
            }
            return;
          }

          // Serve files from ../videos/. path.join normalizes ".." segments,
          // so anything escaping videosDir fails the prefix check.
          const filePath = path.join(videosDir, url);
          if (!filePath.startsWith(videosDir + path.sep)) {
            next();
            return;
          }

          if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
            const ext = path.extname(filePath).toLowerCase();
            const mimeTypes = {
              ".mp4": "video/mp4",
              ".json": "application/json",
              ".webm": "video/webm",
            };
            const mime = mimeTypes[ext] || "application/octet-stream";

            // For video files, support range requests
            if (ext === ".mp4" || ext === ".webm") {
              const stat = fs.statSync(filePath);
              const range = req.headers.range;

              if (range) {
                const parts = range.replace(/bytes=/, "").split("-");
                let start = parseInt(parts[0], 10);
                let end = parts[1] ? parseInt(parts[1], 10) : stat.size - 1;
                if (Number.isNaN(start)) start = 0;
                if (Number.isNaN(end) || end >= stat.size) end = stat.size - 1;
                if (start > end || start >= stat.size) {
                  res.writeHead(416, { "Content-Range": `bytes */${stat.size}` });
                  res.end();
                  return;
                }
                const chunkSize = end - start + 1;

                res.writeHead(206, {
                  "Content-Range": `bytes ${start}-${end}/${stat.size}`,
                  "Accept-Ranges": "bytes",
                  "Content-Length": chunkSize,
                  "Content-Type": mime,
                });
                const stream = fs.createReadStream(filePath, { start, end });
                res.on("close", () => stream.destroy());
                stream.pipe(res);
              } else {
                res.writeHead(200, {
                  "Content-Length": stat.size,
                  "Content-Type": mime,
                  "Accept-Ranges": "bytes",
                });
                const stream = fs.createReadStream(filePath);
                res.on("close", () => stream.destroy());
                stream.pipe(res);
              }
            } else if (path.basename(filePath) === "metadata.json") {
              // Edits are saved against the version a page loaded (see
              // /api/metadata), so never let a browser cache it
              const body = fs.readFileSync(filePath);
              res.writeHead(200, {
                "Content-Type": mime,
                "Cache-Control": "no-store",
                "X-Metadata-Version": metadataVersion(body),
              });
              res.end(body);
            } else {
              res.writeHead(200, { "Content-Type": mime });
              const stream = fs.createReadStream(filePath);
              res.on("close", () => stream.destroy());
              stream.pipe(res);
            }
            return;
          }

          next();
        });
      },
    },
  ],
});
