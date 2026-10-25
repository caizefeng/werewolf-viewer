import { WerewolfPlayer } from "./player.js";

// Which server this page came from (scripts/start.sh sets VITE_INSTANCE): the
// dev instance labels itself so it is never mistaken for production
const IS_DEV = import.meta.env.VITE_INSTANCE === "dev";
const APP_NAME = IS_DEV ? "Werewolf Viewer (dev)" : "Werewolf Viewer";

let player;
let currentVideoId = null;

function getElements() {
  return {
    video: document.getElementById("video"),
    wrapper: document.getElementById("video-wrapper"),
    nightOverlay: document.getElementById("night-overlay"),
    nameMasks: document.getElementById("name-masks"),
    toggleMasks: document.getElementById("toggle-masks"),
    maskModeBtn: document.getElementById("mask-mode-btn"),
    phaseIndicator: document.getElementById("phase-indicator"),
    status: document.getElementById("status"),
    playBtn: document.getElementById("play-btn"),
    timeDisplay: document.getElementById("time-display"),
    volumeSlider: document.getElementById("volume-slider"),
    muteBtn: document.getElementById("mute-btn"),
    fullscreenBtn: document.getElementById("fullscreen-btn"),
    progressContainer: document.getElementById("progress-container"),
    progressBar: document.getElementById("progress-bar"),
    progressPlayed: document.getElementById("progress-played"),
    progressBuffered: document.getElementById("progress-buffered"),
    nightMarkers: document.getElementById("night-markers"),
    addPhaseBtn: document.getElementById("add-phase-btn"),
    addMaskBtn: document.getElementById("add-mask-btn"),
    resetMasksBtn: document.getElementById("reset-masks-btn"),
    resetNightsBtn: document.getElementById("reset-nights-btn"),
    nightJumpButtons: document.getElementById("night-jump-buttons"),
    rolePanel: document.getElementById("role-panel"),
  };
}

// ── Video list tab ──

// "京城大师赛 S23E26 第四局 机械狼通灵师 261015 狼人杀游戏" ->
// {episode: "S23E26", game: 4, gameLabel: "第四局", config: "机械狼通灵师", date: "261015"}
const CN_NUM = { "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10 };
function parseTitle(title) {
  const ep = title.match(/S(\d+)E(\d+)/);
  if (!ep) return null;
  const g = title.match(/第(.)局/);
  const date = title.match(/(?:^|\D)(\d{6})(?!\d)/);
  let config = "";
  if (g) {
    config = title.slice(g.index + g[0].length).replace(/\d{6}/, "").replace(/狼人杀游戏/, "").trim();
  }
  return {
    episode: `S${ep[1]}E${ep[2]}`,
    game: g ? (CN_NUM[g[1]] || parseInt(g[1], 10) || 0) : 0,
    gameLabel: g ? g[0] : "",
    config,
    date: date ? date[1] : "",
  };
}

// 261015 -> 2026-10-15 (the channel dates titles as YYMMDD)
function formatBroadcastDate(d) {
  if (!/^\d{6}$/.test(d)) return "";
  return `20${d.slice(0, 2)}-${d.slice(2, 4)}-${d.slice(4, 6)}`;
}

const GROUP_KEY = "werewolf.libgroup.";
function isGroupCollapsed(key) {
  try { return localStorage.getItem(GROUP_KEY + key) === "1"; } catch { return false; }
}
function toggleGroup(key) {
  const collapsed = !isGroupCollapsed(key);
  try { localStorage.setItem(GROUP_KEY + key, collapsed ? "1" : "0"); } catch {}
  const head = document.querySelector(`#video-list li.lib-group[data-group="${key}"]`);
  if (head) {
    head.classList.toggle("collapsed", collapsed);
    head.title = collapsed ? "Expand" : "Collapse";
  }
  document.querySelectorAll(`#video-list li.lib-item[data-group="${key}"]`).forEach((li) => li.classList.toggle("hidden", collapsed));
}

// ── Bookmarks and resume points ──
// Per-game viewer state lives on the server (videos/<id>/viewer_state.json,
// POST /api/state) so it follows the user across devices on the LAN.
// libState: videoId -> {bookmarked, position, duration, watchedAt}
const libState = new Map();
const RESUME_MIN = 30;                       // s; earlier positions count as "not started"
const FILTER_KEY = "werewolf.libfilter.starred";

function isFinished(s) {
  if (!s || !Number.isFinite(s.position) || !Number.isFinite(s.duration) || s.duration <= 0) return false;
  return s.position >= s.duration - 60 || s.position / s.duration >= 0.97;
}

// Where a game resumes, or null when it was never really started or was
// watched to the end (then it opens from the beginning again)
function resumePoint(s) {
  if (!s || !Number.isFinite(s.position) || s.position < RESUME_MIN || isFinished(s)) return null;
  return s.position;
}

function fmtTime(s) {
  s = Math.max(0, Math.floor(s || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return `${h ? h + ":" : ""}${mm}:${String(sec).padStart(2, "0")}`;
}

// Star, resume chip and progress line of one library row from libState
function renderRowState(li) {
  const s = libState.get(li.dataset.id) || {};
  const on = !!s.bookmarked;
  li.classList.toggle("starred", on);
  const star = li.querySelector(".video-star");
  if (star) {
    star.textContent = on ? "\u2605" : "\u2606";
    star.setAttribute("aria-pressed", String(on));
    star.title = on ? "Remove bookmark" : "Bookmark this game";
  }
  const at = resumePoint(s);
  const done = isFinished(s);
  let meta = li.querySelector(".video-meta");
  let chip = li.querySelector(".video-resume");
  if (at !== null || done) {
    if (!meta) {
      meta = document.createElement("span");
      meta.className = "video-meta";
      li.insertBefore(meta, li.querySelector(".video-re-btn"));
    }
    if (!chip) {
      chip = document.createElement("span");
      chip.className = "video-resume";
      meta.appendChild(chip);
    }
    chip.classList.toggle("done", done);
    chip.textContent = done ? "\u2713 watched" : `\u25B6 ${fmtTime(at)}`;
    chip.title = done ? "Watched to the end; opens from the start" : `Resumes at ${fmtTime(at)}`;
  } else if (chip) {
    chip.remove();
    if (meta && !meta.children.length) meta.remove();
  }
  let bar = li.querySelector(".video-progress");
  if (at !== null && Number.isFinite(s.duration) && s.duration > 0) {
    if (!bar) {
      bar = document.createElement("span");
      bar.className = "video-progress";
      bar.appendChild(document.createElement("span"));
      li.appendChild(bar);
    }
    bar.firstChild.style.width = `${Math.min(100, (at / s.duration) * 100).toFixed(1)}%`;
  } else if (bar) {
    bar.remove();
  }
}

// "★ n" on an episode header (kept visible when the group is collapsed)
function updateGroupStars(key) {
  if (!key) return;
  const head = document.querySelector(`#video-list li.lib-group[data-group="${key}"]`);
  if (!head) return;
  const n = document.querySelectorAll(`#video-list li.lib-item.starred[data-group="${key}"]`).length;
  head.classList.toggle("has-starred", n > 0);
  const el = head.querySelector(".lib-group-stars");
  if (el) {
    el.textContent = n ? `\u2605\u2009${n}` : "";
    el.title = n ? `${n} bookmarked` : "";
  }
}

// The "bookmarked only" filter shows a hint when nothing is bookmarked
function updateFilterEmpty() {
  const list = document.getElementById("video-list");
  list.classList.toggle("no-starred", !list.querySelector("li.lib-item.starred"));
}

function setLibraryFilter(on) {
  const list = document.getElementById("video-list");
  const btn = document.getElementById("lib-filter-btn");
  list.classList.toggle("only-starred", on);
  btn.classList.toggle("active", on);
  btn.setAttribute("aria-pressed", String(on));
  btn.textContent = on ? "\u2605" : "\u2606";
  btn.title = on ? "Showing bookmarked games only (click to show all)" : "Show bookmarked games only";
  try { localStorage.setItem(FILTER_KEY, on ? "1" : "0"); } catch {}
  updateFilterEmpty();
}

function renderBookmarkBtn() {
  const btn = document.getElementById("bookmark-btn");
  const on = !!(currentVideoId && libState.get(currentVideoId)?.bookmarked);
  btn.hidden = !currentVideoId;
  btn.textContent = on ? "\u2605" : "\u2606";
  btn.classList.toggle("on", on);
  btn.setAttribute("aria-pressed", String(on));
  btn.title = on ? "Remove bookmark (B)" : "Bookmark this game (B)";
}

// Merge a patch into a game's local state and refresh every place it shows
function setLocalState(videoId, patch) {
  libState.set(videoId, { ...(libState.get(videoId) || {}), ...patch });
  const li = document.querySelector(`#video-list li.lib-item[data-id="${videoId}"]`);
  if (li) {
    renderRowState(li);
    updateGroupStars(li.dataset.group);
  }
  updateFilterEmpty();
  if (videoId === currentVideoId) renderBookmarkBtn();
}

async function toggleBookmark(videoId) {
  const next = !libState.get(videoId)?.bookmarked;
  setLocalState(videoId, { bookmarked: next });          // optimistic
  try {
    const res = await fetch("/api/state", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ videoId, bookmarked: next }),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
    setLocalState(videoId, { bookmarked: data.bookmarked });
  } catch (err) {
    setLocalState(videoId, { bookmarked: !next });
    statusText(`Bookmark not saved: ${err.message}`);
  }
}

// Resume points: saved while the user actually watches (play, or a seek
// they made) -- merely opening a game writes nothing. Saves every 5s while
// playing, on pause/end, shortly after a seek, when switching games and when
// the page is hidden or closed (keepalive fetch survives the unload).
const watch = { videoId: null, engaged: false, resuming: false, lastSaveAt: 0, lastPos: null, seekTimer: null };

function savePosition() {
  const id = watch.videoId;
  if (!id || !watch.engaged || id !== currentVideoId) return;
  const video = document.getElementById("video");
  const position = video.currentTime;
  const duration = video.duration;
  if (!Number.isFinite(position) || !Number.isFinite(duration) || duration <= 0) return;
  if (watch.lastPos !== null && Math.abs(position - watch.lastPos) < 0.5) return;
  watch.lastPos = position;
  watch.lastSaveAt = Date.now();
  setLocalState(id, { position, duration, watchedAt: Date.now() });
  fetch("/api/state", {
    method: "POST",
    keepalive: true,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ videoId: id, position, duration }),
  }).catch(() => {});
}

function showResumeNote(at) {
  document.getElementById("resume-text").textContent = `Resumed at ${fmtTime(at)}`;
  document.getElementById("resume-note").hidden = false;
}

function hideResumeNote() {
  document.getElementById("resume-note").hidden = true;
}

function initWatchState() {
  const video = document.getElementById("video");
  video.addEventListener("play", () => {
    if (watch.videoId && watch.videoId === currentVideoId) watch.engaged = true;
  });
  video.addEventListener("timeupdate", () => {
    if (!video.paused && Date.now() - watch.lastSaveAt > 5000) savePosition();
  });
  video.addEventListener("pause", savePosition);
  video.addEventListener("ended", savePosition);
  video.addEventListener("seeked", () => {
    if (watch.resuming) {          // our own jump to the resume point
      watch.resuming = false;
      return;
    }
    if (!watch.videoId || watch.videoId !== currentVideoId) return;
    watch.engaged = true;
    hideResumeNote();
    clearTimeout(watch.seekTimer);
    watch.seekTimer = setTimeout(savePosition, 800);
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") savePosition();
  });
  window.addEventListener("pagehide", savePosition);

  document.getElementById("start-over-btn").addEventListener("click", () => {
    hideResumeNote();
    video.currentTime = 0;              // the seeked handler records it
  });
  document.getElementById("bookmark-btn").addEventListener("click", () => {
    if (currentVideoId) toggleBookmark(currentVideoId);
  });
  // B toggles the open game's bookmark (not while typing in a field)
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if ((e.key === "b" || e.key === "B") && currentVideoId) {
      e.preventDefault();
      toggleBookmark(currentVideoId);
    }
  });
  const filterBtn = document.getElementById("lib-filter-btn");
  let filterOn = false;
  try { filterOn = localStorage.getItem(FILTER_KEY) === "1"; } catch {}
  setLibraryFilter(filterOn);
  filterBtn.addEventListener("click", () => {
    setLibraryFilter(!document.getElementById("video-list").classList.contains("only-starred"));
  });
}

async function loadVideoList() {
  const list = document.getElementById("video-list");
  try {
    const res = await fetch("/api/videos");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const videos = await res.json();
    const cnNum = { '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10 };
    const sortKey = (t) => {
      const m = t.match(/第(.)局/);
      // Primary key: everything before 第X局 (episode prefix)
      const prefix = m ? t.slice(0, m.index).trimEnd() : t;
      return { prefix, game: m ? (cnNum[m[1]] || 0) : 0 };
    };
    videos.sort((a, b) => {
      const ka = sortKey(a.title), kb = sortKey(b.title);
      return ka.prefix.localeCompare(kb.prefix, "zh") || ka.game - kb.game;
    });
    libState.clear();
    for (const v of videos) {
      libState.set(v.id, { bookmarked: !!v.bookmarked, position: v.position, duration: v.duration, watchedAt: v.watchedAt });
    }

    // Group by episode: one header per SxxEyy (with its broadcast date and
    // game count), one short row per game. Titles repeat the episode four
    // times otherwise ("京城大师赛 S23E26 第一局 …" x4)
    list.innerHTML = "";
    const groups = new Map();
    for (const v of videos) {
      const info = parseTitle(v.title);
      const key = info ? info.episode : "";
      if (!groups.has(key)) groups.set(key, { key, date: info?.date || "", items: [] });
      const g = groups.get(key);
      if (!g.date && info?.date) g.date = info.date;
      g.items.push({ v, info });
    }
    for (const g of groups.values()) {
      if (g.key) {
        const head = document.createElement("li");
        head.className = "lib-group" + (isGroupCollapsed(g.key) ? " collapsed" : "");
        head.dataset.group = g.key;
        head.innerHTML = `<span class="lib-group-name"></span><span class="lib-group-date"></span><span class="lib-group-stars"></span><span class="lib-group-count"></span><button class="video-del-btn lib-group-del" title="Delete every game in this episode">×</button><span class="lib-group-chev">▾</span>`;
        head.querySelector(".lib-group-name").textContent = g.key;
        head.querySelector(".lib-group-date").textContent = formatBroadcastDate(g.date);
        head.querySelector(".lib-group-count").textContent = `${g.items.length} game${g.items.length === 1 ? "" : "s"}`;
        head.title = isGroupCollapsed(g.key) ? "Expand" : "Collapse";
        head.addEventListener("click", () => toggleGroup(g.key));
        head.querySelector(".lib-group-del").addEventListener("click", (e) => {
          e.stopPropagation();
          deleteEpisode(g.key, g.items);
        });
        list.appendChild(head);
      }
      for (const { v, info } of g.items) {
        const li = document.createElement("li");
        li.className = "lib-item";
        li.dataset.id = v.id;
        li.dataset.title = v.title;
        if (g.key) li.dataset.group = g.key;
        if (g.key && isGroupCollapsed(g.key)) li.classList.add("hidden");
        if (v.id === currentVideoId) li.classList.add("active");

        const titleSpan = document.createElement("span");
        titleSpan.className = "video-title";
        if (info && info.gameLabel) {
          const game = document.createElement("span");
          game.className = "lib-game";
          game.textContent = info.gameLabel;
          titleSpan.appendChild(game);
          if (info.config) {
            const cfg = document.createElement("span");
            cfg.className = "lib-config";
            cfg.textContent = info.config;
            titleSpan.appendChild(cfg);
          }
        } else {
          titleSpan.textContent = info ? v.title.replace(/^京城大师赛\s*/, "").replace(info.episode, "").trim() || v.title : v.title;
        }
        titleSpan.title = v.title;

        const delBtn = document.createElement("button");
        delBtn.className = "video-del-btn";
        delBtn.textContent = "×";
        delBtn.title = "Delete";
        delBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          deleteVideo(v.id);
        });

        const reBtn = document.createElement("button");
        reBtn.className = "video-del-btn video-re-btn";
        reBtn.textContent = "↻";
        reBtn.title = "Re-analyze (re-run night + name detection)";
        reBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          reanalyzeVideo(v.id);
        });

        const starBtn = document.createElement("button");
        starBtn.className = "video-star";
        starBtn.type = "button";
        starBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          toggleBookmark(v.id);
        });

        li.appendChild(starBtn);
        li.appendChild(titleSpan);
        if (v.hiddenRoles) {
          // The broadcast hides roles itself: masks/reveal are off for this one
          li.classList.add("hidden-roles");
          const meta = document.createElement("span");
          meta.className = "video-meta";
          const badge = document.createElement("span");
          badge.className = "video-badge";
          badge.textContent = "hidden roles";
          badge.title = "Hidden-roles broadcast: the show keeps roles as \u672a\u77e5 and reveals them as the game goes; masks and role reveal are off";
          meta.appendChild(badge);
          li.appendChild(meta);
        }
        li.appendChild(reBtn);
        li.appendChild(delBtn);
        li.addEventListener("click", () => switchVideo(v.id));
        list.appendChild(li);
        renderRowState(li);
      }
      updateGroupStars(g.key);
    }

    // Shown by CSS only while the "bookmarked only" filter is on and empty
    const empty = document.createElement("li");
    empty.className = "lib-empty";
    empty.textContent = "No bookmarks yet. Tap \u2606 on a game to keep it here.";
    list.appendChild(empty);
    updateFilterEmpty();

    // Rows whose video has a running job show it (spinner, disabled buttons)
    applyJobStates();

    // On load, open the game being watched most recently (it resumes where
    // it was left); with nothing in progress, the first bookmarked game (the
    // one marked to watch next); else the first game
    if (!currentVideoId && videos.length > 0) {
      const inProgress = videos
        .filter((v) => resumePoint(v) !== null)
        .sort((a, b) => (b.watchedAt || 0) - (a.watchedAt || 0));
      const firstStarred = videos.find((v) => v.bookmarked);
      switchVideo((inProgress[0] || firstStarred || videos[0]).id);
    } else if (currentVideoId) {
      renderBookmarkBtn();
    }
  } catch (err) {
    list.innerHTML = `<li style="color:#52525b">Failed to load: ${err.message}</li>`;
  }
}

async function switchVideo(videoId) {
  if (videoId === currentVideoId) return;
  savePosition();                       // the game being left keeps its place
  clearTimeout(watch.seekTimer);
  currentVideoId = videoId;
  Object.assign(watch, { videoId, engaged: false, resuming: false, lastSaveAt: 0, lastPos: null });
  hideResumeNote();
  renderBookmarkBtn();

  // Update active state in sidebar
  document.querySelectorAll("#video-list li").forEach((li) => {
    li.classList.toggle("active", li.dataset.id === videoId);
  });

  // Stop current video
  const video = document.getElementById("video");
  video.pause();
  video.removeAttribute("src");
  video.load();

  // Show which video is open
  const row = document.querySelector(`#video-list li[data-id="${videoId}"]`);
  const title = row?.dataset.title || row?.querySelector(".video-title")?.textContent || videoId;
  document.getElementById("video-title").textContent = title;
  document.title = `${title} – ${APP_NAME}`;

  // Load new metadata and video
  player.videoId = videoId;
  const loaded = await player.loadMetadata(`/${videoId}/metadata.json`);
  if (loaded) {
    const at = resumePoint(libState.get(videoId));
    player.loadVideo(`/${videoId}/video.mp4`);
    if (at !== null) {
      const video = document.getElementById("video");
      video.addEventListener("loadedmetadata", () => {
        if (currentVideoId !== videoId) return;
        watch.resuming = true;
        video.currentTime = at;
        showResumeNote(at);
      }, { once: true });
    }
  } else {
    document.getElementById("status").textContent =
      "Run analyze.py to generate metadata";
  }
}

// ── Download management tab ──

let downloadedSet = new Set(); // video IDs that have metadata

async function refreshDownloadedState() {
  try {
    const res = await fetch("/api/downloaded");
    const items = await res.json();
    downloadedSet.clear();
    for (const item of items) {
      if (item.hasMetadata) downloadedSet.add(item.id);
    }
  } catch {}
}

function formatDuration(sec) {
  if (!sec) return "";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

async function doSearch() {
  const input = document.getElementById("search-input");
  const query = input.value.trim();
  if (!query) return;

  const resultsList = document.getElementById("search-results");
  resultsList.innerHTML = `<li class="search-item"><div class="sr-title" style="color:#71717a">Searching...</div></li>`;

  try {
    const res = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    const results = await res.json();
    if (!Array.isArray(results)) throw new Error(results?.error || `HTTP ${res.status}`);
    await refreshDownloadedState();
    renderSearchResults(results);
  } catch (err) {
    resultsList.innerHTML = `<li class="search-item"><div class="sr-title" style="color:#ef4444">Search failed: ${err.message}</div></li>`;
  }
}

function renderSearchResults(results) {
  const list = document.getElementById("search-results");
  list.innerHTML = "";

  if (results.length === 0) {
    list.innerHTML = `<li class="search-item"><div class="sr-title" style="color:#71717a">No results</div></li>`;
    return;
  }

  for (const r of results) {
    const li = document.createElement("li");
    li.className = "search-item";
    li.dataset.videoId = r.id;

    const isReady = downloadedSet.has(r.id);

    li.innerHTML = `
      <div class="sr-title">${escapeHtml(r.title)}</div>
      <div class="sr-meta">${formatDuration(r.duration)}</div>
      <div class="sr-actions">
        <button class="sr-btn-dl ${isReady ? "done" : ""}" ${isReady ? "disabled" : ""}
          data-id="${r.id}" data-state="${isReady ? "done" : "idle"}">${isReady ? "✓ Done" : "Download"}</button>
      </div>
      <div class="sr-progress" data-progress-id="${r.id}">
        <div class="progress-step" data-step="download">
          <span class="step-label">↓</span>
          <div class="step-bar"><div class="step-fill"></div></div>
          <span class="step-time"></span>
        </div>
        <div class="progress-step" data-step="analysis">
          <span class="step-label">⚙</span>
          <div class="step-bar"><div class="step-fill"></div></div>
          <span class="step-time"></span>
        </div>
      </div>
    `;
    list.appendChild(li);
  }

  // Rows of videos with a running or recently finished job show that state
  applyJobStates();
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function formatElapsed(ms) {
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${(s % 60).toString().padStart(2, "0")}s`;
}

function getProgressEl(videoId) {
  return document.querySelector(`.sr-progress[data-progress-id="${videoId}"]`);
}

function showProgress(videoId) {
  const el = getProgressEl(videoId);
  if (!el) return;
  el.classList.add("visible");
  el.querySelectorAll(".step-fill").forEach((f) => (f.className = "step-fill"));
  el.querySelectorAll(".step-time").forEach((t) => (t.textContent = ""));
  clearErrorMessage(videoId);
}

function setStepState(videoId, stepName, state, timeText) {
  const el = getProgressEl(videoId);
  if (!el) return;
  const step = el.querySelector(`[data-step="${stepName}"]`);
  if (!step) return;
  step.querySelector(".step-fill").className = `step-fill ${state}`;
  if (timeText !== undefined) step.querySelector(".step-time").textContent = timeText;
}

function clearErrorMessage(videoId) {
  const existing = getProgressEl(videoId)?.querySelector(".sr-error-msg");
  if (existing) existing.remove();
}

function showErrorMessage(videoId, message, hint) {
  const el = getProgressEl(videoId);
  if (!el) return;
  clearErrorMessage(videoId);
  const msgEl = document.createElement("div");
  msgEl.className = "sr-error-msg";
  const errorText = document.createElement("div");
  errorText.className = "sr-error-text";
  errorText.textContent = message;
  msgEl.appendChild(errorText);
  if (hint) {
    const hintEl = document.createElement("div");
    hintEl.className = "sr-error-hint";
    hintEl.textContent = hint;
    msgEl.appendChild(hintEl);
  }
  el.appendChild(msgEl);
}

const DOWNLOAD_HINT = "YouTube may be limiting format access. Try again in a few minutes.";

// The search-row button: Download / Stop / Retry / ✓ Done. One delegated
// click handler (bound in init) reads data-state, so rows never rebind.
function updateButtonState(videoId, state) {
  const btn = document.querySelector(`.sr-btn-dl[data-id="${videoId}"]`);
  if (!btn || btn.dataset.state === state) return;
  btn.dataset.state = state;
  btn.className = "sr-btn-dl";
  btn.disabled = false;
  if (state === "running") {
    btn.classList.add("running");
    btn.textContent = "Stop";
  } else if (state === "done") {
    btn.classList.add("done");
    btn.textContent = "✓ Done";
    btn.disabled = true;
  } else if (state === "error") {
    btn.textContent = "Retry";
  } else {
    btn.textContent = "Download";
  }
}

async function startDownload(videoId) {
  let data;
  try {
    const res = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ videoId }),
    });
    data = await res.json();
  } catch (err) {
    data = { error: err.message };
  }
  if (data.error) {
    showProgress(videoId);
    setStepState(videoId, "download", "error", "");
    showErrorMessage(videoId, data.error);
    updateButtonState(videoId, "error");
    return;
  }
  // Optimistic row state until the first poll arrives
  updateButtonState(videoId, "running");
  showProgress(videoId);
  setStepState(videoId, "download", "active", data.phase === "queued" ? "queued" : "0s");
  ensureJobPolling();
}

async function stopJob(videoId) {
  try {
    await fetch("/api/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ videoId }),
    });
  } catch {}
  pollJobs();
}

// ── Jobs: several videos at once; the server queues beyond its slot limits ──

let jobPollTimer = null;
let jobTickTimer = null;
let jobsEverPolled = false;
const jobSnapshot = new Map(); // videoId -> last job view from /api/job-status

const PHASE_LABEL = {
  queued: "Queued for download",
  downloading: "Downloading",
  waiting: "Queued for analysis",
  processing: "Analyzing",
  done: "Done",
};

function phaseElapsed(job) {
  return job.phaseElapsedMs + (Date.now() - job.receivedAt);
}

function queuedText(job) {
  return job.queuePosition ? `queued #${job.queuePosition}` : "queued";
}

// Per-step bar state for a job: download (↓) and analysis (⚙)
function stepStates(job) {
  const dl = { state: "", time: "" };
  const an = { state: "", time: "" };
  if (job.kind === "download") {
    if (job.phase === "queued") { dl.state = "active"; dl.time = queuedText(job); }
    else if (job.phase === "downloading") { dl.state = "active"; dl.time = formatElapsed(phaseElapsed(job)); }
    else if (job.timings.download != null) { dl.state = "done"; dl.time = formatElapsed(job.timings.download); }
  } else {
    dl.state = "done";
  }
  if (job.phase === "waiting") { an.state = "active"; an.time = queuedText(job); }
  else if (job.phase === "processing") { an.state = "active"; an.time = formatElapsed(phaseElapsed(job)); }
  else if (job.timings.analysis != null) { an.state = "done"; an.time = formatElapsed(job.timings.analysis); }
  if (job.done && job.stopped) {
    dl.state = ""; dl.time = ""; an.state = ""; an.time = "";
  } else if (job.done && job.error) {
    const failed = job.kind === "download" && job.timings.download == null ? dl : an;
    failed.state = "error";
    failed.time = "";
  }
  return { dl, an };
}

function statusText(text) {
  document.getElementById("status").textContent = text;
}

// Reflect one job in every place it shows: the search row (progress bars +
// button), the library row (spinner, disabled buttons) and the status line
// when it is a re-analysis of the open video
function renderJobRow(job) {
  const vid = job.videoId;
  const el = getProgressEl(vid);
  if (el) {
    el.classList.add("visible");
    const { dl, an } = stepStates(job);
    setStepState(vid, "download", dl.state, dl.time);
    setStepState(vid, "analysis", an.state, an.time);
    if (job.done && job.error && !job.stopped) {
      const failedDownload = job.kind === "download" && job.timings.download == null;
      showErrorMessage(vid, job.error, failedDownload ? DOWNLOAD_HINT : "See .run/server.log for the full output.");
    } else {
      clearErrorMessage(vid);
    }
  }
  updateButtonState(vid, job.done ? (job.stopped ? "idle" : (job.error ? "error" : "done")) : "running");

  const li = document.querySelector(`#video-list li[data-id="${vid}"]`);
  if (li) {
    const busy = !job.done;
    li.classList.toggle("busy", busy);
    const re = li.querySelector(".video-re-btn");
    const del = li.querySelector(".video-del-btn:not(.video-re-btn)");
    if (re) {
      re.classList.toggle("spinning", busy);
      re.disabled = busy;
      re.title = busy ? `${PHASE_LABEL[job.phase] || job.phase}…` : "Re-analyze (re-run night + name detection)";
    }
    if (del) {
      del.disabled = busy;
      del.title = busy ? "Busy: stop the job first" : "Delete";
    }
    if (li.dataset.group) updateGroupBusy(li.dataset.group);
  }

  if (job.kind === "analyze" && vid === currentVideoId) {
    if (job.phase === "waiting") statusText(`Re-analysis ${queuedText(job)}…`);
    else if (job.phase === "processing") statusText(`Re-analyzing (night + name detection)… ${formatElapsed(phaseElapsed(job))}`);
    else if (job.done && job.stopped) statusText("Re-analysis stopped");
    else if (job.done && job.error) statusText(`Re-analysis failed: ${job.error}`);
    else if (job.done) statusText(`Re-analysis complete (${formatElapsed(job.timings.analysis || 0)})`);
  }
}

function applyJobStates() {
  for (const job of jobSnapshot.values()) renderJobRow(job);
}

async function pollJobs() {
  let data;
  try {
    const res = await fetch("/api/job-status");
    data = await res.json();
  } catch {
    return;
  }
  if (!Array.isArray(data.jobs)) return;
  const now = Date.now();
  const seen = new Set();
  const finished = [];
  for (const job of data.jobs) {
    job.receivedAt = now;
    seen.add(job.videoId);
    const prev = jobSnapshot.get(job.videoId);
    jobSnapshot.set(job.videoId, job);
    renderJobRow(job);
    // A job that ended since the last poll (jobs already over when the page
    // loaded are not "news")
    if (job.done && jobsEverPolled && (!prev || !prev.done)) finished.push(job);
  }
  for (const id of [...jobSnapshot.keys()]) {
    if (!seen.has(id)) jobSnapshot.delete(id); // the server has forgotten it
  }
  jobsEverPolled = true;
  for (const job of finished) await onJobFinished(job);
  if (!data.jobs.some((j) => j.active)) stopJobPolling();
}

async function onJobFinished(job) {
  await refreshDownloadedState();
  await loadVideoList(); // re-renders the library (and re-applies job states)
  // Pick up regenerated night phases / masks if that video is open
  if (job.kind === "analyze" && job.videoId === currentVideoId && !job.error && !job.stopped) {
    player.loadMetadata(`/${job.videoId}/metadata.json`);
  }
}

function tickJobTimes() {
  for (const job of jobSnapshot.values()) {
    if (job.phase !== "downloading" && job.phase !== "processing") continue;
    const t = formatElapsed(phaseElapsed(job));
    const el = getProgressEl(job.videoId);
    if (el) {
      const step = el.querySelector(`[data-step="${job.phase === "downloading" ? "download" : "analysis"}"] .step-time`);
      if (step) step.textContent = t;
    }
    if (job.kind === "analyze" && job.phase === "processing" && job.videoId === currentVideoId) {
      statusText(`Re-analyzing (night + name detection)… ${t}`);
    }
  }
}

function ensureJobPolling() {
  if (jobPollTimer) return;
  jobPollTimer = setInterval(pollJobs, 2000);
  jobTickTimer = setInterval(tickJobTimes, 500);
  pollJobs();
}

function stopJobPolling() {
  clearInterval(jobPollTimer);
  clearInterval(jobTickTimer);
  jobPollTimer = null;
  jobTickTimer = null;
}

async function reanalyzeVideo(videoId) {
  if (!confirm("Re-run night and name detection for this video?\nManual edits to its masks and night phases will be replaced.")) return;
  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ videoId }),
    });
    const data = await res.json();
    if (data.error) {
      alert(`Re-analyze failed: ${data.error}`);
      return;
    }
    if (videoId === currentVideoId) {
      statusText(data.phase === "processing" ? "Re-analyzing (night + name detection)…" : "Re-analysis queued…");
    }
    ensureJobPolling();
  } catch (err) {
    alert(`Re-analyze failed: ${err.message}`);
  }
}

// Delete one game on the server and drop it from the page state. Returns
// null on success or an error message; callers refresh the library.
async function removeVideo(videoId) {
  let data;
  try {
    const res = await fetch("/api/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ videoId }),
    });
    data = await res.json();
  } catch (err) {
    return err.message;
  }
  if (data.error) return data.error;
  if (!data.deleted) return "not deleted";
  // If currently playing this video, clear player
  if (currentVideoId === videoId) {
    currentVideoId = null;
    const video = document.getElementById("video");
    video.pause();
    video.removeAttribute("src");
    video.load();
    player.clear();
    document.getElementById("video-title").textContent = "";
    document.title = APP_NAME;
  }
  jobSnapshot.delete(videoId);
  libState.delete(videoId);
  if (watch.videoId === videoId) {
    watch.videoId = null;
    hideResumeNote();
  }
  renderBookmarkBtn();
  // The search result (if shown) becomes downloadable again
  updateButtonState(videoId, "idle");
  return null;
}

async function deleteVideo(videoId) {
  const title = document.querySelector(`#video-list li[data-id="${videoId}"]`)?.dataset.title || videoId;
  if (!confirm(`Delete ${title}?`)) return;
  const err = await removeVideo(videoId);
  if (err) {
    alert(`Delete failed: ${err}`);
    return;
  }
  await refreshDownloadedState();
  loadVideoList();
}

// The × on an episode header: every game of the episode after one
// confirmation. Games with a running job are kept (the server would refuse
// them anyway) and said so up front.
async function deleteEpisode(key, items) {
  const isBusy = ({ v }) => { const j = jobSnapshot.get(v.id); return !!j && !j.done; };
  const kept = items.filter(isBusy);
  const targets = items.filter((it) => !isBusy(it));
  if (!targets.length) {
    alert(`Every game in ${key} is being downloaded or analyzed. Stop those jobs first.`);
    return;
  }
  const label = ({ v, info }) => (info?.gameLabel ? `${info.gameLabel} ${info.config}`.trim() : v.title);
  const lines = targets.map((it) => `• ${label(it)}`).join("\n");
  const note = kept.length ? `\n\n${kept.length} game${kept.length === 1 ? "" : "s"} with a running job will be kept.` : "";
  if (!confirm(`Delete ${targets.length} game${targets.length === 1 ? "" : "s"} of ${key}?\n\n${lines}${note}`)) return;
  const failed = [];
  for (const it of targets) {
    const err = await removeVideo(it.v.id);
    if (err) failed.push(`${label(it)}: ${err}`);
  }
  await refreshDownloadedState();
  loadVideoList();
  if (failed.length) alert(`Could not delete:\n${failed.join("\n")}`);
}

// Episode header × is disabled while any game of the episode has a job
function updateGroupBusy(key) {
  const head = document.querySelector(`#video-list li.lib-group[data-group="${key}"]`);
  if (!head) return;
  const busy = !!document.querySelector(`#video-list li.lib-item[data-group="${key}"].busy`);
  const del = head.querySelector(".lib-group-del");
  if (!del) return;
  del.disabled = busy;
  del.title = busy ? "Busy: a game in this episode is being downloaded or analyzed" : "Delete every game in this episode";
}

// ── Init ──

async function init() {
  if (IS_DEV) {
    document.title = APP_NAME;
    document.body.classList.add("instance-dev");
    const badge = document.createElement("span");
    badge.className = "instance-badge";
    badge.textContent = "dev";
    badge.title = "Development instance: its own library (videos-dev/), code from the working tree";
    document.querySelector("header h1").append(badge);
  }
  player = new WerewolfPlayer(getElements());
  initWatchState();

  // Load the library and open the game in progress (or the first)
  await loadVideoList();

  // Refresh button
  document.getElementById("refresh-list").addEventListener("click", loadVideoList);

  // Search button + Enter key
  document.getElementById("search-btn").addEventListener("click", doSearch);
  document.getElementById("search-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") doSearch();
  });

  // Search-row buttons: Download/Retry start a job, Stop ends one
  document.getElementById("search-results").addEventListener("click", (e) => {
    const btn = e.target.closest(".sr-btn-dl");
    if (!btn || btn.disabled) return;
    if (btn.dataset.state === "running") stopJob(btn.dataset.id);
    else startDownload(btn.dataset.id);
  });

  // Edit popover in the controls bar (night phases / masks)
  const editBtn = document.getElementById("edit-menu-btn");
  const editMenu = document.getElementById("edit-menu");
  const setEditMenu = (open) => {
    editMenu.classList.toggle("hidden", !open);
    editBtn.classList.toggle("active", open);
    editBtn.setAttribute("aria-expanded", String(open));
  };
  editBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    setEditMenu(editMenu.classList.contains("hidden"));
  });
  editMenu.addEventListener("click", (e) => {
    e.stopPropagation();
    if (e.target.closest(".menu-btn")) setEditMenu(false);
  });
  document.addEventListener("click", () => setEditMenu(false));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") setEditMenu(false); });

  // Both sidebars take the player column's height so the three columns share
  // one bottom edge (the lists scroll inside)
  const stage = document.getElementById("player-container");
  const setStageHeight = () => {
    document.documentElement.style.setProperty("--stage-h", `${Math.round(stage.getBoundingClientRect().height)}px`);
  };
  new ResizeObserver(setStageHeight).observe(stage);
  setStageHeight();

  // Pick up jobs already running (page reload); polling stops itself when idle
  ensureJobPolling();
}

init();
