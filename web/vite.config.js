import { defineConfig } from "vite";
import fs from "fs";
import path from "path";
import { spawn } from "child_process";

const videosDir = path.resolve(__dirname, "../videos");
const processingDir = path.resolve(__dirname, "../processing");
const venvPython = path.join(processingDir, "venv", "bin", "python3");

// Track active download/process jobs: { videoId, proc, phase, log }
let activeJob = null;

function jsonResponse(res, status, data) {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(data));
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
          const url = decodeURIComponent(req.url.split("?")[0]);

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
          // Fetches recent channel videos and filters by query keywords.
          // YouTube's channel search tab caps results at ~12, so we fetch
          // the 200 most recent uploads and filter client-side instead.
          if (url === "/api/search" && req.method === "POST") {
            const { query } = await readBody(req);
            if (!query) return jsonResponse(res, 400, { error: "Missing query" });

            const args = [
              "yt-dlp", "--flat-playlist", "--dump-json",
              "--playlist-end", "200",
              "https://www.youtube.com/@JCDSS/videos",
            ];
            const proc = spawn(args[0], args.slice(1), { stdio: ["ignore", "pipe", "pipe"] });
            let output = "";
            proc.stdout.on("data", (d) => (output += d));
            proc.stderr.on("data", () => {});
            proc.on("close", () => {
              // Split query into keywords; video must contain ALL keywords
              const keywords = query.toLowerCase().split(/\s+/).filter(Boolean);
              const results = output
                .trim()
                .split("\n")
                .filter(Boolean)
                .map((line) => {
                  try {
                    const j = JSON.parse(line);
                    return { id: j.id, title: j.title, duration: j.duration };
                  } catch { return null; }
                })
                .filter((r) => {
                  if (!r) return false;
                  const t = r.title.toLowerCase();
                  return keywords.every((kw) => t.includes(kw));
                });
              // Sort by title for chronological upload order (S21E01, S21E02, ...)
              results.sort((a, b) => a.title.localeCompare(b.title, "zh"));
              jsonResponse(res, 200, results);
            });
            return;
          }

          // API: start download + process
          if (url === "/api/download" && req.method === "POST") {
            const { videoId } = await readBody(req);
            if (!videoId) return jsonResponse(res, 400, { error: "Missing videoId" });
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
            });
            activeJob.proc = dlProc;

            dlProc.stdout.on("data", (d) => activeJob.log.push(d.toString()));
            dlProc.stderr.on("data", (d) => activeJob.log.push(d.toString()));

            dlProc.on("close", (code) => {
              if (!activeJob || activeJob.videoId !== videoId) return;
              if (code !== 0) {
                activeJob.error = `Download failed (exit ${code})`;
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
              });
              activeJob.proc = anProc;

              anProc.stdout.on("data", (d) => activeJob.log.push(d.toString()));
              anProc.stderr.on("data", (d) => activeJob.log.push(d.toString()));

              anProc.on("close", (code2) => {
                if (!activeJob || activeJob.videoId !== videoId) return;
                if (code2 !== 0) {
                  activeJob.error = `Analysis failed (exit ${code2})`;
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
              phaseStartedAt: activeJob.phaseStartedAt,
            });
          }

          // API: stop active job
          if (url === "/api/stop" && req.method === "POST") {
            if (!activeJob || activeJob.done) return jsonResponse(res, 200, { stopped: false });
            if (activeJob.proc) {
              activeJob.proc.kill("SIGTERM");
            }
            activeJob.error = "Stopped by user";
            activeJob.done = true;
            activeJob.proc = null;
            return jsonResponse(res, 200, { stopped: true });
          }

          // API: delete a video
          if (url === "/api/delete" && req.method === "POST") {
            const { videoId } = await readBody(req);
            if (!videoId) return jsonResponse(res, 400, { error: "Missing videoId" });
            const dir = path.join(videosDir, videoId);
            if (!fs.existsSync(dir)) return jsonResponse(res, 404, { error: "Not found" });
            fs.rmSync(dir, { recursive: true, force: true });
            return jsonResponse(res, 200, { deleted: true });
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

          // Serve files from ../videos/
          const filePath = path.join(videosDir, url);

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
                const start = parseInt(parts[0], 10);
                const end = parts[1] ? parseInt(parts[1], 10) : stat.size - 1;
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
