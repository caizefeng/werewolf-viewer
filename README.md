# Werewolf Viewer

A spoiler-free player for recorded 12-player werewolf (狼人杀) tournament broadcasts. It finds the night phases and the on-screen role labels by itself, blacks out the nights, covers the roles, and lets you reveal exactly as much as the player you want to watch as would know.

![The player with role masks on both sides, per-seat wire frames and the role panel](docs/screenshots/overview.png)

> Every screenshot in this README comes from the built-in **demo mode**, which renders made-up games with invented players. No tournament footage is included.

## Why

Tournament broadcasts show each player's role in a sidebar the whole time, and the night segments show who the wolves pick. Watching a recording as if you were at the table means hiding both, and then peeking at the one role you chose to play. That is what this viewer does, automatically, for a whole library of games.

## Features

### Nights go dark on their own

The analysis samples the video every two seconds and reads the red ambient light the studio uses at night. The nights it finds become a black overlay with muted audio, red markers on the progress bar, and a **NIGHTS** panel on the left edge that jumps to the start or end of any night. `N` and `Shift+N` skip between nights.

![Night overlay with the NIGHTS jump panel open and red night markers on the progress bar](docs/screenshots/night.png)

### Roles are covered, seat by seat

OCR locates the vertical role labels in the sidebar. Each side gets an opaque mask that covers the role column and the director's running notes next to it, drawn with one thin gold **wire frame per seat** so you can still see the table layout. The masks appear once the first night ends (nothing to hide before that) and stay off during nights.

Two coverages are available from the controls bar:

| `Mask: Full` (default) | `Mask: Roles` |
|---|---|
| Extends to the frame edge, hiding avatars and player names as well | Covers only the role column and the notes next to it |

![The player with Roles coverage, where only the role column is covered](docs/screenshots/mask-roles-mode.png)

### Reveal exactly what one player would know

Hover the **ROLES** tab on the right edge. Everything starts blind.

- **By role** lists the roles in play with no seats shown. Clones are numbered (平民 1 … 4) in a random order fixed per game, so picking "平民 2" tells you nothing until you reveal it. Once revealed, the row says which seat that was.
- **By seat** lists seats 1 to 12. Click one to open its mask.
- **Wolves reveal as a team.** Picking any wolf opens every wolf's row at once, the way a wolf knows the pack from the first night. The team is read from the ribbon colour the broadcast paints behind each label, so wolf-side roles whose names do not say wolf (假面, 盗宝大师, 九尾, a 机械狼 labelled with the role it copied) are included.
- `Blind` and `All` reset either way. Your choices persist per game in the browser.

![By role mode with the wolf team revealed: three rows open on the masks](docs/screenshots/reveal-role.png)

![By seat mode with two seats revealed](docs/screenshots/reveal-seat.png)

Each opening is cut strictly to that player's own label, with a guard so a neighbour's coloured ribbon tip never shows.

### Hidden-roles broadcasts are recognised

Some games are broadcast with roles shown as 未知 until the show reveals them. The analysis detects this from the sidebar, flags the game in the library, starts it with masks off, and explains in the role panel why there is nothing to reveal.

![A hidden-roles game: badge in the library, masks off, explanation in the role panel](docs/screenshots/hidden-roles.png)

### A library that fills itself

Search the channel from the right-hand panel and press **Download**. Each row has its own Download/Stop button and progress bars, several jobs run at once, and the rest queue behind the slot limits (3 downloads, 2 analyses by default). The library groups games by episode; each row has **↻** to re-run the analysis and **×** to delete.

![Three jobs: two analysing, one queued behind the analysis slots](docs/screenshots/jobs.png)

### Everything is editable

Dragging a night boundary, resizing a mask from its inner edge, or using **✎ Edit** (add a night phase at the current time, add a mask, reset either) saves to the game's metadata immediately. The detected values are kept, so **Reset** always returns to them.

![The Edit popover in the controls bar](docs/screenshots/edit-menu.png)

### Keyboard

| Key | Action |
|---|---|
| `Space` | Play / pause |
| `←` `→` | Seek 5 s |
| `M` | Toggle masks |
| `N` / `Shift+N` | Next / previous night |
| `F` | Fullscreen (masks follow the letterboxed video) |

## How it works

**Night detection** (`processing/analyze_night.py`). Three threads scan the bottom corners of a frame every 2 s and compute the red-to-green ratio; red studio light reads 2.5 and above, daylight about 1.1. Red clusters are merged into nights by three rules: both gap boundaries are camera cuts; the gap stays red-tinted (close-ups during a night); or, for newer broadcasts that cut away for minutes at a time, no day evidence lies in the gap. Day evidence is the player sidebar being on screen, or the broadcast's own 天黑请闭眼 / 天亮请睁眼 banners, found by OCR only inside candidate gaps. Boundaries are then refined at 0.25 s. The detector is validated against 17 hand-verified games (0 false positives, 0 misses).

**Role map** (`processing/analyze_names.py`). PaddleOCR (PP-OCRv6 medium) reads the left and right 30% of a few frames and keeps the vertical boxes in the role column: known role names, misreads snapped to the nearest name, annotated labels such as 机械通灵 mapped to 机械狼, and labels the list does not know yet kept as read when every frame agrees on them. Rows are clustered, seat numbers come from the number badges and the fixed row pitch, and every seat gets a reveal band from a 6-row layout fitted to the rows that were read, so seat reveal works even where a label was not recognised. The ribbon colour behind each label gives the faction. Only seat numbers identify players; names are never extracted.

**Jobs** (`web/vite.config.js`). The dev server's middleware runs one job per game in a FIFO queue with separate download and analysis slots, and reports every job's phase, elapsed time and queue position. Downloads use yt-dlp; analysis runs night and role detection in parallel processes.

## Setup

Requirements: Python 3.11+, Node.js 20+ with corepack, ffmpeg (for yt-dlp merges and the demo renderer), and a JavaScript runtime for yt-dlp's challenge solver (`brew install deno`).

```bash
git clone https://github.com/caizefeng/werewolf-viewer.git
cd werewolf-viewer

python3 -m venv processing/venv
source processing/venv/bin/activate
pip install -r processing/requirements.txt      # yt-dlp, PaddleOCR, OpenCV

corepack enable
cd web && pnpm install && cd ..

scripts/start.sh        # http://localhost:5173/ (LAN-reachable); scripts/stop.sh to stop
```

OCR models (about 165 MB) download into `processing/models/` on first use.

The command line does the same work as the UI:

```bash
python3 processing/download.py --video-id="VIDEO_ID"     # quote IDs that start with a dash
python3 processing/analyze.py --video-id="VIDEO_ID"      # writes videos/VIDEO_ID/metadata.json
python3 processing/update_role_maps.py [VIDEO_ID ...]    # re-scan roles only, keeps manual edits
```

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `WEREWOLF_MAX_DOWNLOADS` | 3 | Concurrent downloads |
| `WEREWOLF_MAX_ANALYSES` | 2 | Concurrent analyses (each uses 4 to 5 cores) |
| `WEREWOLF_VIDEOS_DIR` | `videos/` | Where games are stored |
| `WEREWOLF_DEMO` | unset | Serve the rendered demo games instead of YouTube |

The YouTube channel searched by default is set by `CHANNEL_URL` in `web/vite.config.js`.

### Demo mode

To try the viewer without downloading anything, render the synthetic games and run a server against a scratch library:

```bash
source processing/venv/bin/activate
python3 processing/demo/make_demo_video.py          # three games into processing/demo/library/
cd web && WEREWOLF_DEMO=1 WEREWOLF_VIDEOS_DIR=/tmp/demo-library pnpm exec vite --port 5174
```

Search for `demo cup`, download the three games, and the real pipeline analyses them. This is how the screenshots above were made.

## Project structure

```
werewolf-viewer/
├── processing/
│   ├── analyze.py              # pipeline: night + role detection in parallel, writes metadata.json
│   ├── analyze_night.py        # night phases (corner redness, cut/ratio/evidence merging, refinement)
│   ├── analyze_names.py        # role map and masks (PaddleOCR), banner and sidebar checks
│   ├── update_role_maps.py     # re-scan roles only, preserving manual edits
│   ├── download.py             # yt-dlp download with client fallbacks
│   ├── demo/                   # synthetic game renderer + demo download stand-in
│   └── benchmarks/             # ground-truth validation
├── web/
│   ├── vite.config.js          # dev server: API, job queue, file serving
│   └── src/                    # main.js (library, search, jobs), player.js (player, masks, reveal), style.css
├── scripts/start.sh, stop.sh   # background server
├── docs/screenshots/           # README images (demo games)
└── videos/                     # downloaded games + metadata (gitignored)
```

## API

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/videos` | Analysed games (with `hiddenRoles`) |
| GET | `/api/downloaded` | Every game directory with `hasVideo` / `hasMetadata` |
| POST | `/api/search` | Search the channel, body `{query}` |
| POST | `/api/download` | Queue download + analysis, body `{videoId}` |
| POST | `/api/analyze` | Queue a re-analysis of a downloaded game, body `{videoId}` |
| GET | `/api/job-status` | Every job: phase, elapsed time, timings, queue position |
| POST | `/api/stop` | Stop one job, body `{videoId}` |
| POST | `/api/delete` | Delete a game, body `{videoId}` (refused while its job runs) |
| POST | `/api/metadata` | Save edited night phases and masks, body `{videoId, night_phases, name_masks}` |

## Tuning

Night detection constants live at the top of `processing/analyze_night.py`:

| Constant | Default | Meaning |
|---|---|---|
| `RED_THRESH` | 2.5 | Corner R/G ratio that counts as red light |
| `CUT_THRESH` | 40 | Frame difference that counts as a camera cut |
| `MAX_MERGE_GAP` | 100 s | Longest gap bridged on red-tint evidence |
| `MAX_CUT_MERGE_GAP` | 180 s | Longest gap bridged when both boundaries are cuts |
| `MAX_EVIDENCE_GAP` | 240 s | Longest gap bridged on day-evidence grounds (120 s without banners) |
| `MIN_PHASE_DURATION` | 35 s | Shorter red stretches are ignored |
| `ENTRY_BUFFER` / `EXIT_BUFFER` | 2 s / 1 s | Overlay lead before red-on and lag after red-off |

Reveal band geometry is `BAND_PAD` and `BAND_GUARD` in `web/src/player.js`.

## License

[MIT](LICENSE)
