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

# If downloads fail with "Requested format is not available" or SABR warnings,
# yt-dlp is stale — YouTube breaks old versions quickly. Update it with:
#   processing/venv/bin/pip install -U "yt-dlp[default]"
# download.py and /api/search prefer processing/venv/bin/yt-dlp over PATH,
# so updating the venv copy is sufficient.
#
# If downloads fail with "n challenge solving failed" / "Some formats may be
# missing": YouTube requires solving JS challenges (since 2026-07). yt-dlp
# needs a JS runtime (brew install deno) plus the solver package yt-dlp-ejs
# (included in the yt-dlp[default] pip extra).
#
# If downloads die mid-stream with "HTTP Error 403: Forbidden" (a few % in):
# YouTube's PO-token enforcement invalidated that client's stream URLs.
# FIRST update yt-dlp (its maintainers rotate default clients to ungated
# ones; 2026-08-19 moved to visionos and fixed this). download.py tries the
# default clients first (2 attempts, since the 403s are intermittent), then
# falls back to player_client=web_embedded. If both break, sweep clients:
#   yt-dlp --extractor-args "youtube:player_client=CLIENT" -f "bestvideo..." --print format_id URL
# or install a PO token provider (bgutil-ytdlp-pot-provider).
#
# GOTCHA: if `processing/venv/bin/pip list | grep yt-dlp` shows version
# "None", the venv has duplicate yt_dlp-*.dist-info dirs and `pip install -U`
# silently does nothing (this pinned us to a stale version in 2026-08).
# Fix: pip uninstall -y yt-dlp; rm -rf venv/lib/python3.11/site-packages/yt_dlp*;
# pip install -U "yt-dlp[default]"

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
- Pipeline: find_red_clusters → merge_clusters → **merge_by_day_evidence** → filter_cut_bounded_phases → filter by min duration (35s) → **refine_boundaries** → add buffers
- **refine_boundaries**: a raw boundary from the 2s grid is only known to within one interval, which
  made the overlay lead vary between ~1s and ~4s. Each boundary window — (start−2s, start] for red-on,
  [end, end+2s) for red-off — is re-scanned at `REFINE_STEP` (0.25s) by seeking once and decoding
  sequentially (`_scan_window`), so buffers apply to the actual light transition. Output times are
  floats (2 decimals). Buffers: `ENTRY_BUFFER=2.0` before red-on, `EXIT_BUFFER=1.0` after red-off
- **merge_clusters**: merges adjacent red clusters when EITHER: (1) BOTH exit and entry boundaries are camera cuts (diff >= 40), using a 3-sample window around each boundary, OR (2) the gap is ≤100s and at least 60% of gap samples have R/G ≥ GAP_RED_THRESH (1.3) with no sample below GAP_MIN_FLOOR (1.05), indicating close-up shots during an ongoing night (close-up R/G ~1.5-2.1 vs daytime ~1.0-1.2). The fraction-based check tolerates occasional brief dips while the floor prevents merging across genuine daytime gaps.
- **merge_by_day_evidence** (second pass, S23+): newer seasons cut away from the red table for
  over a minute at a time during a night (the wolves' masked close-ups, the night graphic), so a
  night arrives as 14-60s red bursts that neither rule above reconnects, and each burst then dies
  to the 35s minimum (S23E24G1's first night was missed entirely; its second night was split).
  Day evidence = the player sidebar being on screen: it is visible throughout the day and never
  inside a night. Two substantial bursts (>= MIN_EVIDENCE_FRAGMENT=6s) at most MAX_EVIDENCE_GAP=300s
  apart are joined if no sidebar sighting lies between them. Sightings come from
  analyze_names.sidebar_visible (OCR of the narrow role-column strips, >= 3 role/未知 labels) sampled
  every 10s inside candidate gaps only, so OCR is loaded lazily and only runs for a few minutes of
  video (_make_gap_checker). Tiny flashes (a red costume in a close-up) neither extend a night nor
  break a chain. Boundaries stay red-light based (refined), never extended by evidence
- **filter_cut_bounded_phases**: removes phases where BOTH outer boundaries are camera cuts (both entry and exit diffs >= 40) — these are brief red-lit scenes, not real night phases. Phases assembled from >= 3 bursts are exempt (a real night whose outer bursts begin/end on cuts)
- Constants: `RED_THRESH=2.5`, `CUT_THRESH=40`, `GAP_RED_THRESH=1.3`, `GAP_ELEVATED_FRACTION=0.6`, `GAP_MIN_FLOOR=1.05`, `MAX_MERGE_GAP=100`, `MAX_EVIDENCE_GAP=300`, `MIN_EVIDENCE_FRAGMENT=6`, `MIN_PHASE_DURATION=35`, `ENTRY_BUFFER=2.0`, `EXIT_BUFFER=1.0`, `REFINE_STEP=0.25`, `SCAN_INTERVAL=2`, `CUT_WINDOW=3`
- Performance: ~40s per hour of 720p video with 3 threads (~1min sequential; GPU decoding via VideoToolbox is slower due to GPU→CPU transfer overhead)

### Name Mask Detection (analyze_names.py)
- Uses PaddleOCR **PP-OCRv6 medium** det+rec (paddleocr 3.7.0) to find Chinese role names (狼人,
  预言家, 女巫, etc.). Chosen 2026-10 by benchmark on 72 verified vertical role labels + 18 未知
  labels: v6 medium 69/72, v5 server (previous) 68/72, v5 mobile 59/72, all zero false roles; v6 is
  the smaller/faster model. Apple Vision cannot read the vertical labels (0/72). Model names live in
  OCR_DET_MODEL / OCR_REC_MODEL; _ensure_models downloads them into processing/models/ on first use
- Left + right edge crops are OCR'd in a **single batched `predict()` call** per frame
- Sets `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK` at import (offline-safe, faster init)
- **Local models**: weights stored in `processing/models/` (self-contained, no global cache dependency)
- **No aux models**: doc orientation, unwarping, textline orientation disabled (designed for scanned docs, hurt video frame detection)
- **Device fallback**: uses CUDA GPU if available, falls back to CPU (PaddlePaddle has no Apple MPS support)
- **Sidebar probes first** (probe_sidebar): OCR at 15/25/35/50/65/80/90% of the video. They decide
  hidden-roles broadcasts (>= 2 probes showing >= 2 未知) and pick the role-scan window: it starts
  60s before the first probe showing >= 4 role labels (games reach the sidebar at different times —
  S23E24G2 showed an intermission screen through the old fixed 1100-1400s window), falling back to
  1100s. The window is 300s at 10s intervals; extended scans cover the next 600s at 30s
- **Extended scan**: if one side is missing after the primary window, extends over the next 600s at 30s intervals
- **Lazy generator**: `sample_frames` yields frames on demand, stops reading when enough names found (typically ~4 frames instead of 30)
- **Exact-match only** (`text.strip() == role`): the role column shows the bare role name, while
  players' public notes ("没平民", "跳狼人") and the watermark contain role words too. Substring
  matching let notes widen masks into the notes column (S22 right masks came out 0.785 instead of
  ~0.862; some left masks 0.19 instead of 0.14). Notes are public claims, not spoilers
- Outer edge from **10th/90th percentile** role-box x-edges (a stray box can't widen it)
- **Masks cover the role column PLUS the note column**: inner edge extends NOTE_EXTEND (0.12 of
  frame width) past the role toward center, clamped (left <=0.32, right >=0.68) so it never reaches
  the stage. The director types a running opinion next to each role that gives it away as much as
  the name. Fixed extension, not measured (measuring tripped over centered banners: title, config
  line, news ticker)
- **Role map** (build_role_map): role_map = {left:[...], right:[...]}, each player
  {number, role, y0, y1} -- seat ID only, NO names (OCR of the stylized name tags was unreliable;
  the user wants seat numbers only). Rows cluster role boxes by y (_cluster_rows); reveal bands
  are midpoints between rows (_bands_from_centers). The role string is only a menu label (the
  viewer reveals real pixels)
- **Seat numbers are inferred from row position** (_infer_seats): seats run 1-6 top-to-bottom on
  the left and 7-12 on the right at a fixed pitch, so every anchored row (a seat badge OCR did
  read, outward of the role column) votes seat = anchor + round(dy / pitch) for every row; majority
  wins, so one misread badge can't shift the others and a row whose badge wasn't read still gets
  its seat. No anchor on a side -> standard layout geometry (SEAT_BASE / SEAT_ROW_SPACING /
  SEAT_FIRST_ROW_Y)
- **Misread role labels are recovered** (_recover_misread_roles + _snap_role): any short CJK box
  centered in the role column that isn't an exact role is a misread label (notes sit inward,
  badges outward), snapped by containment or edit distance 1 (械狼->机械狼, 狼人学->狼人,
  自神->白神). 未知 never snaps. Without this a misread row vanished from the role map
- **Hidden-roles broadcasts**: the broadcast shows 未知 instead of a role until it is revealed in-game,
  so the audience is already blind. _scan_range counts frames with >=2 未知 labels; >=2 such
  frames -> hidden_roles=True in metadata.json (extended scans skipped; the scan also stops
  early after 3 such frames with no roles). The viewer then starts with masks/overlay OFF
  (toggle still works as an override), badges the video in the library, and the role panel
  shows an explanation instead of rows. Titles don't mark these games; detection is purely from
  the sidebar labels and is unit-tested but not yet confirmed on a real hidden-roles video
- Raw OCR goes through ocr_items_in_frame (edge_ratio 0.30) -> _roles_from_items;
  detect_names_in_frame is a thin wrapper. analyze_name_regions_full() returns {name_masks,
  role_map, hidden_roles} (what analyze.py writes); analyze_name_regions() still returns masks only

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
- **Role reveal panel** (right-edge slide-out, hover the ROLES tab): default all-blind. Revealing
  opens the mask over that player's row so the real role shows through (_fillSegments renders the
  opaque fill in segments with gaps at revealed rows). Two modes (button pair, remembered per
  browser, default By role):
  - **By seat**: rows are seat numbers 1-12; click to reveal that seat's role
  - **By role**: rows are the roles in play, with NO seat shown; clones are indexed (平民 1..4) and
    the index->seat assignment is a random permutation generated once per video and stored in
    localStorage (werewolf.roleorder.<id>) so labels stay stable but leak nothing. Pick one to
    'blend in' as that role; once revealed the row shows which seat it was
  Clicking a WOLF (any role containing 狼) reveals/hides the whole wolf team in either mode,
  mimicking playing as a wolf who knows the pack. Blind/All buttons; the revealed set persists per
  video. Needs a role map (re-analyze older videos). Hidden-roles broadcasts show an explanation only
- Masks default ON for every loaded video (spoiler-safe), OFF for hidden-roles broadcasts; the toggle
  is a per-video override. With no detected night phases masks stay on throughout (a detection
  failure must not leak)
- **Mute button** beside the volume slider; volume/mute persist per browser
- **Mask mode** (`Mask: Full` / `Mask: Roles` button, per-browser via localStorage, default Full):
  metadata.json always stores the OCR'd role-name box. Full mode renders each mask extended
  outward to its frame edge (`_renderedBox`), hiding player avatars/names too; only the inner
  edge handle is shown and resizes write back through the inverse transform (`_storeRenderedBox`),
  so switching back to Roles mode keeps the detected box. "+ Mask" in Full mode adds an
  edge-anchored mask on whichever side has none; in Roles mode it adds a center mask
- "+ Mask" button to manually add mask regions when auto-detection fails
- Night phase markers on progress bar (red segments, draggable handles)
- **Edit persistence**: all edits (phase drags, add/remove phases, add/remove/resize
  masks, resets) POST to `/api/metadata` and are written into the video's
  metadata.json; auto-detected values are preserved in `original_night_phases` /
  `original_name_masks` on first save, and the Reset buttons restore those
- Fullscreen via Fullscreen API on wrapper element
- Sidebar with two tabs: video list + download management
- Download management: search YouTube, download+process, stop, delete
- Library items have a ↻ **Re-analyze** button (`POST /api/analyze`): re-runs analyze.py on the
  downloaded video (e.g. after detection improvements) and reloads metadata if that video is open.
  Replaces manual edits (confirm dialog)
- Info bar shows the open video's title (also set as the document title)
- Volume and user mute are remembered per browser (localStorage); the night auto-mute is never persisted
  - Stop during download deletes the partial dir; stop during analysis keeps the video
- Time display shows h:mm:ss above one hour
- Mute button (🔊/🔇) beside the volume slider. `userMuted` tracks a deliberate mute
  separately from the night auto-mute: dawn only unmutes if the user didn't mute, and
  unmuting during a night phase (masks on) takes effect at dawn rather than immediately
- Keyboard: Space=play, M=masks, F=fullscreen, arrows=±5s, N=next night start, Shift+N=previous

## API Endpoints (vite.config.js middleware)
- `GET /api/videos` - list videos with metadata.json (`hiddenRoles` flag included for the library badge)
- `GET /api/downloaded` - list all video dirs with hasVideo/hasMetadata flags
- `POST /api/search` - search @JCDSS channel via yt-dlp (body: {query}). Merges two
  sources, deduped by id, both filtered by all query keywords: (1) the 200 most recent
  uploads (cached 5 min) — covers broad queries, which YouTube's search tab caps at ~20;
  (2) the channel search tab `@JCDSS/search?query=…` — finds older episodes that have
  aged out of the recent window (the channel posts ~3 games/day, so 200 uploads ≈ 2 months;
  this is why S22E39/S22E41 returned "no results" in 2026-10 before source 2 was added)
- `POST /api/download` - start download+process job (body: {videoId})
- `POST /api/analyze` - re-run analysis on a downloaded video (body: {videoId}); 404 if no video.mp4, 409 if a job is running
- `GET /api/job-status` - poll active job status (`kind`: "download" | "analyze")
- `POST /api/stop` - stop active job (deletes dir only if still downloading)
- `POST /api/delete` - delete video dir (body: {videoId})
- `POST /api/metadata` - persist edited night_phases/name_masks to metadata.json (body: {videoId, night_phases, name_masks}); preserves originals in original_* fields
- metadata.json also carries `role_map` (per-player role/number/name/y-band) from analysis, read by the role-reveal panel
- `GET /<videoId>/*` - serve files from ../videos/

### Security (server is LAN-exposed: host 0.0.0.0, allowedHosts true)
- `videoId` validated against `/^[A-Za-z0-9_-]{6,20}$/` everywhere (blocks path traversal into rm/spawn/paths)
- Static file serving is confined to `videos/` via a resolved-path prefix check
- POST endpoints reject cross-origin requests (Origin header vs Host)
- Malformed URLs (bad percent-encoding) return 400 instead of crashing the middleware
- All `spawn()` calls have `error` handlers (missing binaries can't crash the server)
- Request bodies are capped at 1 MB (413); the server is LAN-exposed and bodies are buffered in memory

## Ground Truth - Night Phase Boundaries
Not every game has the same number of phases. Use these timestamps (±2s tolerance).
All 9 videos below achieve 100% detection accuracy (0 FP, 0 miss), re-validated after the 0.25s boundary refinement (benchmark.py: all GT OK, parallel == sequential, ~1.3x speedup).

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

### S23 test set (2026-10, generated by frame inspection; S23 nights are cut-heavy)
S23 broadcasts intercut nights with the wolves' masked close-ups and a night graphic, overlay a
transient (~6s) "天黑请闭眼" banner at night start, and hide the sidebar for the whole night. Ground
truth below was established by reading the red-light transitions and the sidebar frame by frame.
- xNDz6SStaLo (S23E24 第一局): 9:17 -- 13:13, 1:00:38 -- 1:05:55 (role map 12/12 verified)
- QNxo5hmWLN0 (S23E24 第二局, hidden-roles): 7:03 -- 9:46, 1:28:33 -- 1:35:07
- (S23E24 第三局 pZ0vo8VRDkA, S23E25 第一局 bzsBWNpIwpo, 第二局 fgw-4eUV0JE, 第三局 HpIM5xTU-t8:
  see benchmark.py GROUND_TRUTH once audited)
