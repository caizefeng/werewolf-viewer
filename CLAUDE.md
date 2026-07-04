# Werewolf Viewer - Development Guide

> **Keep this file up to date.** When making changes to the project (code, dependencies, algorithms, commands, etc.), update the relevant sections of this file to reflect the current state.
>
> **Always commit after changes.** After any edit to the codebase, stage and commit the changes to git with a descriptive message.

## Project Overview
Web-based werewolf (狼人杀) tournament video viewer that auto-detects night phases and masks character role names to avoid spoilers. Designed for 京城大师赛 (Beijing Masters) tournament videos.

## Directory Structure
```
werewolf_viewer/
├── CLAUDE.md              # This file — keep up to date with changes
├── scripts/               # Deployment scripts
│   ├── start.sh           # Start server in background (persists after terminal close)
│   └── stop.sh            # Stop background server
├── .run/                  # Runtime files: server.pid, server.log (gitignored)
├── processing/            # Python video analysis scripts
│   ├── venv/              # Python virtual environment (pyenv + venv)
│   ├── requirements.txt   # Dependencies: yt-dlp, paddleocr, paddlepaddle, opencv-python
│   ├── analyze.py         # Main pipeline: runs night + name analysis (parallel by default)
│   ├── analyze_night.py   # Night phase detection via R/G color ratio + frame diffs (threaded)
│   ├── analyze_names.py   # Role name detection via PaddleOCR (lazy frame sampling)
│   ├── models/            # Local PaddleOCR model weights (gitignored, ~165MB)
│   │   ├── PP-OCRv5_server_det/  # Text detection model
│   │   └── PP-OCRv5_server_rec/  # Text recognition model (Chinese)
│   ├── benchmarks/        # Performance benchmarks (gitignored)
│   │   ├── benchmark.py       # Parallel vs sequential + ground truth validation
│   │   ├── benchmark_full.py  # Night + name + full pipeline profiling
│   │   └── benchmark_ocr.py   # OCR model configuration benchmark (server vs mobile)
│   └── download.py        # YouTube video downloader via yt-dlp
├── videos/                # Downloaded videos + metadata (not in git)
│   └── <video-id>/
│       ├── video.mp4      # Downloaded video file
│       ├── info.json      # {title, video_id} from YouTube
│       └── metadata.json  # {night_phases, name_masks} from analysis
└── web/                   # Vite + vanilla JS frontend
    ├── .node-version      # v24.14.0 (used by fnm)
    ├── package.json       # packageManager field pins pnpm version for corepack
    ├── vite.config.js     # Dev server + video file serving middleware
    ├── index.html
    └── src/
        ├── main.js        # App initialization, video list sidebar
        ├── player.js      # WerewolfPlayer class (custom controls, masks, overlays)
        └── style.css
```

## Environment Setup

### Python (processing)
```bash
# Python managed by pyenv, venv in processing/venv/
source processing/venv/bin/activate
# Then run: python3 processing/analyze.py ...
```

### Node.js (web frontend)
```bash
# Node managed by fnm (Fast Node Manager)
# .node-version in web/ pins to v24.14.0
# pnpm managed by corepack (bundled with Node), pinned via packageManager in package.json
# IMPORTANT: must load fnm + enable corepack before running node/pnpm commands
eval "$(fnm env --use-on-cd)" && corepack enable && cd web && pnpm dev
```

### Key Commands
```bash
# Download a video (default quality: 1080p)
# Downloads to video.download.mp4, renamed to video.mp4 only on success
# (an interrupted merge can't leave a truncated video.mp4 blocking re-download)
source processing/venv/bin/activate
python3 processing/download.py --video-id="VIDEO_ID"

# Analyze a video (generates metadata.json, parallel by default)
python3 processing/analyze.py --video-id="VIDEO_ID"

# Analyze with full sequential mode (for debugging / comparison)
python3 processing/analyze.py --video-id="VIDEO_ID" --sequential --workers 1

# Run just night detection (threaded scan by default)
python3 processing/analyze_night.py videos/<id>/video.mp4
python3 processing/analyze_night.py videos/<id>/video.mp4 --workers 1  # sequential

# Benchmark parallel vs sequential on all ground truth videos
cd processing/benchmarks && python3 benchmark.py

# Comprehensive benchmark: night + name detection + full pipeline profiling
cd processing/benchmarks && python3 benchmark_full.py                    # all GT videos
cd processing/benchmarks && python3 benchmark_full.py VIDEO_ID1 VIDEO_ID2  # specific videos

# Start server in background (persists after terminal close)
scripts/start.sh          # serves on http://localhost:5173/

# Stop background server
scripts/stop.sh

# Start web dev server interactively (must load fnm + corepack first)
eval "$(fnm env --use-on-cd)" && corepack enable && cd web && pnpm dev

# For video IDs starting with dash, use: --video-id="-XXXX"
```

## Algorithm Notes

### Night Phase Detection (analyze_night.py)
- Samples frames every 2 seconds using grab+read, tracking a frame-index
  cursor (`pos`) so each sample lands on `round(sec * fps)` — frame-accurate
  for fractional frame rates (a fixed skip count would drift ~56s/hour at 29.97 fps)
- **Threaded scanning**: splits video into segments, scans in parallel with `ThreadPoolExecutor`
  - Default: 3 threads (optimal; diminishing returns beyond 3 due to I/O contention)
  - Each thread opens its own `VideoCapture` and seeks to its segment start
  - Boundary diffs handled correctly: each thread reads one extra frame before its segment
  - Revert to sequential: `--workers 1`
- Computes R/G color ratio from bottom-left and bottom-right corners
  - ROI: upper half of bottom 12% strip (h*0.88 to h*0.93), avoids UI overlays
  - Uses max(left, right) R/G ratio per frame
  - R/G >= 2.5 = red ambient light (night), ~1.0 = normal (day)
- Computes frame-to-frame pixel diff (`cv2.absdiff`, mean) to distinguish:
  - Real day/night transitions: small diff (~20-30), same scene with lighting change
  - Camera cuts (close-up ↔ table): large diff (~60-80), different scene
- Pipeline: find_red_clusters → merge_clusters → filter_cut_bounded_phases → filter by min duration (35s) → add ±2s buffer
- **merge_clusters**: merges adjacent red clusters when EITHER: (1) BOTH exit and entry boundaries are camera cuts (diff >= 40), using a 3-sample window around each boundary, OR (2) the gap is ≤100s and at least 60% of gap samples have R/G ≥ GAP_RED_THRESH (1.3) with no sample below GAP_MIN_FLOOR (1.05), indicating close-up shots during an ongoing night (close-up R/G ~1.5-2.1 vs daytime ~1.0-1.2). The fraction-based check tolerates occasional brief dips while the floor prevents merging across genuine daytime gaps.
- **filter_cut_bounded_phases**: removes phases where BOTH outer boundaries are camera cuts (both entry and exit diffs >= 40) — these are brief red-lit scenes, not real night phases
- Constants: `RED_THRESH=2.5`, `CUT_THRESH=40`, `GAP_RED_THRESH=1.3`, `GAP_ELEVATED_FRACTION=0.6`, `GAP_MIN_FLOOR=1.05`, `MAX_MERGE_GAP=100`, `MIN_PHASE_DURATION=35`, `ENTRY_BUFFER=3.5`, `EXIT_BUFFER=2`, `SCAN_INTERVAL=2`, `CUT_WINDOW=3`
- Performance: ~40s per hour of 720p video with 3 threads (~1min sequential; GPU decoding via VideoToolbox is slower due to GPU→CPU transfer overhead)

### Name Mask Detection (analyze_names.py)
- Uses PaddleOCR (PP-OCRv5 server det+rec) to find Chinese role names (狼人, 预言家, 女巫, etc.)
- Left + right edge crops are OCR'd in a **single batched `predict()` call** per frame
- Sets `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK` at import (offline-safe, faster init)
- **Local models**: weights stored in `processing/models/` (self-contained, no global cache dependency)
- **No aux models**: doc orientation, unwarping, textline orientation disabled (designed for scanned docs, hurt video frame detection)
- **Device fallback**: uses CUDA GPU if available, falls back to CPU (PaddlePaddle has no Apple MPS support)
- Scans left/right 20% edges of frames sampled from **1100s-1400s** (shifted from 1000-1300 for better generalizability)
- **Extended scan**: if one side is missing after primary range, extends to 1400s-2000s at 30s intervals
- **Lazy generator**: `sample_frames` yields frames on demand, stops reading when enough names found (typically ~4 frames instead of 30)
- Merges detected regions per side, full frame height
- Masks only cover role name text, NOT player avatars/numbers

### Pipeline Parallelism (analyze.py)
- Default: runs night + name detection in **separate processes** (subprocess for name detection)
  - Night detection runs in main process with threaded scanning
  - Name detection runs as subprocess (separate GIL, no contention)
  - Results communicated via temp JSON file; fallback to sequential on failure
  - Subprocess output captured to a temp log file, tail printed on failure for diagnosis
  - If night detection raises, the subprocess is killed (no orphans) and temp files removed
- Revert to sequential: `--sequential`
- **Benchmarked speedup**: ~1.57x overall (91s → 58s on 62min video)
- All 9 ground truth videos validated: parallel produces **identical** results to sequential

## Web Player Features
- Custom video controls at z-index 20 (above overlays)
- Night overlay: black screen during night phases
- Name masks: opaque overlay, visible only after first night ends, hidden during nights
- Masks are resizable via drag handles on edges, deletable via × button on hover
- "+ Mask" button to manually add mask regions when auto-detection fails
- Night phase markers on progress bar (red segments, draggable handles)
- **Edit persistence**: all edits (phase drags, add/remove phases, add/remove/resize
  masks, resets) POST to `/api/metadata` and are written into the video's
  metadata.json; auto-detected values are preserved in `original_night_phases` /
  `original_name_masks` on first save, and the Reset buttons restore those
- Fullscreen via Fullscreen API on wrapper element
- Sidebar with two tabs: video list + download management
- Download management: search YouTube, download+process, stop, delete
  - Stop during download deletes the partial dir; stop during analysis keeps the video
- Time display shows h:mm:ss above one hour
- Keyboard: Space=play, M=masks, F=fullscreen, arrows=±5s

## API Endpoints (vite.config.js middleware)
- `GET /api/videos` - list videos with metadata.json
- `GET /api/downloaded` - list all video dirs with hasVideo/hasMetadata flags
- `POST /api/search` - search @JCDSS channel via yt-dlp (body: {query}); channel list cached 5 min
- `POST /api/download` - start download+process job (body: {videoId})
- `GET /api/job-status` - poll active job status
- `POST /api/stop` - stop active job (deletes dir only if still downloading)
- `POST /api/delete` - delete video dir (body: {videoId})
- `POST /api/metadata` - persist edited night_phases/name_masks to metadata.json (body: {videoId, night_phases, name_masks}); preserves originals in original_* fields
- `GET /<videoId>/*` - serve files from ../videos/

### Security (server is LAN-exposed: host 0.0.0.0, allowedHosts true)
- `videoId` validated against `/^[A-Za-z0-9_-]{6,20}$/` everywhere (blocks path traversal into rm/spawn/paths)
- Static file serving is confined to `videos/` via a resolved-path prefix check
- POST endpoints reject cross-origin requests (Origin header vs Host)
- Malformed URLs (bad percent-encoding) return 400 instead of crashing the middleware
- All `spawn()` calls have `error` handlers (missing binaries can't crash the server)

## Ground Truth - Night Phase Boundaries
Not every game has the same number of phases. Use these timestamps (±2s tolerance).
All 9 videos below achieve 100% detection accuracy (0 FP, 0 miss) with current algorithm.

### 65R0r19JyYk (S21E03)
- 12:31 -- 17:05
- 29:41 -- 33:01
- 33:31 -- 36:03
- 58:08 -- 1:00:31

### -ESYZWvQMH4 (S21E02)
- 8:24 -- 12:23
- 1:13:08 -- 1:16:19
- 1:46:05 -- 1:48:25
- 2:09:12 -- 2:11:06
- 2:25:16 -- 2:25:56

### EC-1bimFjo4 (S21E05)
- 7:28 -- 8:24 (interrupted game)
- 15:49 -- 18:50
- 28:11 -- 32:38
- 33:15 -- 36:47
- 46:24 -- 48:34

### ieLaR4NBPz4
- 11:12 -- 15:08
- 34:30 -- 38:48
- 39:18 -- 42:22

### ZusP81Ycn-U
- 7:34 -- 11:28
- 1:22:48 -- 1:27:11
- 1:27:46 -- 1:30:05
- 1:44:50 -- (game ends during night, no day boundary)

### Xk65eicHSyw
- 16:44 -- 21:08
- 42:10 -- 46:00
- 1:10:52 -- 1:13:36
- 1:29:18 -- 1:31:22

### WkVPdddUiio
- 6:06 -- 9:52
- 58:10 -- 61:14
- 91:08 -- 93:00
- 119:08 -- 120:50

### F2J0QK_3gUo
- 10:24 -- 14:14
- 28:09 -- 31:20
- 31:47 -- 34:28
- 59:30 -- 60:40

### Jnf_dLaVNMU
- 11:44 -- 15:14
- 42:46 -- 47:00
