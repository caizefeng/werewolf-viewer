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
│   ├── benchmark.py       # Performance benchmark: parallel vs sequential, ground truth validation
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
cd processing && python3 benchmark.py

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
- Samples frames every 2 seconds using grab+read
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
- **merge_clusters**: merges adjacent red clusters when BOTH the exit and entry boundaries are camera cuts (diff >= 40), using a 3-sample window around each boundary to catch cuts that land slightly offset from the red/non-red threshold
- **filter_cut_bounded_phases**: removes phases where BOTH outer boundaries are camera cuts (both entry and exit diffs >= 40) — these are brief red-lit scenes, not real night phases
- Constants: `RED_THRESH=2.5`, `CUT_THRESH=40`, `MIN_PHASE_DURATION=35`, `ENTRY_BUFFER=3.5`, `EXIT_BUFFER=2`, `SCAN_INTERVAL=2`, `CUT_WINDOW=3`
- Performance: ~40s per hour of 720p video with 3 threads (~1min sequential; GPU decoding via VideoToolbox is slower due to GPU→CPU transfer overhead)

### Name Mask Detection (analyze_names.py)
- Uses PaddleOCR to find Chinese role names (狼人, 预言家, 女巫, etc.)
- Scans left/right 20% edges of frames sampled from 1000s-1300s
- **Lazy generator**: `sample_frames` yields frames on demand, stops reading when enough names found (typically ~10 frames instead of 30)
- Merges detected regions per side, full frame height
- Masks only cover role name text, NOT player avatars/numbers

### Pipeline Parallelism (analyze.py)
- Default: runs night + name detection in **separate processes** (subprocess for name detection)
  - Night detection runs in main process with threaded scanning
  - Name detection runs as subprocess (separate GIL, no contention)
  - Results communicated via temp JSON file; fallback to sequential on failure
- Revert to sequential: `--sequential`
- **Benchmarked speedup**: ~1.57x overall (91s → 58s on 62min video)
- All 6 ground truth videos validated: parallel produces **identical** results to sequential

## Web Player Features
- Custom video controls at z-index 20 (above overlays)
- Night overlay: black screen during night phases
- Name masks: visible only after first night ends, hidden during nights
- Masks are resizable via drag handles on edges
- Night phase markers on progress bar (red segments, draggable handles)
- Fullscreen via Fullscreen API on wrapper element
- Sidebar with two tabs: video list + download management
- Download management: search YouTube, download+process, stop, delete
- Keyboard: Space=play, M=masks, F=fullscreen, arrows=±5s

## API Endpoints (vite.config.js middleware)
- `GET /api/videos` - list videos with metadata.json
- `GET /api/downloaded` - list all video dirs with hasVideo/hasMetadata flags
- `POST /api/search` - search @JCDSS channel via yt-dlp (body: {query})
- `POST /api/download` - start download+process job (body: {videoId})
- `GET /api/job-status` - poll active job status
- `POST /api/stop` - stop active job
- `POST /api/delete` - delete video dir (body: {videoId})
- `GET /<videoId>/*` - serve files from ../videos/

## Ground Truth - Night Phase Boundaries
Not every game has the same number of phases. Use these timestamps (±2s tolerance).
All 5 videos below achieve 100% detection accuracy (0 FP, 0 miss) with current algorithm.

### 65R0r19JyYk (S21E03)
- 12:31 -- 17:05
- 29:41 -- 33:01
- 33:31 -- 36:03
- 58:08 -- 1:00:31

### EC-1bimFjo4 (S21E05)
- 7:28 -- 8:24 (interrupted game)
- 15:49 -- 18:50
- 28:11 -- 32:38
- 33:15 -- 36:47
- 46:24 -- 48:34

### -ESYZWvQMH4 (S21E02)
- 8:24 -- 12:23
- 1:13:08 -- 1:16:19
- 1:46:05 -- 1:48:25
- 2:09:12 -- 2:11:06
- 2:25:16 -- 2:25:56

### ZusP81Ycn-U
- 7:34 -- 11:28
- 1:22:48 -- 1:27:11
- 1:27:46 -- 1:30:05
- 1:44:50 -- (game ends during night, no day boundary)

### ieLaR4NBPz4
- 11:12 -- 15:08
- 34:30 -- 38:48
- 39:18 -- 42:22

### Xk65eicHSyw
- 16:44 -- 21:08
- 42:10 -- 46:00
- 1:10:52 -- 1:13:36
- 1:29:18 -- 1:31:22
