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
    phaseIndicator: document.getElementById("phase-indicator"),
    status: document.getElementById("status"),
    playBtn: document.getElementById("play-btn"),
    timeDisplay: document.getElementById("time-display"),
    volumeSlider: document.getElementById("volume-slider"),
    fullscreenBtn: document.getElementById("fullscreen-btn"),
    progressContainer: document.getElementById("progress-container"),
    progressBar: document.getElementById("progress-bar"),
    progressPlayed: document.getElementById("progress-played"),
    progressBuffered: document.getElementById("progress-buffered"),
    nightMarkers: document.getElementById("night-markers"),
    addPhaseBtn: document.getElementById("add-phase-btn"),
    resetMasksBtn: document.getElementById("reset-masks-btn"),
    resetNightsBtn: document.getElementById("reset-nights-btn"),
    nightJumpButtons: document.getElementById("night-jump-buttons"),
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

      li.appendChild(titleSpan);
      li.appendChild(delBtn);
      li.addEventListener("click", () => switchVideo(v.id));
      list.appendChild(li);
    }

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

  // Load new metadata and video
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
let jobPollTimer = null;
let phaseStartTime = null; // client-side timer for active phase

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
          data-id="${r.id}">${isReady ? "✓ Done" : "Download"}</button>
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

  // Bind download buttons
  list.querySelectorAll(".sr-btn-dl:not(.done)").forEach((btn) => {
    btn.addEventListener("click", () => startDownload(btn.dataset.id));
  });
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
}

function setStepState(videoId, stepName, state, timeText) {
  const el = getProgressEl(videoId);
  if (!el) return;
  const step = el.querySelector(`[data-step="${stepName}"]`);
  if (!step) return;
  step.querySelector(".step-fill").className = `step-fill ${state}`;
  if (timeText !== undefined) step.querySelector(".step-time").textContent = timeText;
}

async function startDownload(videoId) {
  try {
    const res = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ videoId }),
    });
    const data = await res.json();
    if (data.error) {
      showProgress(videoId);
      setStepState(videoId, "download", "error", "");
      return;
    }
  } catch {
    showProgress(videoId);
    setStepState(videoId, "download", "error", "");
    return;
  }

  // Update button to running state
  updateButtonState(videoId, "running");

  // Show progress bars, start download timer
  showProgress(videoId);
  setStepState(videoId, "download", "active", "0s");
  phaseStartTime = Date.now();

  // Start polling job status
  startJobPolling(videoId);
}

function updateButtonState(videoId, state) {
  const btn = document.querySelector(`.sr-btn-dl[data-id="${videoId}"]`);
  if (!btn) return;

  btn.className = "sr-btn-dl";
  if (state === "running") {
    btn.classList.add("running");
    btn.textContent = "Stop";
    btn.disabled = false;
    // Rebind to stop
    btn.replaceWith(btn.cloneNode(true));
    const newBtn = document.querySelector(`.sr-btn-dl[data-id="${videoId}"]`);
    newBtn.addEventListener("click", () => stopJob());
  } else if (state === "done") {
    btn.classList.add("done");
    btn.textContent = "✓ Done";
    btn.disabled = true;
  } else if (state === "error") {
    btn.textContent = "Retry";
    btn.disabled = false;
    btn.replaceWith(btn.cloneNode(true));
    const newBtn = document.querySelector(`.sr-btn-dl[data-id="${videoId}"]`);
    newBtn.addEventListener("click", () => startDownload(videoId));
  }
}

let lastPhase = null;
let elapsedTickTimer = null;
let activeJobVideoId = null;
let activeStepName = null;

function startElapsedTicker() {
  if (elapsedTickTimer) clearInterval(elapsedTickTimer);
  elapsedTickTimer = setInterval(() => {
    if (phaseStartTime && activeJobVideoId && activeStepName) {
      const el = getProgressEl(activeJobVideoId);
      if (!el) return;
      const step = el.querySelector(`[data-step="${activeStepName}"]`);
      if (step) step.querySelector(".step-time").textContent = formatElapsed(Date.now() - phaseStartTime);
    }
  }, 500);
}

function stopElapsedTicker() {
  if (elapsedTickTimer) {
    clearInterval(elapsedTickTimer);
    elapsedTickTimer = null;
  }
}

function startJobPolling(videoId) {
  if (jobPollTimer) clearInterval(jobPollTimer);
  lastPhase = "downloading";
  activeJobVideoId = videoId;
  activeStepName = "download";

  startElapsedTicker();

  jobPollTimer = setInterval(async () => {
    try {
      const res = await fetch("/api/job-status");
      const status = await res.json();
      const vid = status.videoId;

      if (!status.active && status.done) {
        clearInterval(jobPollTimer);
        jobPollTimer = null;
        stopElapsedTicker();

        if (status.error) {
          const step = lastPhase === "downloading" ? "download" : "analysis";
          setStepState(vid, step, "error", "");
          updateButtonState(vid, "error");
        } else {
          const elapsed = formatElapsed(Date.now() - phaseStartTime);
          setStepState(vid, "analysis", "done", elapsed);
          updateButtonState(vid, "done");
          loadVideoList();
        }
        phaseStartTime = null;
        lastPhase = null;
        activeJobVideoId = null;
        activeStepName = null;
        return;
      }

      if (status.active) {
        if (status.phase === "processing" && lastPhase === "downloading") {
          const dlElapsed = formatElapsed(Date.now() - phaseStartTime);
          setStepState(vid, "download", "done", dlElapsed);
          phaseStartTime = Date.now();
          setStepState(vid, "analysis", "active", "0s");
          lastPhase = "processing";
          activeStepName = "analysis";
        }
      }
    } catch {}
  }, 2000);
}

async function stopJob() {
  try {
    await fetch("/api/stop", { method: "POST" });
  } catch {}
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
    if (data.deleted) {
      // If currently playing this video, clear player
      if (currentVideoId === videoId) {
        currentVideoId = null;
        const video = document.getElementById("video");
        video.pause();
        video.removeAttribute("src");
        video.load();
      }
      await refreshDownloadedState();
      loadVideoList();
      // Update search result download button
      const dlBtn = document.querySelector(`.sr-btn-dl[data-id="${videoId}"]`);
      if (dlBtn) {
        dlBtn.className = "sr-btn-dl";
        dlBtn.textContent = "Download";
        dlBtn.disabled = false;
        dlBtn.replaceWith(dlBtn.cloneNode(true));
        const newBtn = document.querySelector(`.sr-btn-dl[data-id="${videoId}"]`);
        newBtn.addEventListener("click", () => startDownload(videoId));
      }
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

  // Check if there's an active job (page reload)
  try {
    const res = await fetch("/api/job-status");
    const status = await res.json();
    if (status.active) {
      phaseStartTime = status.phaseStartedAt || Date.now();
      lastPhase = status.phase === "processing" ? "processing" : "downloading";
      startJobPolling(status.videoId);
    }
  } catch {}
}

init();
