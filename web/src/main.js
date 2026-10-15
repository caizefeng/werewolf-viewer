import { WerewolfPlayer } from "./player.js";

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

    list.innerHTML = "";
    for (const v of videos) {
      const li = document.createElement("li");
      li.dataset.id = v.id;
      if (v.id === currentVideoId) li.classList.add("active");

      const titleSpan = document.createElement("span");
      titleSpan.className = "video-title";
      titleSpan.textContent = v.title;

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

      li.appendChild(titleSpan);
      if (v.hiddenRoles) {
        // The broadcast hides roles itself: masks/reveal are off for this one
        li.classList.add("hidden-roles");
        const badge = document.createElement("span");
        badge.className = "video-badge";
        badge.textContent = "hidden roles";
        badge.title = "Hidden-roles broadcast: the show keeps roles as \u672a\u77e5 and reveals them as the game goes; masks and role reveal are off";
        li.appendChild(badge);
      }
      li.appendChild(reBtn);
      li.appendChild(delBtn);
      li.addEventListener("click", () => switchVideo(v.id));
      list.appendChild(li);
    }

    // Rows whose video has a running job show it (spinner, disabled buttons)
    applyJobStates();

    // Auto-select first if none selected
    if (!currentVideoId && videos.length > 0) {
      switchVideo(videos[0].id);
    }
  } catch (err) {
    list.innerHTML = `<li style="color:#52525b">Failed to load: ${err.message}</li>`;
  }
}

async function switchVideo(videoId) {
  if (videoId === currentVideoId) return;
  currentVideoId = videoId;

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
  const title = document.querySelector(`#video-list li[data-id="${videoId}"] .video-title`)?.textContent || videoId;
  document.getElementById("video-title").textContent = title;
  document.title = `${title} – Werewolf Viewer`;

  // Load new metadata and video
  player.videoId = videoId;
  const loaded = await player.loadMetadata(`/${videoId}/metadata.json`);
  if (loaded) {
    player.loadVideo(`/${videoId}/video.mp4`);
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

async function deleteVideo(videoId) {
  if (!confirm(`Delete ${videoId}?`)) return;

  try {
    const res = await fetch("/api/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ videoId }),
    });
    const data = await res.json();
    if (data.error) {
      alert(`Delete failed: ${data.error}`);
      return;
    }
    if (data.deleted) {
      // If currently playing this video, clear player
      if (currentVideoId === videoId) {
        currentVideoId = null;
        const video = document.getElementById("video");
        video.pause();
        video.removeAttribute("src");
        video.load();
        player.clear();
        document.getElementById("video-title").textContent = "";
        document.title = "Werewolf Viewer";
      }
      jobSnapshot.delete(videoId);
      await refreshDownloadedState();
      loadVideoList();
      // The search result (if shown) becomes downloadable again
      updateButtonState(videoId, "idle");
    }
  } catch (err) {
    alert(`Delete failed: ${err.message}`);
  }
}

// ── Init ──

async function init() {
  player = new WerewolfPlayer(getElements());

  // Load video list and auto-select first
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

  // Pick up jobs already running (page reload); polling stops itself when idle
  ensureJobPolling();
}

init();
