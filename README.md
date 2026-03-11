# Werewolf Viewer

A spoiler-free video viewer for werewolf (狼人杀) tournament recordings. Automatically detects night phases and masks player role names so you can watch games without knowing who's who.

Built for [京城大师赛 (Beijing Masters)](https://www.youtube.com/@JCDSS) tournament videos, but works with any werewolf game recording that follows the standard table camera format with red ambient lighting during night phases.

## Features

- **Night phase detection** — Automatically identifies night phases by analyzing the red ambient lighting change, then overlays a black screen with muted audio during those segments
- **Role name masking** — Uses OCR to detect and cover player role labels (狼人, 预言家, 女巫, etc.) on the video overlay, preventing accidental spoilers
- **In-app download & processing** — Search YouTube, download videos, and analyze them directly from the web interface
- **Interactive controls** — Draggable night phase boundaries, resizable mask regions, manual mask addition, one-click jump to any night phase
- **Keyboard shortcuts** — Space (play/pause), M (toggle masks), F (fullscreen), arrow keys (±5s seek)

## How It Works

### Night Phase Detection

The system samples video frames every 2 seconds and measures the red-to-green color ratio in the bottom corners of the frame. Werewolf games use distinctive red ambient lighting during night phases (R/G ratio ≥ 2.5 vs ~1.0 during day). Frame-to-frame pixel diffs distinguish real lighting transitions from camera cuts.

- 3-thread parallel scanning for ~1.5x speedup
- ~40 seconds processing per hour of 720p video
- Validated against 6 ground truth videos with 100% accuracy (0 false positives, 0 misses)

### Role Name Detection

PaddleOCR (PP-OCRv5 server model) scans the left and right edges of video frames to locate Chinese role name text. Detected regions are merged into mask overlays that cover the text without obscuring player avatars or numbers.

- Models stored locally for self-contained deployment (~165MB)
- Auto-downloads models on first run if not present
- Adaptive scan range with fallback for late-appearing names

## Prerequisites

- **Python 3.11+** with pip
- **Node.js 20+** with corepack enabled (for pnpm)
- **yt-dlp** (installed via pip as a dependency)

## Quick Start

### 1. Clone and set up Python environment

```bash
git clone https://github.com/caizefeng/werewolf-viewer.git
cd werewolf-viewer

python3 -m venv processing/venv
source processing/venv/bin/activate
pip install -r processing/requirements.txt
```

### 2. Install frontend dependencies

```bash
corepack enable
cd web && pnpm install && cd ..
```

### 3. Start the dev server

```bash
cd web && pnpm dev
```

Then open http://localhost:5173 in your browser.

### 4. Download and process a video

You can do this directly from the web UI:

1. Use the **Search** panel on the right sidebar to find a video
2. Click **Download** — this downloads the video and automatically runs the analysis pipeline

Or via command line:

```bash
source processing/venv/bin/activate

# Download a video
python3 processing/download.py --video-id="VIDEO_ID"

# Analyze it (generates metadata.json with night phases + name masks)
python3 processing/analyze.py --video-id="VIDEO_ID"
```

> For video IDs starting with a dash, use `--video-id="-XXXX"`.

## Deployment

For background server deployment (persists after terminal close):

```bash
# Start
scripts/start.sh    # Serves on http://localhost:5173/

# Stop
scripts/stop.sh
```

## Project Structure

```
werewolf-viewer/
├── processing/              # Python video analysis
│   ├── analyze.py           # Main pipeline (parallel night + name detection)
│   ├── analyze_night.py     # Night phase detection (R/G ratio + frame diffs)
│   ├── analyze_names.py     # Role name detection (PaddleOCR)
│   ├── download.py          # YouTube video downloader (yt-dlp)
│   └── requirements.txt
├── web/                     # Vite + vanilla JS frontend
│   ├── index.html
│   ├── vite.config.js       # Dev server with API middleware
│   └── src/
│       ├── main.js          # App init, video list, download management
│       ├── player.js        # Video player with overlays and custom controls
│       └── style.css
├── scripts/                 # Server deployment scripts
│   ├── start.sh
│   └── stop.sh
└── videos/                  # Downloaded videos + metadata (gitignored)
```

## API Endpoints

The Vite dev server provides these API endpoints via middleware:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/videos` | List analyzed videos |
| GET | `/api/downloaded` | List all video directories |
| POST | `/api/search` | Search YouTube (body: `{query}`) |
| POST | `/api/download` | Download + analyze a video (body: `{videoId}`) |
| GET | `/api/job-status` | Poll active download/analysis job |
| POST | `/api/stop` | Stop active job |
| POST | `/api/delete` | Delete a video (body: `{videoId}`) |

## Configuration

### Video Analysis

Key constants in `processing/analyze_night.py`:

| Constant | Default | Description |
|----------|---------|-------------|
| `RED_THRESH` | 2.5 | R/G ratio threshold for night detection |
| `CUT_THRESH` | 40 | Frame diff threshold for camera cuts |
| `MIN_PHASE_DURATION` | 35 | Minimum night phase duration in seconds |
| `SCAN_INTERVAL` | 2 | Frame sampling interval in seconds |
| `ENTRY_BUFFER` | 3.5 | Seconds added before detected night start |
| `EXIT_BUFFER` | 2 | Seconds added after detected night end |

### OCR Models

PaddleOCR models are stored in `processing/models/` and downloaded automatically on first use. The system uses PP-OCRv5 server-grade detection and recognition models for Chinese text.

## License

[MIT](LICENSE)
