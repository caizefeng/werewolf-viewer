/**
 * Werewolf Viewer - Video player with custom controls, mask overlays,
 * interactive night-phase markers, and resizable name masks.
 */

export class WerewolfPlayer {
  constructor(elements) {
    this.video = elements.video;
    this.wrapper = elements.wrapper;
    this.nightOverlay = elements.nightOverlay;
    this.nameMasksContainer = elements.nameMasks;
    this.toggleBtn = elements.toggleMasks;
    this.phaseIndicator = elements.phaseIndicator;
    this.statusEl = elements.status;
    this.playBtn = elements.playBtn;
    this.timeDisplay = elements.timeDisplay;
    this.volumeSlider = elements.volumeSlider;
    this.fullscreenBtn = elements.fullscreenBtn;
    this.progressContainer = elements.progressContainer;
    this.progressBar = elements.progressBar;
    this.progressPlayed = elements.progressPlayed;
    this.progressBuffered = elements.progressBuffered;
    this.nightMarkersEl = elements.nightMarkers;
    this.addPhaseBtn = elements.addPhaseBtn;
    this.resetMasksBtn = elements.resetMasksBtn;
    this.resetNightsBtn = elements.resetNightsBtn;
    this.nightJumpButtons = elements.nightJumpButtons;

    this.metadata = null;
    this._defaultNameMasks = null;
    this._defaultNightPhases = null;
    this.masksEnabled = true;
    this.isNight = false;
    this.savedVolume = 1;
    this.hideTimer = null;
    this.isSeeking = false;

    this._bindEvents();
  }

  // ── Events ──

  _bindEvents() {
    // Video events
    this.video.addEventListener("timeupdate", () => this._onTimeUpdate());
    this.video.addEventListener("play", () => this._updatePlayBtn());
    this.video.addEventListener("pause", () => {
      this._updatePlayBtn();
      this._showControls();
    });
    this.video.addEventListener("ended", () => this._updatePlayBtn());
    this.video.addEventListener("loadedmetadata", () => this._updateTime());
    this.video.addEventListener("progress", () => this._updateBuffered());
    this.video.addEventListener("volumechange", () => {
      this.volumeSlider.value = this.video.muted ? 0 : this.video.volume;
    });

    // Play/pause
    this.playBtn.addEventListener("click", () => this._togglePlay());
    this.video.addEventListener("click", () => this._togglePlay());

    // Volume
    this.volumeSlider.addEventListener("input", () => {
      const v = parseFloat(this.volumeSlider.value);
      this.video.volume = v;
      this.video.muted = v === 0;
      this.savedVolume = v || this.savedVolume;
    });

    // Progress bar seek
    this.progressContainer.addEventListener("mousedown", (e) => this._startSeek(e));
    document.addEventListener("mousemove", (e) => { if (this.isSeeking) this._doSeek(e); });
    document.addEventListener("mouseup", () => { if (this.isSeeking) this._endSeek(); });

    // Mask toggle
    this.toggleBtn.addEventListener("click", () => this.toggleMasks());

    // Fullscreen
    this.fullscreenBtn.addEventListener("click", () => this._toggleFullscreen());
    document.addEventListener("fullscreenchange", () => this._onFullscreenChange());

    // Add night phase
    this.addPhaseBtn.addEventListener("click", () => this._addNightPhase());

    // Reset buttons
    this.resetMasksBtn.addEventListener("click", () => this._resetMasks());
    this.resetNightsBtn.addEventListener("click", () => this._resetNightPhases());

    // Controls show/hide
    this.wrapper.addEventListener("mousemove", () => this._showControls());
    this.wrapper.addEventListener("mouseleave", () => this._startHideTimer());

    // Keyboard
    document.addEventListener("keydown", (e) => this._onKeyDown(e));
  }

  // ── Metadata & Video ──

  async loadMetadata(url) {
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      this.metadata = await res.json();
      // Deep-copy originals for reset
      this._defaultNameMasks = JSON.parse(JSON.stringify(this.metadata.name_masks));
      this._defaultNightPhases = JSON.parse(JSON.stringify(this.metadata.night_phases));
      this.statusEl.textContent = `Loaded: ${this.metadata.night_phases.length} night phases, ${this.metadata.name_masks.length} mask regions`;
      this.createNameMasks();
      this._renderNightMarkers();
      return true;
    } catch (err) {
      this.statusEl.textContent = `Failed to load metadata: ${err.message}`;
      console.error("Failed to load metadata:", err);
      return false;
    }
  }

  loadVideo(url) {
    this.video.src = url;
  }

  // ── Name masks ──

  createNameMasks() {
    this.nameMasksContainer.innerHTML = "";
    if (!this.metadata?.name_masks) return;

    for (const mask of this.metadata.name_masks) {
      const el = document.createElement("div");
      el.className = "name-mask";
      el.style.left = `${mask.x * 100}%`;
      el.style.top = `${mask.y * 100}%`;
      el.style.width = `${mask.w * 100}%`;
      el.style.height = `${mask.h * 100}%`;
      if (!this.masksEnabled) el.classList.add("hidden");

      // Inner edge (closer to center): right handle for left masks, left handle for right masks
      const innerSide = mask.x < 0.5 ? "right" : "left";
      const outerSide = mask.x < 0.5 ? "left" : "right";

      // Inner hover zone + handle
      const innerZone = document.createElement("div");
      innerZone.className = `mask-hover-zone zone-${innerSide}`;
      const innerHandle = document.createElement("div");
      innerHandle.className = `resize-handle handle-${innerSide}`;
      innerZone.appendChild(innerHandle);
      el.appendChild(innerZone);
      this._bindMaskResize(el, innerHandle, mask, `handle-${innerSide}`);

      // Outer hover zone + handle
      const outerZone = document.createElement("div");
      outerZone.className = `mask-hover-zone zone-${outerSide}`;
      const outerHandle = document.createElement("div");
      outerHandle.className = `resize-handle handle-${outerSide}`;
      outerZone.appendChild(outerHandle);
      el.appendChild(outerZone);
      this._bindMaskResize(el, outerHandle, mask, `handle-${outerSide}`);

      this.nameMasksContainer.appendChild(el);
    }
  }

  _bindMaskResize(el, handle, mask, handleSide) {
    let startX, startLeft, startW;

    const onMouseDown = (e) => {
      e.preventDefault();
      e.stopPropagation();
      startX = e.clientX;
      const elRect = el.getBoundingClientRect();
      const wrapperW = this.wrapper.getBoundingClientRect().width;
      const wrapperLeft = this.wrapper.getBoundingClientRect().left;
      startW = elRect.width;
      startLeft = elRect.left - wrapperLeft;
      const maxW = wrapperW * 0.5;

      const onMove = (ev) => {
        const dx = ev.clientX - startX;
        let newW, newLeft;

        if (handleSide === "handle-right") {
          // Dragging right edge: width changes, left stays
          newW = Math.max(0, Math.min(startW + dx, maxW));
          newLeft = startLeft;
        } else {
          // Dragging left edge: width changes inversely, left shifts
          newW = Math.max(0, Math.min(startW - dx, maxW));
          newLeft = startLeft + (startW - newW);
        }

        el.style.width = `${(newW / wrapperW) * 100}%`;
        el.style.left = `${(newLeft / wrapperW) * 100}%`;
      };

      const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      };

      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    };

    handle.addEventListener("mousedown", onMouseDown);
  }

  // ── Custom controls: play/pause ──

  _togglePlay() {
    if (this.video.paused || this.video.ended) {
      this.video.play();
    } else {
      this.video.pause();
    }
  }

  _updatePlayBtn() {
    this.playBtn.textContent = this.video.paused ? "▶" : "⏸";
  }

  // ── Custom controls: time ──

  _updateTime() {
    const cur = this._fmt(this.video.currentTime);
    const dur = this._fmt(this.video.duration || 0);
    this.timeDisplay.textContent = `${cur} / ${dur}`;
  }

  _fmt(s) {
    if (!isFinite(s)) return "0:00";
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, "0")}`;
  }

  // ── Custom controls: seek ──

  _startSeek(e) {
    this.isSeeking = true;
    this._doSeek(e);
  }

  _doSeek(e) {
    const rect = this.progressBar.getBoundingClientRect();
    const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    if (this.video.duration) {
      this.video.currentTime = pct * this.video.duration;
    }
    this.progressPlayed.style.width = `${pct * 100}%`;
  }

  _endSeek() {
    this.isSeeking = false;
  }

  // ── Custom controls: buffered ──

  _updateBuffered() {
    if (!this.video.duration || this.video.buffered.length === 0) return;
    const end = this.video.buffered.end(this.video.buffered.length - 1);
    this.progressBuffered.style.width = `${(end / this.video.duration) * 100}%`;
  }

  // ── Fullscreen ──

  _toggleFullscreen() {
    if (document.fullscreenElement) {
      document.exitFullscreen();
    } else {
      this.wrapper.requestFullscreen();
    }
  }

  _onFullscreenChange() {
    this.fullscreenBtn.textContent = document.fullscreenElement ? "⛶" : "⛶";
  }

  // ── Controls show/hide ──

  _showControls() {
    this.wrapper.classList.add("controls-visible");
    this.wrapper.classList.remove("hide-cursor");
    this._startHideTimer();
  }

  _startHideTimer() {
    clearTimeout(this.hideTimer);
    if (this.video.paused) return; // always visible when paused
    this.hideTimer = setTimeout(() => {
      this.wrapper.classList.remove("controls-visible");
      if (document.fullscreenElement) {
        this.wrapper.classList.add("hide-cursor");
      }
    }, 3000);
  }

  // ── Night phase logic ──

  _onTimeUpdate() {
    if (!this.metadata) return;
    const t = this.video.currentTime;
    const wasNight = this.isNight;

    this.isNight = this.metadata.night_phases.some(
      (phase) => t >= phase.start && t <= phase.end
    );

    if (this.isNight !== wasNight) {
      this._updateNightState();
    }

    // Name masks only appear after the first night ends
    this._updateMaskVisibility(t);

    this._updateTime();
    if (!this.isSeeking && this.video.duration) {
      this.progressPlayed.style.width = `${(t / this.video.duration) * 100}%`;
    }
  }

  _updateNightState() {
    if (this.isNight && this.masksEnabled) {
      this.nightOverlay.classList.remove("hidden");
      this.savedVolume = this.video.volume;
      this.video.muted = true;
      this.phaseIndicator.textContent = "🌙 Night";
    } else {
      this.nightOverlay.classList.add("hidden");
      if (this.video.muted && this.masksEnabled) {
        this.video.muted = false;
        this.video.volume = this.savedVolume;
      }
      this.phaseIndicator.textContent = "☀️ Day";
    }
  }

  _updateMaskVisibility(t) {
    const masks = this.nameMasksContainer.querySelectorAll(".name-mask");
    if (!this.masksEnabled || !this.metadata?.night_phases?.length) {
      masks.forEach((el) => el.classList.add("hidden"));
      return;
    }

    // Names only appear after the first night ends, and not during night phases
    const firstNightEnd = this.metadata.night_phases[0].end;
    const shouldShow = t >= firstNightEnd && !this.isNight;

    masks.forEach((el) => el.classList.toggle("hidden", !shouldShow));
  }

  // ── Night markers on progress bar ──

  _renderNightMarkers() {
    this.nightMarkersEl.innerHTML = "";
    if (!this.metadata?.night_phases) return;

    // Wait for duration to be known
    const render = () => {
      if (!this.video.duration) return;
      this.nightMarkersEl.innerHTML = "";
      this._renderNightJumpButtons();
      const dur = this.video.duration;

      this.metadata.night_phases.forEach((phase, i) => {
        const left = (phase.start / dur) * 100;
        const width = ((phase.end - phase.start) / dur) * 100;

        const marker = document.createElement("div");
        marker.className = "night-marker";
        marker.style.left = `${left}%`;
        marker.style.width = `${width}%`;
        marker.dataset.tooltip = `${this._fmt(phase.start)} – ${this._fmt(phase.end)}`;

        // Drag handles
        const startHandle = document.createElement("div");
        startHandle.className = "night-handle handle-start";
        const endHandle = document.createElement("div");
        endHandle.className = "night-handle handle-end";

        // Remove button
        const removeBtn = document.createElement("button");
        removeBtn.className = "remove-phase";
        removeBtn.textContent = "×";
        removeBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          this.metadata.night_phases.splice(i, 1);
          this._renderNightMarkers();
          this._onTimeUpdate(); // re-evaluate current state
          this.statusEl.textContent = `Removed night phase ${i + 1}`;
        });

        marker.appendChild(startHandle);
        marker.appendChild(endHandle);
        marker.appendChild(removeBtn);
        this.nightMarkersEl.appendChild(marker);

        this._bindHandleDrag(startHandle, phase, "start", dur, i);
        this._bindHandleDrag(endHandle, phase, "end", dur, i);
      });
    };

    if (this.video.duration) {
      render();
    } else {
      this.video.addEventListener("loadedmetadata", render, { once: true });
    }
  }

  _renderNightJumpButtons() {
    this.nightJumpButtons.innerHTML = "";
    if (!this.metadata?.night_phases?.length) return;

    const sorted = this.metadata.night_phases
      .map((p, i) => ({ ...p, idx: i }))
      .sort((a, b) => a.start - b.start);

    sorted.forEach((phase, i) => {
      if (i > 0) {
        const sep = document.createElement("div");
        sep.className = "night-jump-sep";
        this.nightJumpButtons.appendChild(sep);
      }

      const startBtn = document.createElement("button");
      startBtn.className = "night-jump-btn";
      startBtn.textContent = this._fmt(phase.start);
      startBtn.title = `Night ${i + 1} start`;
      startBtn.addEventListener("click", () => {
        this.video.currentTime = phase.start;
      });

      const endBtn = document.createElement("button");
      endBtn.className = "night-jump-btn jump-end";
      endBtn.textContent = this._fmt(phase.end);
      endBtn.title = `Night ${i + 1} end (dawn)`;
      endBtn.addEventListener("click", () => {
        this.video.currentTime = phase.end;
      });

      this.nightJumpButtons.appendChild(startBtn);
      this.nightJumpButtons.appendChild(endBtn);
    });
  }

  _bindHandleDrag(handle, phase, edge, duration, index) {
    handle.addEventListener("mousedown", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const barRect = this.progressBar.getBoundingClientRect();

      const onMove = (ev) => {
        const pct = Math.max(0, Math.min(1, (ev.clientX - barRect.left) / barRect.width));
        const time = pct * duration;

        if (edge === "start") {
          phase.start = Math.min(time, phase.end - 1);
        } else {
          phase.end = Math.max(time, phase.start + 1);
        }

        this._renderNightMarkers();
        this._onTimeUpdate();
      };

      const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        this.statusEl.textContent = `Night phase ${index + 1}: ${this._fmt(phase.start)} – ${this._fmt(phase.end)}`;
      };

      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  }

  _addNightPhase() {
    if (!this.metadata) return;
    const t = this.video.currentTime;
    const start = Math.max(0, t - 30);
    const end = t + 30;
    this.metadata.night_phases.push({ start, end });
    this._renderNightMarkers();
    this._onTimeUpdate();
    this.statusEl.textContent = `Added night phase: ${this._fmt(start)} – ${this._fmt(end)}`;
  }

  // ── Reset defaults ──

  _resetMasks() {
    if (!this._defaultNameMasks) return;
    this.metadata.name_masks = JSON.parse(JSON.stringify(this._defaultNameMasks));
    this.createNameMasks();
    this.statusEl.textContent = "Masks reset to default";
  }

  _resetNightPhases() {
    if (!this._defaultNightPhases) return;
    this.metadata.night_phases = JSON.parse(JSON.stringify(this._defaultNightPhases));
    this._renderNightMarkers();
    this._onTimeUpdate();
    this.statusEl.textContent = "Night phases reset to default";
  }

  // ── Mask toggle ──

  toggleMasks() {
    this.masksEnabled = !this.masksEnabled;

    this.toggleBtn.textContent = this.masksEnabled ? "Masks: On" : "Masks: Off";
    this.toggleBtn.classList.toggle("active", this.masksEnabled);

    if (this.masksEnabled && this.isNight) {
      this.nightOverlay.classList.remove("hidden");
      this.savedVolume = this.video.volume;
      this.video.muted = true;
    } else {
      this.nightOverlay.classList.add("hidden");
      this.video.muted = false;
    }

    // Re-evaluate mask visibility based on current time
    this._updateMaskVisibility(this.video.currentTime);
  }

  // ── Keyboard ──

  _onKeyDown(e) {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
    switch (e.key) {
      case "m":
      case "M":
        e.preventDefault();
        this.toggleMasks();
        break;
      case " ":
        e.preventDefault();
        this._togglePlay();
        break;
      case "f":
      case "F":
        e.preventDefault();
        this._toggleFullscreen();
        break;
      case "ArrowLeft":
        e.preventDefault();
        this.video.currentTime = Math.max(0, this.video.currentTime - 5);
        break;
      case "ArrowRight":
        e.preventDefault();
        this.video.currentTime = Math.min(this.video.duration, this.video.currentTime + 5);
        break;
    }
  }
}
