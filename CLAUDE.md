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
├── scripts/               # Server instances (see "Server instances" below)
│   ├── start.sh           # start.sh [prod|dev]: start an instance in the background
│   ├── stop.sh            # stop.sh [prod|dev]
│   ├── deploy.sh          # deploy.sh [REF] [--force]: move prod's worktree to a commit
│   └── dev-library.sh     # dev-library.sh ID... | --all: hard-link games into videos-dev/
├── .run/                  # Runtime files: <instance>.pid, <instance>.log (gitignored)
├── .prod/                 # Production git worktree, detached at the deployed commit (gitignored)
├── videos-dev/            # Dev instance library: hard-linked video.mp4 + copied metadata (gitignored)
├── processing/            # Python video analysis scripts
│   ├── venv/              # Python virtual environment (pyenv + venv)
│   ├── requirements.txt   # Dependencies: yt-dlp, paddleocr, paddlepaddle, opencv-python
│   ├── analyze.py         # Main pipeline: runs night + name analysis (parallel by default)
│   ├── analyze_night.py   # Night phase detection via R/G color ratio + frame diffs (threaded)
│   ├── analyze_cards.py   # Card-viewing (看牌) detection: seat tour (camera motion) or 2x2 split screen
│   ├── analyze_names.py   # Role name detection via PaddleOCR (lazy frame sampling)
│   ├── models/            # Local PaddleOCR model weights (gitignored, fetched on first use)
│   │   ├── PP-OCRv6_medium_det/  # Text detection model (in use, ~59MB)
│   │   ├── PP-OCRv6_medium_rec/  # Text recognition model (in use, ~73MB)
│   │   └── PP-OCRv5_server_*/    # Previous models, only benchmark_ocr.py uses them (~165MB)
│   ├── benchmarks/        # Performance benchmarks (tracked; the dir is in .gitignore, so new files need git add -f)
│   │   ├── benchmark.py       # Parallel vs sequential + ground truth validation
│   │   ├── benchmark_full.py  # Night + name + full pipeline profiling
│   │   ├── benchmark_hardware.py  # Full-analysis time + peak memory on this machine (README "Processing time")
│   │   └── benchmark_ocr.py   # OCR model configuration benchmark (server vs mobile)
│   └── download.py        # YouTube video downloader via yt-dlp
├── videos/                # Downloaded videos + metadata (not in git)
│   └── <video-id>/
│       ├── video.mp4      # Downloaded video file
│       ├── info.json      # {title, video_id} from YouTube
│       ├── metadata.json  # {night_phases, name_masks, role_map, ...} from analysis
│       └── viewer_state.json  # {bookmarked, position, duration, ...} bookmark + resume point
├── tests/                 # Browser end-to-end tests on the synthetic demo library
│   ├── requirements.txt   # playwright
│   └── e2e/               # harness.py, run.py, test_player.py, test_bookmarks.py, readme_screenshots.py
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

# Re-analyze but keep the user's edited nights / masks (original_* takes the new detection)
python3 processing/analyze.py --video-id="VIDEO_ID" --keep-edits

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

# Start / stop a server instance in the background (persists after terminal close)
scripts/start.sh          # prod: http://localhost:5173/, .prod worktree, videos/
scripts/start.sh dev      # dev:  http://localhost:5174/, this tree, videos-dev/
scripts/stop.sh [dev]

# Deploy committed code to production (refuses while a prod job runs)
scripts/deploy.sh         # HEAD; or scripts/deploy.sh <commit>

# Start web dev server interactively (must load fnm + corepack first)
eval "$(fnm env --use-on-cd)" && corepack enable && cd web && pnpm dev

# For video IDs starting with dash, use: --video-id="-XXXX"
```

## Server instances (prod / dev, since 2026-10-25)
The user watches games on the server while development goes on, so there are two:
- **prod** (`scripts/start.sh`, port 5173): runs from `.prod/`, a git worktree detached at the
  deployed commit, and serves the real library `videos/`. Its `processing/venv` and
  `processing/models` are symlinks to the main tree's (gitignored); `web/node_modules` is its own
  (`pnpm install` by deploy.sh when the lockfile changes). `scripts/deploy.sh [REF]` checks the
  worktree out at REF; the running Vite server picks it up itself (page reloads; a vite.config.js
  change restarts it and drops in-memory jobs, hence the refusal while `/api/job-status` shows an
  active job; `--force` overrides). Never edit files under `.prod/`.
- **dev** (`scripts/start.sh dev`, port 5174): runs from this working tree (hot reload) with
  `WEREWOLF_VIDEOS_DIR=videos-dev`. `scripts/dev-library.sh ID...|--all` hard-links video.mp4 and
  copies info.json/metadata.json, so dev analyses, edits and deletes never touch production.
  `VITE_INSTANCE=dev` makes the page say "dev" (header badge, amber top rule, tab title).
- Both bind 0.0.0.0. The e2e tests start their own throwaway servers on free ports.
- New analysis code reaches production videos only by re-running it over `videos/` (↻ in prod
  after a deploy, or a CLI script); videos with `original_*` fields carry the user's corrections.

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
  - **Why this feature (feature study 2026-10-15, 520 night + 520 day frames from the 13 GT videos)**:
    per frame, corner-max R/G is the best cheap color feature (day frames are tightly ~1.1, p90 <= 1.4
    in every season, so the 2.5 threshold has a wide margin and daytime "red" is < 1%); corner-min,
    lower-half red-pixel fraction, whole-frame red dominance and a red-hue mask were all worse on
    both axes. Its real limit is COVERAGE, not correctness: 25-30% of true-night frames in every
    season are not red at all because the camera is on close-ups or a graphic. That is why nights are
    assembled temporally (clusters + camera-cut structure) and, since S23, bridged with non-lighting
    evidence (sidebar absence). A night the camera never shows as a red table is still undetectable
  - Other cues checked: the "天黑请闭眼" night-start banner and the "天亮请睁眼" dawn banner exist
    only in S23 broadcasts (absent at all six S21/S22 starts) and last ~6s, so they cannot be the
    primary signal, but they are decisive DAY evidence where they exist and the merge passes use
    them (banner_in_frame, since S23E26); the top "第X天" day counter is intermittent and one
    operator skipped a number (E24 labelled day 2 as 第三天; E26G3's 34s day 2 never got one);
    Apple Vision cannot read the vertical sidebar labels. Sidebar absence is the only night cue
    found to hold across S21-S23
  - ROI: upper half of bottom 12% strip (h*0.88 to h*0.93), avoids UI overlays
  - Uses max(left, right) R/G ratio per frame
  - R/G >= 2.5 = red ambient light (night), ~1.0 = normal (day)
- Computes frame-to-frame pixel diff (`cv2.absdiff`, mean) to distinguish:
  - Real day/night transitions: small diff (~20-30), same scene with lighting change
  - Camera cuts (close-up ↔ table): large diff (~60-80), different scene
- Pipeline (`analyze_phases`, which returns `{night_phases, card_phases}`; `analyze_night_phases`
  is the nights-only wrapper the benchmarks use): scan → **find_card_phases** (看牌, see below) →
  **_mute_cards** (red samples before the first tour's end and inside every tour are ignored: no
  night precedes the card viewing, and the tour's close-ups of the red tablecloth read as night
  light) → find_red_clusters → merge_clusters → **merge_by_day_evidence** → **_cut_out_cards** (a
  merge never bridges a tour) → filter_cut_bounded_phases → filter by min duration (35s) →
  **refine_boundaries** → add buffers → **_link_first_nights**. All OCR (gap checks, banner checks,
  the card search's day checks, the dawn search) shares one lazily loaded `_Evidence` (OCR + capture),
  so OCR loads only when something needs it
- **_link_first_nights** (CARD_NIGHT_LINK=90): the night after each tour starts exactly where the
  tour ends -- the cut from the last seat close-up to the table, when the judge says 天黑请闭眼 (user
  request 2026-10-25: "the 看牌 phase can also be used to correct the beginning and the end of the
  first night"). A red night starting inside the tour (S22 first nights started 10-40 s early on the
  red tablecloth: E47G1 7:13 instead of 7:43, E48G3, E49G2; E49G1's even started at 0:16) or up to
  90 s after it is pinned there; S21's red light comes on 2-7 s after the cut, which the older ground
  truth used. If no night starts within 90 s the first night was missed and is inserted:
  - **hidden-roles broadcasts** (whose nights analyze.py no longer writes, see "Hidden-roles
    broadcasts" below; this stays benchmarked) show the table for 5-10 s, then cover the night with the
    commentators -- the very set shown just before the tour -- and cut back at dawn (S22E47 G2/G3,
    S22E48 G1). `_covered_night_end`: the pre-tour set (median 32x18 colour thumbnail of the scan
    samples 10-2 s before the tour) must return within COVER_WITHIN (30 s) of the tour and stay
    (mean thumbnail difference < COVER_SAME 20, gaps < COVER_GAP 12 s) for >= COVER_MIN (30 s); the
    night ends when it leaves (refined at 0.25 s), or when the red light goes off on the table it cuts
    back to (S22E47 G2: 13:32 -> 13:35, EXIT_BUFFER added). Was the first sidebar sighting, 35-50 s late
  - otherwise (S22E48 G2: the studio never switched the red light on for night 1, 8:43-13:17, so masks
    stayed off for all of day 1; user report 2026-10-25) the night runs to the first sidebar sighting
    (`first_sidebar_after`: OCR every DAWN_SEARCH_STEP=20 s from DAWN_SEARCH_FROM=150 s after the tour up
    to DAWN_SEARCH_TO=600 s, then bisected to ~2 s): 13:52, ~35 s late but never early. Matching the
    night's opening table shot can't do better there: dawn only removes the commentators'
    picture-in-picture, a 14.5-16 vs 11-14 mean-difference change, too close to separate reliably
- `analyze_phases(..., scan=...)` reuses a saved `scan_corner_redness()` result (timestamps, ratios,
  diffs, motions, thumbs) so the rest of the pipeline can be iterated without the minutes-long scan
- The scan also records `motions` (each 2 s sample reads the frame MOTION_DT = 0.25 s later and stores
  the mean change of 32x18 grey thumbnails: camera motion or a cut, for the card search) and `thumbs`
  (the sample's 32x18 colour thumbnail, ~1.7 KB, for recognising the pre-tour set). Cost: none
  measurable on a 1080p60 broadcast (300 s segment, one thread: 52.8 s vs 55.1 s without; decoding
  dominates); +40% only on the synthetic demo games, which decode almost for free. The card
  search's fine scans add ~10-25 s per candidate (usually 1-3), plus 1-2 OCR checks each.
  Threaded and sequential scans give identical arrays (checked on the demo game)
- **refine_boundaries**: a raw boundary from the 2s grid is only known to within one interval, which
  made the overlay lead vary between ~1s and ~4s. Each boundary window — (start−2s, start] for red-on,
  [end, end+2s) for red-off — is re-scanned at `REFINE_STEP` (0.25s) by seeking once and decoding
  sequentially (`_scan_window`), so buffers apply to the actual light transition. Output times are
  floats (2 decimals). Buffers: `ENTRY_BUFFER=2.0` before red-on, `EXIT_BUFFER=1.0` after red-off
- **merge_clusters**: merges adjacent red clusters when EITHER: (1) BOTH exit and entry boundaries are camera cuts (diff >= 40), using a 3-sample window around each boundary, and the gap is at most MAX_CUT_MERGE_GAP=180s (the cut rule used to be unbounded; S23's cut-heavy editing chained a night to stray red flashes up to 45 minutes later, yielding 50-80 minute "nights" on S23E25), OR (2) the gap is ≤100s and at least 60% of gap samples have R/G ≥ GAP_RED_THRESH (1.3) with no sample below GAP_MIN_FLOOR (1.05), indicating close-up shots during an ongoing night (close-up R/G ~1.5-2.1 vs daytime ~1.0-1.2), AND at least one of the two boundaries is a camera cut (window diff >= 40: the camera left the table). The fraction-based check tolerates occasional brief dips while the floor prevents merging across genuine daytime gaps. The cut condition was added 2026-10-26 (user report: S22E49 G3's nights 3 and 4 came out as one): S22 lights some short days PURPLE, R/G 1.55-1.6 on the table shot, which passes the ratio test, and when the camera stays on the table through dawn and dusk both boundaries are gradual -- the light going off and on again, i.e. a day. Of the 8 ratio joins in 31 games only those two had no cut at either end, and both were such days (S22E49 G3 27:15-27:38, S22E47 G1 28:27-28:57); the other six (S21 F2J0QK_3gUo x2, Jnf_dLaVNMU, WkVPdddUiio; S23 3oifxz_xLr4, 40RdPP2AuMs) are a dimmer red table inside a ground-truth night, each with a cut at one end. Either rule is vetoed for a gap of at least `BANNER_MIN_GAP=20`s when the phase banners show a day lay between (`gap_is_night(..., check_sidebar=False)`): an S23 self-destruct day can end on a cut-sized diff (61 at E26G3's dawn, the studio light jumps red→purple), so the cut rule alone is not safe there.
- **merge_by_day_evidence** (second pass, S23+): newer seasons cut away from the red table for
  over a minute at a time during a night (the wolves' masked close-ups, the night graphic), so a
  night arrives as 14-60s red bursts that neither rule above reconnects, and each burst then dies
  to the 35s minimum (S23E24G1's first night was missed entirely; its second night was split).
  Day evidence = (1) the player sidebar on screen (visible throughout a day, never inside a
  night), or (2) S23+ phase banners: "天亮请睁眼" within DAWN_BANNER_WINDOW=24s after the first
  burst's red-off, or "天黑请闭眼" from NIGHT_BANNER_LEAD=12s before to NIGHT_BANNER_LAG=6s after
  the second burst's red-on (banner_in_frame OCRs the top-center crop every 3s; the night banner
  precedes the red light by up to ~8s). Banners are checked only for gaps >= BANNER_MIN_GAP=20s.
  They were added for S23E26 G3, whose 34s self-destruct day (dawn 30:00, 自爆 30:20, night
  30:34) never brought the sidebar back, so sidebar evidence alone glued nights 2 and 3 into a
  7-minute "night". Two substantial bursts (>= MIN_EVIDENCE_FRAGMENT=6s) at most
  MAX_EVIDENCE_GAP=240s apart (longest real in-night gap seen: 152s, E26G3's wolves' discussion
  during night 1; the cap was 120s before E26, which split that night) are joined if (a) at least
  one gap boundary is a camera cut (frame diff >= CUT_THRESH at the exact boundary sample: the
  camera LEFT the table) and (b) no day evidence lies between them. **The 240s cap applies only
  when the broadcast shows phase banners** (`gap_is_night.has_banners()`: a night-start banner at
  one of the first three substantial bursts, checked only if some gap is 120-240s); otherwise
  `MAX_EVIDENCE_GAP_NO_BANNERS=120` as before. Reason: the pre-game red-light card-dealing segment
  sits 186-256s before the first night with no sidebar after it, and in S21/S22 (no banners)
  nothing else tells it from an in-night gap -- a flat 240s cap glued it onto the first night of
  65R0r19JyYk, Xk65eicHSyw and F2J0QK_3gUo. With banners, the first night's 天黑请闭眼 keeps it apart.
  (a) is what keeps S21/S22 intact: those games often have a self-destruct followed by an immediate
  second night ~30s later with no sidebar in between, but there the light goes off and on while the
  camera stays on the table (gradual boundaries, diffs 10-36), whereas S23 fragments always end on a
  cut (diffs 50-84). Without (a) six of the nine reference videos merged real night pairs. Sightings come from
  analyze_names.sidebar_visible (OCR of the narrow role-column strips, >= 3 role/未知 labels) sampled
  every 10s inside candidate gaps only, so OCR is loaded lazily and only runs for a few minutes of
  video (_make_gap_checker). Tiny flashes (a red costume in a close-up) neither extend a night nor
  break a chain. Boundaries stay red-light based (refined), never extended by evidence
- **filter_cut_bounded_phases**: removes phases where BOTH outer boundaries are camera cuts (both entry and exit diffs >= 40) — these are brief red-lit scenes, not real night phases. Phases assembled from >= 3 bursts are exempt (a real night whose outer bursts begin/end on cuts)
- Constants: `RED_THRESH=2.5`, `CUT_THRESH=40`, `GAP_RED_THRESH=1.3`, `GAP_ELEVATED_FRACTION=0.6`, `GAP_MIN_FLOOR=1.05`, `MAX_MERGE_GAP=100`, `MAX_CUT_MERGE_GAP=180`, `MAX_EVIDENCE_GAP=240`, `MAX_EVIDENCE_GAP_NO_BANNERS=120`, `MIN_EVIDENCE_FRAGMENT=6`, `BANNER_MIN_GAP=20`, `DAWN_BANNER_WINDOW=24`, `NIGHT_BANNER_LEAD=12`, `NIGHT_BANNER_LAG=6`, `MIN_PHASE_DURATION=35`, `ENTRY_BUFFER=2.0`, `EXIT_BUFFER=1.0`, `REFINE_STEP=0.25`, `SCAN_INTERVAL=2`, `CUT_WINDOW=3`
- Performance (2026-10-26, `benchmarks/benchmark_hardware.py` on this Mac mini: Apple M4, 4 performance +
  6 efficiency cores, 16 GB; every library video is 1080p60 AV1, ~1.45 GB per hour, decoded in
  software by OpenCV): the corner scan decodes every frame, ~2 min per hour of video with 3 threads
  (it was ~40 s per hour on 720p video; GPU decoding via VideoToolbox was slower due to GPU→CPU
  transfer overhead). The card search adds ~15 s and the lazy OCR evidence checks (banners every 3s
  in short windows, sidebar every 10s inside candidate gaps) 0-1.6 min (a hidden-roles game has few
  candidates); the role-OCR subprocess runs 3-6 min alongside. Full analysis 3.1-6.7 min for 45-148
  min games, 5.4-7.6 cores busy on average, peak RSS ~2.9 GB (main 1.2-1.3 GB + OCR child 1.6-1.7
  GB). Two at once (the server's default slots): 7.4 + 7.9 min against 3.7 + 5.4 alone, only ~14%
  more throughput, 5.6 GB together. Efficiency cores only (`taskpolicy -c background`): 2.0x as long.
  A 1.08 GB download took 43 s (~27 MiB/s). The README's Requirements section quotes these numbers;
  re-measure after changes that move them (a macOS daemon, audiomxd, held one core throughout)

### Card Viewing (看牌) Detection (analyze_cards.py, since 2026-10-25)
- What it is: after the pre-game (commentators, player introductions) the director tours the twelve
  seats in order (1 -> 12 or 12 -> 1) while each player checks their role card, then cuts to the
  table wide shot as night 1 falls. Same in S21, S22 and S23 up to E27, open and hidden-roles
  broadcasts alike; 35-55 s; nothing on screen labels it. From S23E28 on the broadcast shows a split
  screen instead (see "Split screen" below). A broadcast can deal twice before day 1 (re-deal):
  EC-1bimFjo4 (S21E05 G2, 6:48 and 15:06), pZ0vo8VRDkA (S23E24 G3, 7:28 and 13:47), QNxo5hmWLN0
  (S23E24 G2, 6:27 and 16:39 -- the first attempt was abandoned at dawn, commentators in between)
- **Signal: camera motion.** The commentators, the introductions and the night table shot hold still;
  the tour is seat close-ups joined by fast pans. Corner redness can't separate it from the night
  (the tablecloth behind seats 10-12 is red). The S23 night graphic, birthday celebrations, day-time
  camera drifts etc. move too, but slowly (pans 1-25% vs 24-63% for tours)
- **Coarse** (`coarse_cores`, from the night scan's `motions`): runs of 2 s samples with motion >=
  CARD_COARSE (12), gaps <= CARD_BRIDGE (12 s, a held close-up), >= CARD_MIN_CORE (16 s), starting
  before CARD_SEARCH_END (45 min). Until 2026-10-27 that limit held only until the first run started,
  so a game with no tour had candidates fine-scanned all through it (up to CARD_MAX_SCANS, e.g. S23E28
  G1 at 1:26:06); the three S23E28 analyses each spent ~1 min on that
- **Fine** (`fine_scan` around each core +-60 s, widened once if the run reaches the window edge):
  samples every 0.5 s, each with a pair 0.25 s later (32x18 grey thumbs): `motion` (change over
  0.25 s), `change` (over 0.5 s; > CARD_CUT 25 = a cut or a pan step), corner redness, thumbs.
  `shots_from` splits at every change; `grow_tour` grows the core over short shots until a shot >=
  CARD_LONG_SHOT (15 s) on each side, reports cut midpoints (shot start - 0.25 s). A shot only counts
  as inside the core if it overlaps it by > 1 s (the core's first coarse sample often straddles the
  cut from the commentators, which once grew a tour back over 3 minutes of them)
- **Night table shot trimming** (`_night_shot`): hidden-roles broadcasts show the night's table for
  only 5-10 s before the commentators, short enough to pass for one more close-up. It is (1) the first
  still shot after the core in which the red light comes on (first sample R/G < 1.8, later >= 2.5;
  "still" allows a moving sample or two, since the light switching on is itself a big change), or (2)
  when the long shot after the run looks like the long shot before it (same commentators' set, mean
  thumbnail difference < SAME_SET 15) the last still red shot starting within 15 s of that return.
  (1) is not searched inside the core: close-ups settling on the red tablecloth after a pan look the same
- **Accept** (`is_tour`): length 25-80 s and pans >= 30% and moving >= 30%; a slower tour (S21 holds
  each seat longer: F2J0QK_3gUo pans 24%) also passes at >= 15% / 20% when the red light comes on within
  CARD_RED_WITHIN (30 s) of its end. No tour is in daytime: a candidate with the player sidebar up
  3 s / 33 s before it (`day_seen`, 1-2 OCR checks) is rejected, which matters because the night
  search ignores all red light before the first tour (a false tour on day 1 would erase night 1).
  The first accepted tour is 看牌; later candidates are only a re-deal: within CARD_REDEAL_WITHIN
  (15 min) and before the first day, where the search stops. At most CARD_MAX_SCANS (6) fine scans
- **Split screen** (`find_grid`, user report 2026-10-27: "S23E28 didn't have 看牌 phases"): the three
  S23E28 games show no tour; after the commentators they cut to a 2x2 grid of four fixed table
  cameras, three seats each, for 21-24 s while all twelve players check their cards at once, then to
  the night table (天黑请闭眼 over the grid's last 0.5 s). Nothing moves, so no coarse core covered it.
  `find_card_phases` searches for it only when no tour is accepted, so tour games behave as before
  - Coarse (`centre_lines`, on the scan's 32x18 colour thumbnails): the grid's seams lie exactly on
    the frame's centre lines, which are thumbnail block edges (60 px at 1080p, 40 at 720p). Across the
    horizontal one (top quadrants end on white tables, bottom ones start on dark walls) the card grids
    score 2.4-6.8 (contrast across it over the lines beside it, the weaker half); other pictures
    mostly < 1, single samples up to 4.2. The vertical one is weak at that scale (both top quadrants
    are dark there). Runs >= GRID_COARSE (1.6) lasting >= GRID_MIN_CORE (10 s), one sample may miss
    (`coarse_cores` on this score). At 1.6 only the three S23E28 grids pass the red-light rules below
    across 34 cached games; at 1.4 four look-alikes would also need the seam check
  - Verify (`grid_seams`, 3 full frames at 25/50/75% of the run, 2 must pass): each of the four half
    seams' median step across the centre line over the median step 3-8 px beside it; the weakest >=
    GRID_SEAM (3.0). Card grids 3.7-23 per frame (pixel-exact seams, no border), single pictures < 1,
    three-panel layouts (one seam missing: S22E47 G1 9:28, S23E28 G1 night 1) <= 2.8
  - Night shows use 2x2 grids too (the wolves: S21 F2J0QK_3gUo 12:22 and 29:46, S22 d3jNiPSqMuI
    26:20), and they pass the seam check. So the search stops at the first run after red light held
    >= GRID_NIGHT_RUN (6 s) (`night_before`: nothing before the card viewing is night; the S23 games
    have no such red before it, S21/S22 pre-games had some, where the search would simply stop: a
    missed card viewing, never a false one); it also needs red light within CARD_RED_WITHIN after the
    grid (`red_after`) and rejects daytime (`day_seen`). Only the first grid is taken: no re-deal has
    been seen in this format, and a later grid may be the wolves'
  - Edges (`_grid_edge`): outward from the run's first/last sample at REFINE_STEP until a frame
    scores < GRID_EDGE_SEAM (1.5); the cut is the middle of that step. Lower than GRID_SEAM because
    the grid dims with the studio at nightfall (S23E28 G1: 2.75-3.8 for the last 1.2 s, which a 3.0
    edge cut short). Checked 2026-10-27: the grid search alone (no tour search first) on all 31 cached
    games with video finds exactly the three S23E28 grids, each within 0.4 s of the cuts on the frames
- **Ground truth** (28 games, every tour checked on frames: the shot before is the commentators, the
  first/last tour shot a player close-up, the shot after the table; research features + simulation
  in the session scratchpad): S21 -ESYZWvQMH4 7:35-8:18, 65R0r19JyYk 11:44-12:27, EC-1bimFjo4
  6:48-7:26 + 15:06-15:44, F2J0QK_3gUo 9:35-10:22, ieLaR4NBPz4 10:28-11:10, Jnf_dLaVNMU 10:54-11:42,
  WkVPdddUiio 5:24-6:05, Xk65eicHSyw 15:55-16:40 (starts ~2.5 s early: a failed green-screen key split
  the commentators' shot), ZusP81Ycn-U 6:38-7:27; S22 d3jNiPSqMuI 7:06-7:42, iDD3JgXWA-0 8:29-9:09,
  7SG4f3ZpZP0 8:48-9:26, Im5713oy3b4 8:00-8:36, 9Yij3uRUp1M 7:50-8:44, Dv0dRH80XGo 6:40-7:21,
  zHCN-nyQ9jA 6:43-7:26, 02bLRRi6RZk 5:49-6:30, zla5T_T4UKQ 6:15-6:54; S23 xNDz6SStaLo 8:37-9:17,
  QNxo5hmWLN0 6:27-7:03 + 16:39-17:20, pZ0vo8VRDkA 7:28-8:05 + 13:47-14:23, bzsBWNpIwpo 10:24-11:10,
  fgw-4eUV0JE 5:45-6:21, HpIM5xTU-t8 6:17-6:56, X5J6PIMh368 6:28-7:07, 3oifxz_xLr4 6:37-7:15,
  40RdPP2AuMs 7:14-7:52, CBZfebaxD0E 7:30-8:07; split screens (S23E28, 2026-10-27) 40WQgtMozXM
  10:15-10:39, VP2EVqrsWOE 7:49-8:11, 8myFCIe-Yeo 4:51-5:14 (their first nights, in FIRST_NIGHT_GT, end
  14:50 / 12:48 / 9:29; before the fix night 1 started on the red light, 10:40 / 8:09 / 5:15, G2's 2 s
  inside the grid). 31/31 tours found, 0 false tours. Final tour run: every end within 0.25 s of the marked second, every start too except Xk65eicHSyw (2.75 s early); the 8 look-alikes that reached a fine scan (pre-game in ZusP81Ycn-U, bzsBWNpIwpo and Jnf_dLaVNMU; inside night 1 and after dawn in CBZfebaxD0E) scored pans 0-20% / moving 2-25%, the tours 24-63% / 34-62% and 36-54 s

### Name Mask Detection (analyze_names.py)
- Uses PaddleOCR **PP-OCRv6 medium** det+rec (paddleocr 3.7.0) to find Chinese role names (狼人,
  预言家, 女巫, etc.). Chosen 2026-10 by benchmark on 72 verified vertical role labels + 18 未知
  labels: v6 medium 69/72, v5 server (previous) 68/72, v5 mobile 59/72, all zero false roles. Speed
  is NOT the reason: on this CPU (10 cores, no CUDA) v6 medium and v5 server both take ~7-8s per
  frame for the two 1080p edge crops and ~3s per sidebar-strip check (an earlier "4x faster" figure
  was measured under heavy background load and was wrong). cpu_threads has no effect;
  text_det_limit_side_len 736/640 gives no speed-up (640 scored 71/72 but on one benchmark only).
  Apple Vision cannot read the vertical labels (0/72). Model names live in OCR_DET_MODEL /
  OCR_REC_MODEL; _ensure_models downloads them into processing/models/ on first use
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
- **Vertical boxes only** (`item["vert"]`, pixel h > w, set in ocr_items_in_frame): the sidebar's
  role labels are the only vertical role text; notes, name tags, the config line and the watermark
  are horizontal. A horizontal exact match does occur: the 0.30 edge crop cuts the bottom-left
  "配置: 机械狼通灵师" / "假面舞会" config line to a bare "机械狼" / "假面" (S22 and S23E26 G2-G4).
  Before the filter that one box added a phantom seat-7 row on the left AND stretched the
  percentile role column over the note column, where "验7平民" then snapped to 平民 and outvoted
  the real 通灵师 at seat 3. _recover_misread_roles also only snaps vertical boxes, measures the
  column by median center/width, and tags its boxes `recovered` so they vote at half weight in
  _cluster_rows (a snapped label never outvotes an exactly read one). build_role_map drops any
  row whose inferred seat falls outside the side's six seats (1-6 left, 7-12 right)
- Outer edge from **10th/90th percentile** role-box x-edges (a stray box can't widen it)
- **Masks cover the role column PLUS the note column**: inner edge extends NOTE_EXTEND (0.17 of
  frame width) past the role toward center, clamped (left <=0.32, right >=0.68) so it never reaches
  the stage. The director types a running opinion next to each role that gives it away as much as
  the name. Fixed extension, not measured (measuring tripped over centered banners: title, config
  line, news ticker). It was 0.12 until 2026-10-25: a full note line ("觉得3-5-8-9有身份" in S22,
  "11不是女巫就是混子" in S23) reaches ~0.131 past the ribbon, so its last character showed, and the
  user had widened S22E47 G1's masks by hand to exactly 0.172 on both sides. DEFAULT_MASKS (no labels
  read) cover 0.05-0.30 / 0.70-0.95 for the same reason
- **Role map** (build_role_map): role_map = {left:[...], right:[...]}, each player
  {number, role, y0, y1} -- seat ID only, NO names (OCR of the stylized name tags was unreliable;
  the user wants seat numbers only). Rows cluster role boxes by y (_cluster_rows, which also keeps
  the median label box ty0..ty1 per row). The role string is only a menu label (the viewer reveals
  real pixels)
- **Reveal band = the row's own label box ± BAND_PAD (0.035), kept ≥ BAND_GUARD (0.013) inside the
  midpoints to the neighbouring rows.** Each role_map entry stores `label: [ty0, ty1]` (median
  label box) and `span: [mu, md]` (midpoints, from _bands_from_centers, also used to attach seat
  badges) plus a precomputed y0/y1; **the viewer recomputes the band from label/span with its own
  BAND_PAD / BAND_GUARD (player.js, same values), so retuning is a JS edit with no re-scan** (older
  metadata without label/span falls back to y0/y1). Bands used to run midpoint to midpoint; S22
  ribbons end within ~0.005 of the midpoint and the next starts ~0.005 past it, so a midpoint
  boundary showed the neighbour's ribbon tip, whose colour gives the faction away (user report
  2026-10-15). The first fix used 0.02/0.02 and read as too narrow; 0.035/0.013 opens yc ± 0.067
  on a 2-character row (ribbon ± ~0.075) with 6-10px to the neighbour's ribbon. Rows closer than
  0.03 fall back to the guarded midpoints. Reveal keys are side:seat
- `processing/update_role_maps.py [ID...]` re-scans only the sidebar roles (~2 min/video) and
  rewrites role_map / hidden_roles (and name_masks when never hand-edited) -- use it after role-map
  changes instead of ↻ re-analyze, which also replaces manual night/mask edits
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
- **Role list** (ROLE_NAMES): S23 configurations added 2026-10-18 after a sweep of untested
  boards -- 诡术之境 (诡术师, wolf-side; 魔术师, 定序王子, 狼术师 were known), 青丘夜影 (白泽 god, 九尾
  wolf-side, labelled "九尾"), 盗宝大师 (盗宝大师 shows a RED ribbon, i.e. wolf-side in this board;
  摄梦人, 蒙面人, 狼王), 假面舞会 S23 (假面 red). When a game shows '?' seats or a wrong name, add the
  role here; the sweep found two real roles one edit away from known ones (诡术师/狼术师,
  白泽/白痴) that edit-distance snapping silently renamed before the consistency rule below
- **Consistently read unknown labels are kept as read** (_recover_misread_roles,
  CONSISTENT_LABEL_FRAMES=3): a role-column label that OCR returns identically in >= 3 frames is
  a real label, so it becomes the role name even if ROLE_NAMES does not know it (九尾 before it was
  added) and it is never bent to a known name by edit distance ("edit" in _snap_role_kind);
  containment and the 机械 prefix still apply, and a one-off misread still snaps. A consistent
  misread of a KNOWN name is handled by ROLE_ALIASES ("alias" kind, checked right after exact):
  自神 -> 白神, which the S22 ribbon font produces in every frame (the first re-scan with the rule
  labelled three S22 seats 自神). Add to that table when a re-scan prints "Labels kept as read"
  for something that is not a real role
- **Annotated labels** (COMPOUND_ROLE_PREFIXES, checked first in _snap_role): the broadcast labels a
  机械狼 that copied a role with the copied role instead of its own name ("机械通灵" on S23E27 G3
  seat 2, a taller 4-character ribbon; "机械预言", "机械女巫" presumably). Any label starting with
  机械 maps to 机械狼: the panel names the wolf, whatever it learned, and the wolf team includes it
- **Faction from ribbon colour** (`_ribbon_colour` in ocr_items_in_frame, medians per row in
  _cluster_rows, `faction: "wolf" | "good" | ""` per role_map entry): the broadcast paints wolf
  ribbons red and everyone else green (S23) or cream (S22 villagers). The measured box is the
  label box **narrowed 15% per side and grown 25% vertically** (the ribbon core); the fractions
  of red-hued and green-hued saturated pixels (S>60, V>35) are counted; wolf = red >=
  RIBBON_RED_MIN (0.2) and red > green. Measured with that box on four S22/S23 games: wolves red
  0.43-0.69 (green <= 0.02), every good-side ribbon red <= 0.01. The first version grew the box
  30% SIDEWAYS and caught the red vote/badge markers beside a ribbon early in a game; on cream
  S22 villagers no green outvotes them, so two 平民 of S22E41 G2 came out "wolf" (user report
  2026-10-19). The viewer's `_isWolf(player)` is faction == "wolf" OR the name contains 狼: colour
  only ever adds wolf-side roles whose names do not say wolf (假面, 盗宝大师, 九尾, 诡术师) and can
  never demote a named wolf; build_role_map stores faction "wolf" for any role name containing 狼
  regardless of colour, because S22 recolours a 机械狼's ribbon over the game (cream while it has
  learned a villager -- "学3机械平民" on S22E41 G3 seat 2 at 20 min -- red once it holds the knife
  at 40 min), so an early scan can see no red at all
- **Every seat is in the role map, recognised or not** (build_role_map): seats 1-6 / 7-12 get their
  band from a 6-row layout fitted by least squares to the rows that were read (_fit_layout:
  first-row centre + pitch, sanity ranges LAYOUT_PITCH_RANGE / LAYOUT_FIRST_RANGE, constants
  SEAT_FIRST_ROW_Y / SEAT_ROW_SPACING as fallback). Measured across S21-S23 the rows sit at
  0.117 + 0.16·i within 0.005, so seat reveal never depends on a label being read; an
  unrecognised seat keeps role "" and the viewer lists it as 未识别 (last in By role). A video with
  no labels at all still gets the standard 12-seat map (with default masks)
- **Hidden-roles broadcasts**: the broadcast shows 未知 instead of a role until it is revealed in-game,
  so the audience is already blind. _scan_range counts frames with >=2 未知 labels; >=2 such
  frames -> hidden_roles=True in metadata.json (extended scans skipped; the scan also stops
  early after 3 such frames with no roles). The viewer then starts with masks/overlay OFF
  (toggle still works as an override), badges the video in the library, and the role panel
  shows an explanation instead of rows. Titles don't mark these games; detection is purely from
  the sidebar labels, confirmed on S23E24 G2/G3 and S23E25 G3
- **No nights for hidden-roles broadcasts** (analyze.py, user request 2026-10-26: "For hidden role
  games no night phase is needed at all"): the night detector still runs (its 看牌 tours are kept,
  and its hidden-roles first nights stay in FIRST_NIGHT_GT), but metadata.json gets
  `night_phases: []` -- a night there only added markers, the Night chip and, with masks forced on,
  a blackout and mute over the commentators. `--keep-edits` still keeps nights a user added
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
  Wolf-side players come in two kinds (PACK_WOLF_ROLES / LONE_WOLF_ROLES in player.js,
  `_wolfKind`): **pack** wolves wake together and know each other (狼人, 狼王, 白狼王, 黑狼王,
  狼美人, 狼术师 of 魔幻对决, 诡术师 of 诡术之境 -- two different roles), **lone** wolves neither meet
  the pack nor are known to it (机械狼, 假面, 盗宝大师, 九尾/九尾狐 of 青丘夜影, a 混血儿 that copied a
  wolf, 隐狼). Clicking a pack wolf reveals/hides the whole pack and never a lone wolf; clicking a
  lone wolf reveals that seat only. Wolf-side comes from the ribbon colour (faction) and the kind
  from the role name; an unknown red role is pack if its name contains 狼, else lone (never show
  more than the player would know). Rules checked on the web 2026-10-18 after the user corrected
  a first version that revealed every red ribbon as one team. In By seat mode the paw marker
  (dimmed for lone wolves) and its tooltip appear only on revealed rows (marking wolf seats up
  front gave the game away the moment the panel opened; user report 2026-10-15); By role rows
  keep it since the role name says wolf anyway. 白泽 (青丘夜影) is a correct role name, good side. Blind/All buttons; the revealed set persists per
  video. Needs a role map (re-analyze older videos). Hidden-roles broadcasts show an explanation only
- **Per-player wire frames on the masks** (`.name-mask-frame`, drawn by createNameMasks from the
  role map): one thin gold outline per seat band (dim while covered, glowing around a revealed row)
  with the seat number in the outer corner, so a mask reads as the sidebar's six slots. Gold was
  chosen because it is not the mask's dark navy/crimson. Videos without a role map get plain masks
- Masks default ON for every loaded video (spoiler-safe), OFF for hidden-roles broadcasts; the toggle
  is a per-video override. With no detected night phases masks stay on throughout (a detection
  failure must not leak)
- **Mute button** beside the volume slider; volume/mute persist per browser
- Headless UI checks run with Playwright installed in `processing/venv` (`processing/venv/bin/pip install playwright`;
  the chromium-headless-shell lives in ~/Library/Caches/ms-playwright). A scratch venv under /tmp decayed after
  three days (macOS purges unused /tmp files), which is why it moved here (2026-10-19)
- UI gotchas found by headless inspection (Playwright chromium-headless-shell works in this session;
  Google Chrome headless does not): (1) #role-panel must keep overflow visible -- its ROLES tab and
  hover trigger are ::after/::before placed outside the box, and overflow-y:auto clipped them so the
  panel could never open; the row list scrolls in .rp-body instead. (2) .name-mask has no border --
  the opaque .name-mask-fill must reach the box edge or a 1px sliver of video shows at the frame edge
  in Full mode; the crimson edge lines are inset box-shadows on the fill, and Full-mode masks overshoot
  the frame edge by 2px against subpixel rounding. (3) In fullscreen the browser forces the wrapper
  to fill the screen (UA !important rules; author CSS cannot resize it) and the video letterboxes
  inside, while masks are fractions of their container -- on a 16:10 MacBook screen every reveal
  gap drifted off its row. `_fitMasksToVideo` pins #name-masks to the video's content box on
  fullscreenchange/resize/loadedmetadata and clears the inline geometry on exit. (4) `#video-list li`
  sets `word-break: break-all` for long titles; episode headers override it with `white-space:
  nowrap` (only the date may ellipsize) -- without that, adding the "★n" count split "S01E01", the
  date and "2 games" mid-word in the 260px sidebar. The bookmark suite asserts one-line headers and
  info bar at 1600 and 1366 wide. (5) `load()` on a media element (switchVideo's reset, a new src)
  sets `paused` WITHOUT firing "pause", and drops the "pause" a `pause()` just before it had queued
  (HTML spec: the load algorithm removes pending media-element tasks): opening another game while
  one played left the pause icon over the paused game (user report 2026-10-26). The play button
  also redraws on "emptied" and "loadstart". (6) The same load rewinds to 0 while `duration` is NaN,
  so the timeupdate redraw (which needs a duration) left the progress bar alone, and a game opened
  without a resume point never seeks: the played and buffered bars kept the previous game's place
  until playback started (user report 2026-10-27). `_updateProgress` (time display + both bars,
  empty while the duration is unknown) also runs on "emptied" and "loadedmetadata"
- **Mask mode** (`Mask: Full` / `Mask: Roles` button, per-browser via localStorage, default Full):
  metadata.json always stores the OCR'd role-name box. Full mode renders each mask extended
  outward to its frame edge (`_renderedBox`), hiding player avatars/names too; only the inner
  edge handle is shown and resizes write back through the inverse transform (`_storeRenderedBox`),
  so switching back to Roles mode keeps the detected box. "+ Mask" in Full mode adds an
  edge-anchored mask on whichever side has none; in Roles mode it adds a center mask
- "+ Mask" button to manually add mask regions when auto-detection fails
- Night phase markers on progress bar (red segments, draggable handles)
- **Card viewing (看牌)** from metadata `card_phases`: teal segment(s) on the progress bar
  (`.card-marker`, tooltip "看牌 m:ss – m:ss", not editable) and teal rows in the left jump panel
  (`.card-jump-group`: a small card glyph + start/end buttons), placed before the night that follows
  them; the panel's tab reads PHASES (it was NIGHTS) and shows even for a game with no nights (hidden
  roles). The status line says "看牌 at m:ss". Masks now show from `min(first night end, first card
  end)` (and never during a night): the card viewing ends as night 1 begins, so a missed first night
  can no longer leave day 1 unmasked
- **Edit persistence**: all edits (phase drags, add/remove phases, add/remove/resize
  masks, resets) POST to `/api/metadata` and are written into the video's
  metadata.json; auto-detected values are preserved in `original_night_phases` /
  `original_name_masks` on first save, and the Reset buttons restore those. Saves go one at a
  time (`saveMetadata` chains `_save`), each with the version the page loaded or the previous
  save returned; a 409 reloads the metadata (see /api/metadata)
- Fullscreen via Fullscreen API on wrapper element
- Sidebar with two tabs: video list + download management
- Download management: search YouTube, download+process, stop, delete
- **Several jobs at once** (since 2026-10-15): every search row has its own Download/Stop button and
  progress bars, and ↻ re-analyze can run on several library rows. The server keeps a job per video
  (one job per video at a time) and a FIFO queue with separate slot limits: `MAX_DOWNLOADS=3`
  (network-bound) and `MAX_ANALYSES=2` (each analysis keeps 5-8 cores busy and peaks near 3 GB: 3 scan
  threads + an OCR subprocess; on this 10-core M4 two side by side give only ~14% more throughput than
  one after the other, see Performance above); override with env `WEREWOLF_MAX_DOWNLOADS` / `WEREWOLF_MAX_ANALYSES` before
  `scripts/start.sh`. Phases: download jobs go queued → downloading → waiting → processing → done,
  analyze jobs start at waiting; rows show "queued #n" while a job waits for a slot. The front end
  runs ONE poller (`pollJobs`, 2s) for all jobs and stops it when none is active; a library row
  with a running job gets `.busy` (spinning ↻, ↻ and × disabled); finishing a job refreshes the
  library and reloads the open video's metadata if it was re-analyzed. Elapsed times come from the
  server as durations (`phaseElapsedMs`), so LAN clients with a different clock show correct timers.
  Deleting a video with a running job is refused (409); stop it first.
- **Editing vite.config.js restarts the dev server** (Vite watches it): in-memory jobs are lost, and
  although the detached download/analysis processes keep running, nothing starts the analysis
  after an orphaned download finishes. Check `/api/job-status` AND `videos/*/*.part` before
  touching vite.config.js while someone may be using the app
- Library items have a ↻ **Re-analyze** button (`POST /api/analyze`): re-runs analyze.py on the
  downloaded video (e.g. after detection improvements) and reloads metadata if that video is open.
  Replaces manual edits (confirm dialog)
- **Library grouped by episode** (loadVideoList + parseTitle in main.js): one header per SxxEyy
  showing the broadcast date (YYMMDD in the title → 20YY-MM-DD) and game count, then one short row
  per game (第四局 · 机械狼通灵师) with the badge/↻/× controls; headers collapse on click, remembered
  per browser (werewolf.libgroup.<episode>). Each header also has an **×** (deleteEpisode) that
  removes every game of the episode after one confirmation listing them; games with a running job
  are kept and the dialog says so, and the button is disabled (updateGroupBusy) while any game of
  the episode is busy. removeVideo is the shared per-game delete used by both buttons. Rows keep data-id, and data-title holds the full title
  for the info bar. Titles without an SxxEyy code are listed ungrouped
- **Bookmarks and resume points** (main.js "Bookmarks and resume points", 2026-10-25): every game
  row has a star (faint outline, gold when bookmarked; clicking it never opens the game), episode
  headers show "★ n" (also when collapsed), a ☆/★ filter button in the library header shows only
  bookmarked games (remembered per browser, `werewolf.libfilter.starred`; empty filter shows a
  hint), and the info bar has the open game's star (keyboard B). Resume points are recorded only
  once the user engages -- plays, or seeks themselves -- (merely opening a game writes nothing):
  every 5s while playing, on pause/end, 800ms after a seek, when switching games, and on
  visibilitychange/pagehide via a keepalive fetch. A game with a point >= 30s that is not finished
  (finished = within 60s of the end or >= 97%) shows "▶ 25:13" and a thin progress line in its
  row, reopens there with "Resumed at … · Start over" in the info bar, and on load the app opens
  the most recently watched game in progress, else the first bookmarked game (marked to watch
  next), else the first game. Finished games show "✓ watched"
  and open from the start. State is server-side (`viewer_state.json` next to the video, written
  by POST /api/state) so it is shared by every device on the LAN; re-analysis does not touch it
  (it only rewrites metadata.json) and deleting a game removes it with the directory
- Info bar shows the open video's title (also set as the document title)
- **Visual polish pass (2026-10-15, reviewed with headless screenshots at 1600x1000 and 1366x768)**:
  the occasional editing actions (+ Night phase, + Mask, Reset masks/nights) live in an **✎ Edit
  popover** (`#edit-menu`, main.js) so the controls bar fits a laptop width (it used to cut off
  "Reset Nights" at 1366px); the phase indicator is a tinted status chip (gold day / indigo night,
  `.indicator.night`), not a button look-alike; both sidebars take the player column's height
  (`--stage-h` from a ResizeObserver in main.js) so the three columns end on one line and the
  lists scroll inside; library rows are a grid with the hidden-roles badge on its own line (the
  inline badge used to squeeze titles into four lines); the slide-out panels are centred in the
  area above the controls strip (`top: calc((100% - 56px) / 2)`) and capped so they never run
  under the controls; the night-jump tab is a labelled NIGHTS tab matching ROLES; the empty
  search column shows a hint
- Volume and user mute are remembered per browser (localStorage); the night auto-mute is never persisted
- Time display shows h:mm:ss above one hour
- Mute button (🔊/🔇) beside the volume slider. `userMuted` tracks a deliberate mute
  separately from the night auto-mute: dawn only unmutes if the user didn't mute, and
  unmuting during a night phase (masks on) takes effect at dawn rather than immediately
- Keyboard: Space=play, M=masks, F=fullscreen, arrows=±5s, N=next night start, Shift+N=previous,
  B=bookmark the open game

## Browser tests (tests/e2e)
- `processing/venv/bin/python3 tests/e2e/run.py [player|bookmarks] [--fresh]` (Playwright in
  processing/venv: `pip install -r tests/requirements.txt`). Each suite gets a **fresh copy of the
  synthetic demo library** and its own Vite server on a free port (127.0.0.1, `WEREWOLF_DEMO=1`,
  `WEREWOLF_VIDEOS_DIR`), so tests click, edit, bookmark, re-analyse and delete freely and never touch
  videos/. The demo games are rendered and analysed by the real pipeline once and cached in
  tests/.cache/ (gitignored; `--fresh` or deleting it re-analyses after pipeline changes; a renderer
  newer than the rendered games re-renders them)
- `player`: regression walk of the core viewer (library grouping, masks and modes, per-seat frames,
  role panel by role/seat with pack-wolf reveal, the 看牌 marker / panel row / jump / no masks or
  overlay during it, night overlay/auto-mute/jumps, mute, edit + reset persistence, fullscreen mask
  fit, the play icon and progress bar after a game switch, hidden-roles behaviour incl. no nights;
  57 checks). `bookmarks`: the /api/state contract
  (validation, 403/413, merge, 30 concurrent writers, corrupt file) and the UI (row/info-bar/B-key
  stars, header counts, filter + empty hint, resume save/restore/Start over, periodic and pause
  saves, switch and tab-close saves, watched games, another device, touch, survival of
  re-analysis, deletion and re-download). The bookmark suite runs a re-analysis and a re-download,
  so a full run takes several minutes
- **Run mutating UI tests here, not against the real server**: the earlier scratch walks used the
  real library and left `original_*` fields in metadata.json (which mark user corrections); the
  scratch scripts under /tmp were also purged by macOS after a few days, hence the move into the repo

## Demo mode (synthetic broadcasts, no real footage)
- `processing/demo/make_demo_video.py [OUT_DIR]` renders three made-up 12-player games with ffmpeg
  (H.264): player cards with invented names, role ribbons at the layout the analysis expects,
  red-tinted nights with the sidebar hidden, a wolves'-discussion close-up inside a night, and the
  天黑请闭眼 / 天亮请睁眼 banners. One game is a hidden-roles broadcast (未知 ribbons). Since 2026-10-26
  (user request: "a silhouette of a person in the middle, like what happen when people are talking
  in actual 大师赛") the middle is a broadcast's speaking shot, not a drawn table: the player with the
  floor at a desk with a seat name plate and a mic, drawn as a simple backlit person icon (`person_mask`:
  a round head floating over a rounded body, no neck, the same for everyone; a first, more detailed
  silhouette with hairstyles read as uncanny, user feedback), the next speaker every SPEECH = 6 s
  (same backdrop, so a change is a small frame difference, not a cut). Around each night (HOLD = 8 s
  either side) the camera stays on one player, who wears an eye mask under the red light, so the
  light changes on a still shot as the detector expects. The tour close-ups, the commentators and the
  wolves' close-up use the same icon. The tour puts its figures on LIGHT wall panels: the card
  detector measures the pans on 32x18 grey thumbnails, and a dark figure on the old dark panels made a
  pan step change the thumbnail by at most ~24.7 (< CARD_CUT 25): pans 5%, tour rejected; light panels
  give pans ~47%, moving ~46% (old design 37% / 42%). Check a renderer change with the e2e suites
  (`--fresh`), which assert the 看牌 tour. Game 1 (420 s) opens like a real broadcast: a still studio
  shot (0-50 s), the card-viewing tour of the 12 seats (50-90 s, 1.6 s holds + eased pans) and a cut
  to night 1 (90-160 s); night 2 is 280-330 s. Output: `processing/demo/library/<id>/video.mp4 +
  info.json` and `catalogue.json` (gitignored)
- `tests/e2e/readme_screenshots.py [NAME ...]` retakes the README screenshots (overview, night,
  mask-roles-mode, reveal-role, reveal-seat, hidden-roles, edit-menu, jobs) on throwaway demo
  servers at 1600x1000, device scale 2, saved 1400 wide; bookmarks.png (a library crop) is not
  covered
- Run the server with `WEREWOLF_DEMO=1` to make `/api/search` list the catalogue and downloads
  copy the rendered game in (`processing/demo/fake_download.py`, ~12s with progress); analysis
  then runs for real on the synthetic video. `WEREWOLF_VIDEOS_DIR=<dir>` points the server at
  another library so the demo never touches `videos/`. The README screenshots in
  `docs/screenshots/` were taken this way (a second server on `--port 5174`), so no tournament
  footage, titles or players appear in the repository

## API Endpoints (vite.config.js middleware)
- `GET /api/videos` - list videos with metadata.json (`hiddenRoles` flag for the library badge, plus the
  viewer state: `bookmarked`, `position`, `duration`, `watchedAt`; nulls when absent; a corrupt
  viewer_state.json reads as empty)
- `POST /api/state` - merge viewer state into `videos/<id>/viewer_state.json` (body: {videoId,
  bookmarked?: boolean, position?: seconds, duration?: seconds}; duration only with position; both
  0..48h; 400 on anything else or an empty update, 404 if the game has no video.mp4, 403
  cross-origin). The read-modify-write is synchronous (no interleaving) and written via tmp+rename.
  Returns the merged state
- `GET /api/downloaded` - list all video dirs with hasVideo/hasMetadata flags
- `POST /api/search` - search @JCDSS channel via yt-dlp (body: {query}); in demo mode, the rendered catalogue. Merges two
  sources, deduped by id, both filtered by all query keywords: (1) the 200 most recent
  uploads (cached 5 min) — covers broad queries, which YouTube's search tab caps at ~20;
  (2) the channel search tab `@JCDSS/search?query=…` — finds older episodes that have
  aged out of the recent window (the channel posts ~3 games/day, so 200 uploads ≈ 2 months;
  this is why S22E39/S22E41 returned "no results" in 2026-10 before source 2 was added)
- `POST /api/download` - queue a download+process job (body: {videoId}); 409 if that video already has a running job. Returns `{started, videoId, phase}`
- `POST /api/analyze` - queue a re-analysis of a downloaded video (body: {videoId}); 404 if no video.mp4, 409 if that video already has a running job
- `GET /api/job-status` - `{jobs: [...], active: n, limits: {downloads, analyses}}`; each job: `{videoId, kind: "download"|"analyze", phase: queued|downloading|waiting|processing|done, active, done, error, stopped, phaseElapsedMs, timings: {download, analysis} (ms), queuePosition}`. Finished jobs stay listed for 10 min
- `POST /api/stop` - stop one job (body: {videoId}); a stop while queued/downloading deletes the partial dir, a stop during analysis keeps the download
- `POST /api/delete` - delete video dir (body: {videoId}); 409 while a job runs for it
- `POST /api/metadata` - persist edited night_phases/name_masks to metadata.json (body: {videoId, version, night_phases, name_masks}); preserves originals in original_* fields. **Stale saves are refused (409, `stale: true`)**: metadata.json is served with `X-Metadata-Version` (first 16 hex of the content's SHA-1) and `Cache-Control: no-store`, the page sends that version back, and a save made against another version is refused; the page then reloads the current metadata and asks the user to redo the edit. Returns the new `version`. Added 2026-10-25 after a tab that had loaded S22E49 G1 before a production re-analysis saved a mask edit and wrote its stale nights back (the whole nights + masks copy is sent on every save). A missing version is still accepted (scripts, old pages)
- metadata.json also carries `role_map` (per-player role/number/name/y-band) from analysis, read by the role-reveal panel,
  and `card_phases` ([{start, end}], the 看牌 tours; two after a re-deal), which /api/metadata leaves alone
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
All 9 videos below plus the 8 S23 videos in the next section pass (benchmark.py GROUND_TRUTH, 2026-10-15: 17/17 OK with the banner-aware merge code, parallel == sequential). 2026-10-25, card-aware pipeline (one parallel run per game; scans cached in the session scratchpad and replayed with `analyze_phases(scan=...)`): GROUND_TRUTH 17/17, CARD_GROUND_TRUTH 28/28 games (31 tours), FIRST_NIGHT_GT 11/11 (S22 + two S23 hidden-roles games), and the night after every tour starts at its end 31/31. Threaded and sequential scans give identical arrays. 2026-10-26 (ratio merge needs a cut): GROUND_TRUTH 19/19 (d3jNiPSqMuI and zla5T_T4UKQ moved there from FIRST_NIGHT_GT with all their nights), FIRST_NIGHT_GT 9/9, CARD_GROUND_TRUTH 28/28; the change alters no other game's merges (checked over all clusters of the 31 cached scans). 2026-10-27 (split-screen card viewing, 45-min limit on tour candidates): CARD_GROUND_TRUTH 31/31 games (34 card viewings: the 31 tours + the three S23E28 split screens), GROUND_TRUTH 19/19, FIRST_NIGHT_GT 12/12 (with the three S23E28 first nights), the night after every card viewing starts at its end 34/34, and the 28 older games' cards and nights are identical to the 2026-10-26 run.

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

### First nights start where the card viewing (看牌) ends (2026-10-25)
Every first night above (and the night after a re-deal) now starts at the end of the 看牌 tour,
the cut from the last seat close-up to the table: S21 entries moved 2-7 s earlier than the red-on
they used to record (65R0r19JyYk 12:27, -ESYZWvQMH4 8:18, ZusP81Ycn-U 7:27, EC-1bimFjo4 7:26 and
15:44, ...). benchmark.py carries the updated values, CARD_GROUND_TRUTH (the 31 tours) and
FIRST_NIGHT_GT for the S22 games below.

### S22 first nights (2026-10-25, checked on frames)
- d3jNiPSqMuI (S22E47 第一局): 看牌 7:06-7:42, night 1 7:42-11:49 (was 7:13: red tablecloth in the tour).
  All nights (2026-10-26, in GROUND_TRUTH): 7:42-11:49, 25:44-28:26, 28:57-30:46, 38:12-39:49; the 30 s
  day between nights 2 and 3 is lit purple on the table shot and was merged until 2026-10-26; the game
  ends on day 5 (final board 1:01:40)
- iDD3JgXWA-0 (S22E47 第二局, hidden roles): 看牌 8:29-9:09, night 1 9:09-13:35 (commentators
  9:14-13:32, then the table still red until 13:34); was not detected at all
- 7SG4f3ZpZP0 (S22E47 第三局, hidden roles): 看牌 8:48-9:26, night 1 9:26-13:49 (commentators); was missing
- Im5713oy3b4 (S22E48 第一局, hidden roles): 看牌 8:00-8:36, night 1 8:36-12:34 (commentators); was missing
- 9Yij3uRUp1M (S22E48 第二局 孤注一掷): 看牌 7:50-8:44, night 1 8:44-13:17 with NO red light (masked
  players + the commentators' picture-in-picture, normal lighting; one red flash at 13:12); detected
  end 13:52 (first sidebar). Later nights 51:31-56:49, 1:00:35-1:03:15 are red-lit. Was missing,
  so masks stayed off until 56:49
- Dv0dRH80XGo (S22E48 第三局): 看牌 6:40-7:21, night 1 7:21-12:06 (was 6:43)
- zHCN-nyQ9jA (S22E49 第一局): 看牌 6:43-7:26, night 1 7:26-11:29 (was 0:16-11:29)
- 02bLRRi6RZk (S22E49 第二局): 看牌 5:49-6:30, night 1 6:30-10:53 (was 6:21)
- zla5T_T4UKQ (S22E49 第三局): 看牌 6:15-6:54, night 1 6:54-11:18. All nights (2026-10-26, in
  GROUND_TRUTH): 6:54-11:18, 20:15-24:13, 24:55-27:14, 27:38-30:15; the 23 s day between nights 3 and
  4 (players awake, purple light, no sidebar) was merged into one 24:52-30:16 night until 2026-10-26
  (user report); the game ends on day 5 (final board 45:50)
- Later nights of the other S22 games checked on frames 2026-10-26 (no hidden day inside): 9Yij3uRUp1M
  51:31-56:49 (long cutaways are masked players and the wolves' split screen) and 1:00:35-1:03:15,
  Dv0dRH80XGo, zHCN-nyQ9jA, 02bLRRi6RZk (its day 1 really runs 10:53-1:04:52, sidebar throughout) and
  S22E50 G2 bmXW-4CxR7g (18:58-22:45, 23:14-28:04: a 29 s day between, already split)

### S23 test set (2026-10, ground truth generated by frame inspection)
S23 broadcasts intercut nights with the wolves' masked close-ups and a night graphic, overlay a
transient (~6s) "天黑请闭眼" banner at night start, and hide the player sidebar for the whole night.
Boundaries below were read off the red-light transitions frame by frame and cross-checked against
the top "第X天" day counter and, since E26, the dawn / night-start banners. (The E24 counter jumping
from 第一天 to 第三天 is not an operator slip: day 2 was a 26s self-destruct day that the first GT
pass missed; the banners found it.)
Before the evidence-merge / bounded cut-merge changes these videos gave: E24G1 first night missed
entirely and second night split; E25G1/E25G2 one 13-50 minute "night" each.
- xNDz6SStaLo (S23E24 第一局): 9:17 -- 13:13, 1:00:38 -- 1:03:46, 1:04:12 -- 1:05:55  (role map 12/12
  verified; the 26s day between the last two is a self-destruct: 天亮请睁眼 at 1:03:48, 天黑请闭眼 at 1:04:14)
- QNxo5hmWLN0 (S23E24 第二局, hidden-roles): 7:03 -- 9:46, 17:20 -- 21:50, 1:28:33 -- 1:31:57, 1:32:21 -- 1:34:45
  (re-dealt: the first game was abandoned at its first dawn, commentators 9:46-16:39, second
  看牌 16:39-17:20; that second night 1 is covered by the commentators and was missing before 2026-10-25)
  (24s self-destruct day; the red light after the 1:34:48 dawn banner is daytime)
- bzsBWNpIwpo (S23E25 第一局): 11:10 -- 15:00, 1:04:06 -- 1:06:40, 1:12:19 -- 1:14:01  (role map 12/12)
- fgw-4eUV0JE (S23E25 第二局, 诡术之境 config): 6:21 -- 10:24, 1:17:52 -- 1:20:54  (role map 12/12)
- S23E26 (all four games, 2026-10-15; each pulled through the real front-end/CLI path):
  - X5J6PIMh368 (第一局 预女猎白混): 7:08 -- 11:33 only -- the game ends on day 1 (final board at 38:30)
  - 3oifxz_xLr4 (第二局 假面舞会): 7:15 -- 11:16, 49:56 -- 54:37, 55:05 -- 55:52 -- a real 28s
    self-destruct day between the last two (dawn banner 54:42, night banner 55:14)
  - 40RdPP2AuMs (第三局 机械狼通灵师): 7:53 -- 13:45, 26:21 -- 30:00, 30:31 -- 33:33 -- night 1 holds a
    152s wolves'-discussion gap (9:08-11:40, no red table at all); 34s self-destruct day at 30:00.
    Before the banner evidence / 240s cap this gave (7:53-9:09), (11:36-13:45), (26:21-33:33)
  - CBZfebaxD0E (第四局 机械狼通灵师): 8:08 -- 13:16, 58:51 -- 61:55, 69:48 -- 72:28 (day counter
    第一天/第二天/第三天 agrees); role map 12/12 after the vertical-label fix (the bare "机械狼" cut
    from the config line had added a phantom seat 7 and turned seat 3's 通灵师 into 平民)
- pZ0vo8VRDkA (S23E24 第三局) and HpIM5xTU-t8 (S23E25 第三局) are hidden-roles broadcasts that show
  almost no red table at night (commentators instead), so the red-light signal yields a partial or
  empty night list (0 phases on E25G3 before 2026-10-25). Their FIRST nights are now found from the
  card viewing (FIRST_NIGHT_GT): HpIM5xTU-t8 6:55-11:49; pZ0vo8VRDkA was re-dealt: first deal 8:04-9:00
  (abandoned at that dawn; the table stays red until 9:00), second deal 看牌 13:47-14:22, night 1
  14:22-18:13. Their LATER nights are still mostly missed: hidden-roles broadcasts cover every night
  with the commentators (2-5 min runs of the pre-tour set mid-game in S22E47 G2/G3, S22E48 G1), which
  could find them the same way -- not needed: since 2026-10-26 analyze.py writes no nights at all for
  a hidden-roles broadcast. A normal game whose later night had no red table shot at all would still
  be missed
