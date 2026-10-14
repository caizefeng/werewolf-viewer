import { defineConfig } from "vite";
import fs from "fs";
import path from "path";
import { spawn } from "child_process";

const videosDir = path.resolve(__dirname, "../videos");
const processingDir = path.resolve(__dirname, "../processing");
const venvPython = path.join(processingDir, "venv", "bin", "python3");
// Prefer the venv's yt-dlp (kept up to date via pip) over PATH
const venvYtDlp = path.join(processingDir, "venv", "bin", "yt-dlp");
const ytDlpBin = fs.existsSync(venvYtDlp) ? venvYtDlp : "yt-dlp";

// Track active download/process jobs: { videoId, proc, phase, log }
let activeJob = null;

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

function readBody(req) {
  return new Promise((resolve) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      try { resolve(JSON.parse(body)); } catch { resolve({}); }
    });
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
                  return { id: d.name, title };
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
            const { query } = await readBody(req);
            if (!query) return jsonResponse(res, 400, { error: "Missing query" });

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

          // API: start download + process
          if (url === "/api/download" && req.method === "POST") {
            if (blockCrossOrigin(req, res)) return;
            const { videoId } = await readBody(req);
            if (!videoId || !VIDEO_ID_RE.test(videoId)) return jsonResponse(res, 400, { error: "Invalid videoId" });
            if (activeJob && !activeJob.done) return jsonResponse(res, 409, { error: "A job is already running", jobVideoId: activeJob.videoId });

            const outputDir = path.join(videosDir, videoId);
            activeJob = { videoId, proc: null, phase: "downloading", log: [], done: false, error: null, phaseStartedAt: Date.now() };

            // Phase 1: Download
            const dlArgs = [
              path.join(processingDir, "download.py"),
              `--video-id=${videoId}`, "--quality=1080",
              "--output-dir", outputDir,
            ];
            const dlProc = spawn(venvPython, dlArgs, {
              cwd: processingDir,
              stdio: ["ignore", "pipe", "pipe"],
              detached: true,
            });
            activeJob.proc = dlProc;

            dlProc.stdout.on("data", (d) => activeJob.log.push(d.toString()));
            dlProc.stderr.on("data", (d) => activeJob.log.push(d.toString()));

            dlProc.on("error", (err) => {
              if (!activeJob || activeJob.videoId !== videoId || activeJob.done) return;
              activeJob.error = `Failed to start download: ${err.message}`;
              activeJob.done = true;
              activeJob.proc = null;
            });

            dlProc.on("close", (code) => {
              if (!activeJob || activeJob.videoId !== videoId || activeJob.done) return;
              if (code !== 0) {
                activeJob.error = errorTail(activeJob.log) || `Download failed (exit ${code})`;
                activeJob.done = true;
                activeJob.proc = null;
                return;
              }

              // Phase 2: Analyze
              activeJob.phase = "processing";
              activeJob.phaseStartedAt = Date.now();
              activeJob.log.push("--- Starting analysis ---\n");
              const videoPath = path.join(outputDir, "video.mp4");
              const anProc = spawn(venvPython, [
                path.join(processingDir, "analyze.py"),
                `--video-id=${videoId}`,
              ], {
                cwd: processingDir,
                stdio: ["ignore", "pipe", "pipe"],
                detached: true,
              });
              activeJob.proc = anProc;

              anProc.stdout.on("data", (d) => activeJob.log.push(d.toString()));
              anProc.stderr.on("data", (d) => activeJob.log.push(d.toString()));

              anProc.on("error", (err) => {
                if (!activeJob || activeJob.videoId !== videoId || activeJob.done) return;
                activeJob.error = `Failed to start analysis: ${err.message}`;
                activeJob.phase = "done";
                activeJob.done = true;
                activeJob.proc = null;
              });

              anProc.on("close", (code2) => {
                if (!activeJob || activeJob.videoId !== videoId || activeJob.done) return;
                if (code2 !== 0) {
                  activeJob.error = errorTail(activeJob.log) || `Analysis failed (exit ${code2})`;
                }
                activeJob.phase = "done";
                activeJob.done = true;
                activeJob.proc = null;
              });
            });

            return jsonResponse(res, 200, { started: true, videoId });
          }

          // API: job status
          if (url === "/api/job-status") {
            if (!activeJob) return jsonResponse(res, 200, { active: false });
            return jsonResponse(res, 200, {
              active: !activeJob.done,
              videoId: activeJob.videoId,
              phase: activeJob.phase,
              done: activeJob.done,
              error: activeJob.error,
              stopped: activeJob.stopped || false,
              phaseStartedAt: activeJob.phaseStartedAt,
            });
          }

          // API: stop active job
          if (url === "/api/stop" && req.method === "POST") {
            if (blockCrossOrigin(req, res)) return;
            if (!activeJob || activeJob.done) return jsonResponse(res, 200, { stopped: false });
            if (activeJob.proc) {
              // Kill entire process group (python + yt-dlp/analyze subprocesses)
              try { process.kill(-activeJob.proc.pid, "SIGTERM"); } catch {}
            }
            // Clean up the partial download directory — but only while
            // downloading. A stop during analysis keeps the (expensive)
            // finished download; re-running analysis is cheap.
            if (activeJob.phase === "downloading") {
              const jobDir = path.join(videosDir, activeJob.videoId);
              if (fs.existsSync(jobDir)) {
                fs.rmSync(jobDir, { recursive: true, force: true });
              }
            }
            activeJob.error = "Stopped by user";
            activeJob.stopped = true;
            activeJob.done = true;
            activeJob.proc = null;
            return jsonResponse(res, 200, { stopped: true });
          }

          // API: delete a video
          if (url === "/api/delete" && req.method === "POST") {
            if (blockCrossOrigin(req, res)) return;
            const { videoId } = await readBody(req);
            if (!videoId || !VIDEO_ID_RE.test(videoId)) return jsonResponse(res, 400, { error: "Invalid videoId" });
            const dir = path.join(videosDir, videoId);
            if (!fs.existsSync(dir)) return jsonResponse(res, 404, { error: "Not found" });
            fs.rmSync(dir, { recursive: true, force: true });
            return jsonResponse(res, 200, { deleted: true });
          }

          // API: persist edited night phases / name masks to metadata.json.
          // The auto-detected values are preserved in original_* fields on
          // first save so the player's Reset buttons can restore them.
          if (url === "/api/metadata" && req.method === "POST") {
            if (blockCrossOrigin(req, res)) return;
            const { videoId, night_phases, name_masks } = await readBody(req);
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
              const meta = JSON.parse(fs.readFileSync(metaPath, "utf-8"));
              meta.original_night_phases ??= meta.night_phases;
              meta.original_name_masks ??= meta.name_masks;
              meta.night_phases = night_phases.map((p) => ({ start: p.start, end: p.end }));
              meta.name_masks = name_masks.map((m) => ({ x: m.x, y: m.y, w: m.w, h: m.h }));
              const tmpPath = metaPath + ".tmp";
              fs.writeFileSync(tmpPath, JSON.stringify(meta, null, 2));
              fs.renameSync(tmpPath, metaPath);
              return jsonResponse(res, 200, { saved: true });
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
                fs.createReadStream(filePath, { start, end }).pipe(res);
              } else {
                res.writeHead(200, {
                  "Content-Length": stat.size,
                  "Content-Type": mime,
                  "Accept-Ranges": "bytes",
                });
                fs.createReadStream(filePath).pipe(res);
              }
            } else {
              res.writeHead(200, { "Content-Type": mime });
              fs.createReadStream(filePath).pipe(res);
            }
            return;
          }

          next();
        });
      },
    },
  ],
});
