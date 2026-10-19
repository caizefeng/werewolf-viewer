/**
 * Werewolf Viewer - Video player with custom controls, mask overlays,
 * interactive night-phase markers, and resizable name masks.
 */

// Per-browser preference: "full" extends masks to the frame edges (hides
// player names/avatars too); "role" covers only the role-name boxes
const MASK_MODE_KEY = "werewolf.maskMode";
const VOLUME_KEY = "werewolf.volume"; // {volume, muted} as last set by the user

// Reveal band of a player row: their role label's own box plus BAND_PAD,
// never closer than BAND_GUARD to the midpoint toward a neighbouring row
// (fractions of frame height). S22 ribbons end within ~0.005 of the
// midpoint, so the guard is what keeps a neighbour's ribbon colour hidden;
// the pad only matters for 3-character labels. Older metadata without
// label/span falls back to its stored y0/y1.
// What a wolf-side player knows (京城大师赛 boards; rules checked 2026-10-18):
// PACK wolves wake together and know each other -- 狼人 and the wolf-side
// roles below -- while LONE wolves (机械狼, 假面, 盗宝大师, 九尾, a 混血儿
// that copied a wolf, 隐狼) neither meet the pack nor are known to it. So
// revealing as a pack wolf opens the pack and nobody else; revealing as a
// lone wolf opens that seat only. A red-ribbon role the tables don't know
// is treated as pack when its name contains 狼 and as lone otherwise (the
// conservative choice: never show more than the player would know).
const PACK_WOLF_ROLES = new Set(["狼人", "狼王", "白狼王", "黑狼王", "狼美人",
  "狼术师", "诡术师", "血月使徒", "恶灵骑士", "噩梦之影", "梦魇", "狼巫"]);
const LONE_WOLF_ROLES = new Set(["机械狼", "假面", "盗宝大师", "九尾", "九尾狐", "混血儿", "隐狼"]);

const BAND_PAD = 0.035;
const BAND_GUARD = 0.013;
function revealBand(p) {
  if (Array.isArray(p.label) && Array.isArray(p.span)) {
    const y0 = Math.max(p.label[0] - BAND_PAD, p.span[0] + BAND_GUARD);
    const y1 = Math.min(p.label[1] + BAND_PAD, p.span[1] - BAND_GUARD);
    if (y1 - y0 >= 0.03) return [y0, y1];
    return [p.span[0] + BAND_GUARD, p.span[1] - BAND_GUARD];
  }
  return [p.y0, p.y1];
}
const REVEAL_MODE_KEY = "werewolf.revealMode"; // "player" | "role"

export class WerewolfPlayer {
  constructor(elements) {
    this.video = elements.video;
    this.wrapper = elements.wrapper;
    this.nightOverlay = elements.nightOverlay;
    this.nameMasksContainer = elements.nameMasks;
    this.toggleBtn = elements.toggleMasks;
    this.maskModeBtn = elements.maskModeBtn;
    this.phaseIndicator = elements.phaseIndicator;
    this.statusEl = elements.status;
    this.playBtn = elements.playBtn;
    this.timeDisplay = elements.timeDisplay;
    this.volumeSlider = elements.volumeSlider;
    this.muteBtn = elements.muteBtn;
    this.fullscreenBtn = elements.fullscreenBtn;
    this.progressContainer = elements.progressContainer;
    this.progressBar = elements.progressBar;
    this.progressPlayed = elements.progressPlayed;
    this.progressBuffered = elements.progressBuffered;
    this.nightMarkersEl = elements.nightMarkers;
    this.addPhaseBtn = elements.addPhaseBtn;
    this.addMaskBtn = elements.addMaskBtn;
    this.resetMasksBtn = elements.resetMasksBtn;
    this.resetNightsBtn = elements.resetNightsBtn;
    this.nightJumpButtons = elements.nightJumpButtons;
    this.rolePanel = elements.rolePanel;

    this.metadata = null;
    this.videoId = null;
    this.roleMap = {};
    this.revealed = new Set(); // reveal keys the user has un-blinded
    this.hiddenRoles = false; // hidden-roles broadcast (roles shown as 未知)
    this.revealMode = this._loadRevealMode();
    this._defaultNameMasks = null;
    this._defaultNightPhases = null;
    this.masksEnabled = true;
    this.maskMode = this._loadMaskMode();
    this.isNight = false;
    this.savedVolume = 1;
    this.userMuted = false; // mute requested by the user (vs. night auto-mute)
    this.hideTimer = null;
    this.isSeeking = false;

    this._bindEvents();
    this._updateMaskModeBtn();
    this._restoreVolume();
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
      this._updateMuteBtn();
    });

    // Play/pause
    this.playBtn.addEventListener("click", () => this._togglePlay());
    this.video.addEventListener("click", () => this._togglePlay());

    // Volume
    this.volumeSlider.addEventListener("input", () => {
      const v = parseFloat(this.volumeSlider.value);
      this.video.volume = v;
      this.video.muted = v === 0;
      this.userMuted = v === 0;
      this.savedVolume = v || this.savedVolume;
      this._persistVolume();
    });

    // Mute toggle
    this.muteBtn.addEventListener("click", () => this.toggleMute());

    // Progress bar seek
    this.progressContainer.addEventListener("mousedown", (e) => this._startSeek(e));
    document.addEventListener("mousemove", (e) => { if (this.isSeeking) this._doSeek(e); });
    document.addEventListener("mouseup", () => { if (this.isSeeking) this._endSeek(); });

    // Mask toggle
    this.toggleBtn.addEventListener("click", () => this.toggleMasks());
    this.maskModeBtn.addEventListener("click", () => this.toggleMaskMode());

    // Fullscreen
    this.fullscreenBtn.addEventListener("click", () => this._toggleFullscreen());
    document.addEventListener("fullscreenchange", () => this._onFullscreenChange());
    window.addEventListener("resize", () => this._fitMasksToVideo());

    // Add night phase
    this.addPhaseBtn.addEventListener("click", () => this._addNightPhase());

    // Add mask
    this.addMaskBtn.addEventListener("click", () => this._addNameMask());

    // Reset buttons
    this.resetMasksBtn.addEventListener("click", () => this._resetMasks());
    this.resetNightsBtn.addEventListener("click", () => this._resetNightPhases());

    // Controls show/hide
    this.wrapper.addEventListener("mousemove", () => this._showControls());
    // Let the wrapper (and so every overlay) follow the stream's real aspect
    this.video.addEventListener("loadedmetadata", () => {
      if (this.video.videoWidth && this.video.videoHeight) {
        this.wrapper.style.setProperty("--video-aspect", (this.video.videoWidth / this.video.videoHeight).toFixed(4));
      }
      this._fitMasksToVideo();
    });
    this.wrapper.addEventListener("mouseleave", () => this._startHideTimer());

    // Keyboard
    document.addEventListener("keydown", (e) => this._onKeyDown(e));
  }

  // ── Metadata & Video ──

  async loadMetadata(url) {
    this.metadata = null;
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      this.metadata = await res.json();
      // Reset restores the auto-detected values (preserved server-side in
      // original_* once the user saves edits); fall back to loaded values
      this._defaultNameMasks = JSON.parse(JSON.stringify(
        this.metadata.original_name_masks ?? this.metadata.name_masks));
      this._defaultNightPhases = JSON.parse(JSON.stringify(
        this.metadata.original_night_phases ?? this.metadata.night_phases));
      this.statusEl.textContent = `Loaded: ${this.metadata.night_phases.length} night phases, ${this.metadata.name_masks.length} mask regions`;
      this.roleMap = this.metadata.role_map || {};
      this.hiddenRoles = !!this.metadata.hidden_roles;
      // Hidden-roles broadcasts (the show hides roles itself) start with
      // masks off; every other video starts masked (spoiler-safe default)
      this.masksEnabled = !this.hiddenRoles;
      this._updateMaskToggleBtn();
      this.isNight = false;
      this._updateNightState();
      if (this.hiddenRoles) this.statusEl.textContent += " \u00b7 hidden-roles broadcast: masks off";
      this._loadReveal();
      this.createNameMasks();
      this._updateMaskVisibility(this.video.currentTime);
      this._renderNightMarkers();
      this._renderRolePanel();
      return true;
    } catch (err) {
      // Clear stale UI from the previously loaded video
      this.roleMap = {};
      this.revealed = new Set();
      this.hiddenRoles = false;
      this.masksEnabled = true;
      this._updateMaskToggleBtn();
      this.createNameMasks();
      this._renderNightMarkers();
      this._renderNightJumpButtons();
      this._renderRolePanel();
      this.isNight = false;
      this._updateNightState();
      this.statusEl.textContent = `Failed to load metadata: ${err.message}`;
      console.error("Failed to load metadata:", err);
      return false;
    }
  }

  loadVideo(url) {
    this.video.src = url;
  }

  // Drop the loaded video's state (used when it is deleted)
  clear() {
    this.metadata = null;
    this.videoId = null;
    this.roleMap = {};
    this.revealed = new Set();
    this.hiddenRoles = false;
    this.masksEnabled = true;
    this._updateMaskToggleBtn();
    this.createNameMasks();
    this._renderNightMarkers();
    this._renderNightJumpButtons();
    this._renderRolePanel();
    this.isNight = false;
    this._updateNightState();
    this.statusEl.textContent = "";
  }

  // Persist current night phases + masks back to the server's metadata.json
  async saveMetadata() {
    if (!this.videoId || !this.metadata) return;
    try {
      const res = await fetch("/api/metadata", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          videoId: this.videoId,
          night_phases: this.metadata.night_phases,
          name_masks: this.metadata.name_masks,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      this.statusEl.textContent += " · saved";
    } catch (err) {
      this.statusEl.textContent = `Failed to save edits: ${err.message}`;
    }
  }

  // ── Name masks ──

  createNameMasks() {
    this.nameMasksContainer.innerHTML = "";
    if (!this.metadata?.name_masks) return;

    for (const mask of this.metadata.name_masks) {
      const box = this._renderedBox(mask);
      const el = document.createElement("div");
      el.className = "name-mask";
      el.style.top = `${mask.y * 100}%`;
      el.style.height = `${mask.h * 100}%`;
      if (this.maskMode === "full") {
        // Overshoot the frame edge by 2px so subpixel rounding can never
        // leave a sliver of video at the canvas boundary
        if (this._maskSide(mask) === "left") {
          el.style.left = "-2px";
          el.style.width = `calc(${box.width * 100}% + 2px)`;
        } else {
          el.style.left = `${box.left * 100}%`;
          el.style.width = `calc(${box.width * 100}% + 2px)`;
        }
      } else {
        el.style.left = `${box.left * 100}%`;
        el.style.width = `${box.width * 100}%`;
      }
      if (!this.masksEnabled) el.classList.add("hidden");

      // Inner edge (closer to center): right handle for left masks, left handle for right masks
      const side = this._maskSide(mask);
      const innerSide = side === "left" ? "right" : "left";
      const outerSide = side;

      el.classList.add(side);

      // Opaque fill in vertical segments, leaving a gap at each revealed
      // player row so their role shows through (role-reveal panel)
      for (const [segTop, segBot] of this._fillSegments(side, mask)) {
        const fill = document.createElement("div");
        fill.className = "name-mask-fill";
        fill.style.top = `${segTop * 100}%`;
        fill.style.height = `${(segBot - segTop) * 100}%`;
        el.appendChild(fill);
      }

      // Per-player wire frames: one thin outline per seat band (gold, not
      // the mask's colour), dim while covered and bright around a revealed
      // row, with the seat number in the outer corner (seat IDs are public)
      const mh = mask.h || 1;
      for (const p of (this.roleMap?.[side] || [])) {
        const [by0, by1] = revealBand(p);
        const top = Math.max(0, (by0 - mask.y) / mh);
        const bot = Math.min(1, (by1 - mask.y) / mh);
        if (bot <= top) continue;
        const frame = document.createElement("div");
        frame.className = "name-mask-frame" + (this.revealed.has(this._revealKey(side, p)) ? " revealed" : "");
        frame.style.top = `${top * 100}%`;
        frame.style.height = `${(bot - top) * 100}%`;
        const num = document.createElement("span");
        num.className = "name-mask-frame-num";
        num.textContent = p.number;
        frame.appendChild(num);
        el.appendChild(frame);
      }

      // Inner hover zone + handle
      const innerZone = document.createElement("div");
      innerZone.className = `mask-hover-zone zone-${innerSide}`;
      const innerHandle = document.createElement("div");
      innerHandle.className = `resize-handle handle-${innerSide}`;
      innerZone.appendChild(innerHandle);
      el.appendChild(innerZone);
      this._bindMaskResize(el, innerHandle, mask, `handle-${innerSide}`);

      // Outer hover zone + handle (role mode only: in full mode the outer
      // edge is pinned to the frame edge)
      if (this.maskMode !== "full") {
        const outerZone = document.createElement("div");
        outerZone.className = `mask-hover-zone zone-${outerSide}`;
        const outerHandle = document.createElement("div");
        outerHandle.className = `resize-handle handle-${outerSide}`;
        outerZone.appendChild(outerHandle);
        el.appendChild(outerZone);
        this._bindMaskResize(el, outerHandle, mask, `handle-${outerSide}`);
      }

      // Delete button (visible on hover)
      const delBtn = document.createElement("button");
      delBtn.className = "mask-delete-btn";
      delBtn.textContent = "×";
      delBtn.title = "Remove this mask";
      delBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const idx = this.metadata.name_masks.indexOf(mask);
        if (idx !== -1) {
          this.metadata.name_masks.splice(idx, 1);
          this.createNameMasks();
          this._updateMaskVisibility(this.video.currentTime);
          this.statusEl.textContent = `Removed mask region`;
          this.saveMetadata();
        }
      });
      el.appendChild(delBtn);

      this.nameMasksContainer.appendChild(el);
    }
  }

  // ── Mask mode (full = extend to frame edges, role = role-name box only) ──

  _loadMaskMode() {
    try {
      const v = localStorage.getItem(MASK_MODE_KEY);
      if (v === "role" || v === "full") return v;
    } catch {}
    return "full";
  }

  toggleMaskMode() {
    this.maskMode = this.maskMode === "full" ? "role" : "full";
    try { localStorage.setItem(MASK_MODE_KEY, this.maskMode); } catch {}
    this._updateMaskModeBtn();
    this.createNameMasks();
    this._updateMaskVisibility(this.video.currentTime);
    this.statusEl.textContent = this.maskMode === "full"
      ? "Masks extended to frame edges (role + player names hidden)"
      : "Masks cover role names only";
  }

  _updateMaskModeBtn() {
    const full = this.maskMode === "full";
    this.maskModeBtn.textContent = full ? "Mask: Full" : "Mask: Roles";
    this.maskModeBtn.title = full
      ? "Masks extend to the frame edges, hiding player names and avatars too. Click to hide role names only."
      : "Masks hide role names only. Click to also hide player names and avatars.";
  }

  _maskSide(mask) {
    return mask.x < 0.5 ? "left" : "right";
  }

  // Masks are stored as the role-name box. In full mode the rendered box
  // is extended outward to the frame edge on its side.
  _renderedBox(mask) {
    const r4 = (v) => Math.round(v * 10000) / 10000;
    if (this.maskMode !== "full") return { left: mask.x, width: mask.w };
    if (this._maskSide(mask) === "left") return { left: 0, width: r4(mask.x + mask.w) };
    return { left: mask.x, width: r4(1 - mask.x) };
  }

  // Inverse of _renderedBox: write a rendered box back to the stored
  // role box. In full mode only the inner edge can have moved.
  _storeRenderedBox(mask, left, width) {
    const r4 = (v) => Math.round(v * 10000) / 10000;
    if (this.maskMode !== "full") {
      mask.x = r4(left);
      mask.w = r4(width);
    } else if (this._maskSide(mask) === "left") {
      const inner = left + width;
      mask.x = r4(Math.min(mask.x, inner));
      mask.w = r4(inner - mask.x);
    } else {
      const outer = Math.max(mask.x + mask.w, left);
      mask.x = r4(left);
      mask.w = r4(outer - left);
    }
  }

  // ── Role reveal ──

  _revealKey(side, p) {
    return `${side}:${p.number}`;
  }

  _revealedBandsForSide(side) {
    const players = (this.roleMap && this.roleMap[side]) || [];
    return players
      .filter((p) => this.revealed.has(this._revealKey(side, p)))
      .map((p) => revealBand(p));
  }

  // Opaque fill segments = the full mask column minus the revealed bands
  _fillSegments(side, mask) {
    const h = mask.h || 1;
    const bands = this._revealedBandsForSide(side)
      .map(([a, b]) => [(a - mask.y) / h, (b - mask.y) / h])
      .map(([a, b]) => [Math.max(0, Math.min(1, a)), Math.max(0, Math.min(1, b))])
      .filter(([a, b]) => b > a)
      .sort((p, q) => p[0] - q[0]);
    const merged = [];
    for (const [a, b] of bands) {
      if (merged.length && a <= merged[merged.length - 1][1]) {
        merged[merged.length - 1][1] = Math.max(merged[merged.length - 1][1], b);
      } else {
        merged.push([a, b]);
      }
    }
    const segs = [];
    let cur = 0;
    for (const [a, b] of merged) {
      if (a > cur) segs.push([cur, a]);
      cur = Math.max(cur, b);
    }
    if (cur < 1) segs.push([cur, 1]);
    return segs;
  }

  _allRevealKeys() {
    const keys = [];
    for (const side of ["left", "right"]) {
      for (const p of (this.roleMap[side] || [])) keys.push(this._revealKey(side, p));
    }
    return keys;
  }

  _loadReveal() {
    this.revealed = new Set();
    if (!this.videoId) return;
    try {
      const raw = localStorage.getItem(`werewolf.reveal.${this.videoId}`);
      if (raw) for (const k of JSON.parse(raw)) this.revealed.add(k);
    } catch {}
  }

  _persistReveal() {
    if (!this.videoId) return;
    try {
      localStorage.setItem(`werewolf.reveal.${this.videoId}`,
        JSON.stringify([...this.revealed]));
    } catch {}
  }

  _applyReveal() {
    this.createNameMasks();
    this._updateMaskVisibility(this.video.currentTime);
    this._renderRolePanel();
    this._persistReveal();
  }

  _setAllRevealed(on) {
    this.revealed = new Set(on ? this._allRevealKeys() : []);
    this.statusEl.textContent = on ? "All roles revealed" : "All roles hidden (blind)";
    this._applyReveal();
  }

  // Wolf-aligned roles (any role whose name contains 狼) see each other at
  // night, so revealing one reveals the whole pack — mimics playing as a wolf.
  // Wolf team membership: the ribbon colour the analysis measured (faction
  // "wolf" / "good") when present, else the role name containing 狼. The
  // colour is what covers wolf-side roles whose names do not say wolf
  // (假面, a 混血儿 that copied a wolf, roles added later).
  _isWolf(x) {
    if (x && typeof x === "object") {
      // Colour can only ADD a wolf (假面, 盗宝大师, 九尾, 诡术师 …); a name with
      // 狼 in it is wolf-side whatever the measured ribbon said
      return x.faction === "wolf" || this._isWolf(x.role);
    }
    return !!x && x.includes("\u72fc");
  }

  // "pack" (wakes with and knows the other pack wolves), "lone" (wolf-side
  // but knows nobody) or null (not wolf-side)
  _wolfKind(p) {
    if (!this._isWolf(p)) return null;
    if (PACK_WOLF_ROLES.has(p.role)) return "pack";
    if (LONE_WOLF_ROLES.has(p.role)) return "lone";
    return p.role && p.role.includes("\u72fc") ? "pack" : "lone";
  }

  _wolfKeys() {
    const keys = [];
    for (const side of ["left", "right"]) {
      for (const p of (this.roleMap[side] || [])) {
        if (this._wolfKind(p) === "pack") keys.push(this._revealKey(side, p));
      }
    }
    return keys;
  }

  _toggleReveal(key, side, p, label) {
    const turningOn = !this.revealed.has(key);
    const who = label || `#${p.number}`;
    const kind = this._wolfKind(p);
    if (kind === "pack") {
      // Reveal/hide the whole pack together: these wolves know each other.
      // Lone wolves are not in the pack's knowledge and stay as they are
      const keys = this._wolfKeys();
      for (const k of keys) {
        if (turningOn) this.revealed.add(k);
        else this.revealed.delete(k);
      }
      this.statusEl.textContent = turningOn
        ? `Revealed ${who} and the rest of the wolf pack (${keys.length})`
        : "Hid the wolf pack";
    } else if (kind === "lone") {
      // A lone wolf knows nobody: only this seat
      if (turningOn) this.revealed.add(key);
      else this.revealed.delete(key);
      this.statusEl.textContent = `${turningOn ? "Revealed" : "Hid"} ${who} (plays alone, does not know the pack)`;
    } else {
      if (turningOn) this.revealed.add(key);
      else this.revealed.delete(key);
      this.statusEl.textContent = `${turningOn ? "Revealed" : "Hid"} ${who}`;
    }
    this._applyReveal();
  }

  // ── Reveal modes: by player (seat) or by role ──

  _loadRevealMode() {
    try {
      const v = localStorage.getItem(REVEAL_MODE_KEY);
      if (v === "player" || v === "role") return v;
    } catch {}
    return "role";
  }

  setRevealMode(mode) {
    this.revealMode = mode;
    try { localStorage.setItem(REVEAL_MODE_KEY, mode); } catch {}
    this._renderRolePanel();
  }

  // Role mode lists "平民 1..N" etc. without any seat numbers. The index ->
  // seat assignment is a random permutation (so the menu order leaks
  // nothing), generated once per video and remembered so the labels stay
  // stable across reloads.
  _roleEntries() {
    const groups = new Map(); // role -> [{side, p}]
    for (const side of ["left", "right"]) {
      for (const p of (this.roleMap[side] || [])) {
        if (!groups.has(p.role)) groups.set(p.role, []);
        groups.get(p.role).push({ side, p });
      }
    }
    const storeKey = `werewolf.roleorder.${this.videoId}`;
    let stored = {};
    try { stored = JSON.parse(localStorage.getItem(storeKey)) || {}; } catch {}
    let changed = false;
    const entries = [];
    const rank = (role) => {
      const kinds = groups.get(role).map((m) => this._wolfKind(m.p));
      return kinds.includes("pack") ? 2 : (kinds.includes("lone") ? 1 : 0);
    };
    const roles = [...groups.keys()].sort((a, b) =>
      (rank(b) - rank(a)) ||
      (Number(a === "") - Number(b === "")) ||          // unrecognised last
      (groups.get(b).length - groups.get(a).length) ||
      a.localeCompare(b, "zh"));
    for (const role of roles) {
      const members = groups.get(role);
      const keys = members.map((m) => this._revealKey(m.side, m.p));
      let order = Array.isArray(stored[role]) ? stored[role].filter((k) => keys.includes(k)) : [];
      if (order.length !== keys.length || new Set(order).size !== keys.length) {
        order = keys.slice();
        for (let i = order.length - 1; i > 0; i--) {
          const j = Math.floor(Math.random() * (i + 1));
          [order[i], order[j]] = [order[j], order[i]];
        }
        stored[role] = order;
        changed = true;
      }
      const name = role || "\u672a\u8bc6\u522b";   // unrecognised label
      order.forEach((key, i) => {
        const m = members.find((x) => this._revealKey(x.side, x.p) === key);
        entries.push({
          role, key, side: m.side, p: m.p,
          label: members.length > 1 ? `${name} ${i + 1}` : name,
        });
      });
    }
    if (changed && this.videoId) {
      try { localStorage.setItem(storeKey, JSON.stringify(stored)); } catch {}
    }
    return entries;
  }

  _renderRolePanel() {
    const panel = this.rolePanel;
    if (!panel) return;
    const scrollTop = panel.querySelector(".rp-body")?.scrollTop || 0;
    panel.innerHTML = "";
    panel.classList.toggle("hidden", !this.metadata);
    if (!this.metadata) return;

    const header = document.createElement("div");
    header.className = "rp-header";
    const title = document.createElement("span");
    title.className = "rp-title";
    title.textContent = "Roles";
    header.appendChild(title);
    panel.appendChild(header);

    const empty = (text) => {
      const el = document.createElement("div");
      el.className = "rp-empty";
      el.textContent = text;
      panel.appendChild(el);
    };

    if (this.hiddenRoles) {
      empty("Hidden-roles broadcast: the show itself keeps roles as \u672a\u77e5 and reveals them as the game goes, so masks and role reveal are off for this video.");
      return;
    }

    const players = [];
    for (const side of ["left", "right"]) {
      for (const p of (this.roleMap[side] || [])) players.push({ side, p });
    }
    if (!players.length) {
      empty("No role map for this game. Click \u21bb Re-analyze in the library to map roles.");
      return;
    }

    // Blind / All
    const grp = document.createElement("div");
    grp.className = "rp-actions";
    const blindBtn = document.createElement("button");
    blindBtn.className = "rp-btn";
    blindBtn.textContent = "Blind";
    blindBtn.title = "Hide every role (default)";
    blindBtn.addEventListener("click", () => this._setAllRevealed(false));
    const allBtn = document.createElement("button");
    allBtn.className = "rp-btn";
    allBtn.textContent = "All";
    allBtn.title = "Reveal every role";
    allBtn.addEventListener("click", () => this._setAllRevealed(true));
    grp.appendChild(blindBtn);
    grp.appendChild(allBtn);
    header.appendChild(grp);

    // Mode switch
    const modes = document.createElement("div");
    modes.className = "rp-modes";
    for (const [mode, text, tip] of [
      ["role", "By role", "Pick a role to play as. Seats are not shown; clones (\u5e73\u6c11 1, 2, \u2026) are shuffled."],
      ["player", "By seat", "Pick a seat number to reveal that player's role."],
    ]) {
      const b = document.createElement("button");
      b.className = "rp-mode-btn" + (this.revealMode === mode ? " active" : "");
      b.textContent = text;
      b.title = tip;
      b.addEventListener("click", () => this.setRevealMode(mode));
      modes.appendChild(b);
    }
    panel.appendChild(modes);

    // Pack wolves get the paw (click = the whole pack); lone wolves a
    // dimmed paw (click = this seat only, they know nobody)
    const addPaw = (row, kind) => {
      row.classList.add("rp-wolf");
      if (kind === "lone") row.classList.add("rp-lone");
      row.title = kind === "lone"
        ? "Lone wolf \u2014 does not know the pack; reveals this seat only"
        : "Wolf pack \u2014 reveals/hides all pack wolves together";
      const paw = document.createElement("span");
      paw.className = "rp-paw" + (kind === "lone" ? " rp-paw-lone" : "");
      paw.textContent = "\ud83d\udc3a";
      row.appendChild(paw);
    };

    const body = document.createElement("div");
    body.className = "rp-body";
    panel.appendChild(body);
    if (this.revealMode === "player") {
      players.sort((a, b) => a.p.number - b.p.number);
      for (const { side, p } of players) {
        const key = this._revealKey(side, p);
        const on = this.revealed.has(key);
        const row = document.createElement("div");
        row.className = "rp-row" + (on ? " revealed" : "");
        const num = document.createElement("span");
        num.className = "rp-num";
        num.textContent = p.number;
        const spacer = document.createElement("span");
        spacer.className = "rp-name";
        spacer.textContent = `Seat ${p.number}`;
        const role = document.createElement("span");
        role.className = "rp-role";
        // A seat whose label the OCR could not read has role "": its band is
        // positional, so it opens like any other and the row says so
        role.textContent = on ? (p.role || "\u672a\u8bc6\u522b") : "\u2022\u2022\u2022";
        row.appendChild(num);
        row.appendChild(spacer);
        // The paw (and its "wolf team" tooltip) only once this seat is
        // revealed: marking wolf seats up front would give the game away
        if (on && this._wolfKind(p)) addPaw(row, this._wolfKind(p));
        row.appendChild(role);
        row.addEventListener("click", () => this._toggleReveal(key, side, p));
        body.appendChild(row);
      }
    } else {
      for (const e of this._roleEntries()) {
        const on = this.revealed.has(e.key);
        const row = document.createElement("div");
        row.className = "rp-row" + (on ? " revealed" : "");
        const name = document.createElement("span");
        name.className = "rp-name rp-rolename";
        name.textContent = e.label;
        const state = document.createElement("span");
        state.className = "rp-role";
        // Only once revealed does the row say which seat that was
        state.textContent = on ? `seat ${e.p.number}` : "\u2022\u2022\u2022";
        row.appendChild(name);
        if (this._wolfKind(e.p)) addPaw(row, this._wolfKind(e.p));
        row.appendChild(state);
        row.addEventListener("click", () => this._toggleReveal(e.key, e.side, e.p, e.label));
        body.appendChild(row);
      }
    }
    body.scrollTop = scrollTop;
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
      let lastW = startW;
      let lastLeft = startLeft;
      let moved = false;

      const onMove = (ev) => {
        moved = true;
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
        lastW = newW;
        lastLeft = newLeft;
      };

      const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        if (!moved) return;
        // Write final geometry back to the mask object so re-renders
        // (add/delete mask) keep it, and persist
        this._storeRenderedBox(mask, lastLeft / wrapperW, lastW / wrapperW);
        this.statusEl.textContent = "Resized mask region";
        this.saveMetadata();
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
    this.playBtn.innerHTML = this.video.paused
      ? '<span class="icon-play"></span>'
      : '<span class="icon-pause"></span>';
  }

  // ── Custom controls: time ──

  _updateTime() {
    const cur = this._fmt(this.video.currentTime);
    const dur = this._fmt(this.video.duration || 0);
    this.timeDisplay.textContent = `${cur} / ${dur}`;
  }

  _fmt(s) {
    if (!isFinite(s)) return "0:00";
    s = Math.floor(s);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    if (h) return `${h}:${m.toString().padStart(2, "0")}:${sec.toString().padStart(2, "0")}`;
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
    this.fullscreenBtn.title = document.fullscreenElement ? "Exit fullscreen" : "Fullscreen";
    if (!document.fullscreenElement) {
      this.wrapper.classList.remove("hide-cursor");
    }
    this._fitMasksToVideo();
  }

  // In fullscreen the browser forces the wrapper to fill the screen and the
  // video letterboxes inside it (object-fit: contain). Masks and reveal
  // gaps are fractions of their container, so on a 16:10 or ultrawide
  // screen they would drift off the player rows and show a neighbour's
  // ribbon. Pin the masks container to the video's content box instead.
  _fitMasksToVideo() {
    const el = this.nameMasksContainer;
    const fs = document.fullscreenElement === this.wrapper;
    if (!fs || !this.video.videoWidth || !this.video.videoHeight) {
      el.style.left = el.style.top = el.style.width = el.style.height = "";
      return;
    }
    const W = this.wrapper.clientWidth;
    const H = this.wrapper.clientHeight;
    const scale = Math.min(W / this.video.videoWidth, H / this.video.videoHeight);
    const vw = this.video.videoWidth * scale;
    const vh = this.video.videoHeight * scale;
    el.style.left = `${(W - vw) / 2}px`;
    el.style.top = `${(H - vh) / 2}px`;
    el.style.width = `${vw}px`;
    el.style.height = `${vh}px`;
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
    // The indicator reflects the phase itself; only the blackout/mute
    // depend on masks being enabled
    this.phaseIndicator.textContent = this.isNight ? "🌙 Night" : "☀️ Day";
    this.phaseIndicator.classList.toggle("night", this.isNight);
    if (this.isNight && this.masksEnabled) {
      this.nightOverlay.classList.remove("hidden");
      this.savedVolume = this.video.volume;
      this.video.muted = true;
    } else {
      this.nightOverlay.classList.add("hidden");
      if (this.video.muted && this.masksEnabled && !this.userMuted) {
        this.video.muted = false;
        this.video.volume = this.savedVolume;
      }
    }
  }

  _updateMaskVisibility(t) {
    const masks = this.nameMasksContainer.querySelectorAll(".name-mask");
    if (!this.masksEnabled) {
      masks.forEach((el) => el.classList.add("hidden"));
      return;
    }
    // Role names appear in the sidebar once the first night ends, and the
    // night overlay covers everything during nights. With no detected
    // nights at all (detection failed, or none yet) stay masked throughout.
    const phases = this.metadata?.night_phases || [];
    let shouldShow = true;
    if (phases.length) {
      const first = phases.reduce((a, b) => (a.start <= b.start ? a : b));
      shouldShow = t >= first.end && !this.isNight;
    }
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
          this.saveMetadata();
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
      const group = document.createElement("div");
      group.className = "night-jump-group";

      const label = document.createElement("span");
      label.className = "night-jump-label";
      label.textContent = i + 1;

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

      group.appendChild(label);
      group.appendChild(startBtn);
      group.appendChild(endBtn);
      this.nightJumpButtons.appendChild(group);
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
        this.saveMetadata();
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
    this.saveMetadata();
  }

  _addNameMask() {
    if (!this.metadata) return;
    let newMask, msg;
    if (this.maskMode === "full") {
      // Full mode pins masks to a frame edge: add on whichever side has none
      const sides = new Set(this.metadata.name_masks.map((m) => this._maskSide(m)));
      const side = !sides.has("left") ? "left" : (!sides.has("right") ? "right" : "left");
      newMask = side === "left"
        ? { x: 0, y: 0, w: 0.14, h: 1.0 }
        : { x: 0.86, y: 0, w: 0.14, h: 1.0 };
      msg = `Added ${side} mask. Drag its inner edge to size it.`;
    } else {
      // Place new mask at center of video so it's immediately visible and easy to drag
      newMask = { x: 0.42, y: 0, w: 0.16, h: 1.0 };
      msg = "Added mask at center. Drag edges to position it.";
    }

    this.metadata.name_masks.push(newMask);
    this.createNameMasks();
    this._updateMaskVisibility(this.video.currentTime);
    this.statusEl.textContent = msg;
    this.saveMetadata();
  }

  // ── Reset defaults ──

  _resetMasks() {
    if (!this._defaultNameMasks || !this.metadata) return;
    this.metadata.name_masks = JSON.parse(JSON.stringify(this._defaultNameMasks));
    this.createNameMasks();
    this._updateMaskVisibility(this.video.currentTime);
    this.statusEl.textContent = "Masks reset to default";
    this.saveMetadata();
  }

  _resetNightPhases() {
    if (!this._defaultNightPhases || !this.metadata) return;
    this.metadata.night_phases = JSON.parse(JSON.stringify(this._defaultNightPhases));
    this._renderNightMarkers();
    this._onTimeUpdate();
    this.statusEl.textContent = "Night phases reset to default";
    this.saveMetadata();
  }

  // ── Mask toggle ──

  toggleMasks() {
    this.masksEnabled = !this.masksEnabled;

    this._updateMaskToggleBtn();

    if (this.masksEnabled && this.isNight) {
      this.nightOverlay.classList.remove("hidden");
      this.savedVolume = this.video.volume;
      this.video.muted = true;
    } else {
      this.nightOverlay.classList.add("hidden");
      this.video.muted = this.userMuted;
    }

    // Re-evaluate mask visibility based on current time
    this._updateMaskVisibility(this.video.currentTime);
  }

  _updateMaskToggleBtn() {
    const on = this.masksEnabled;
    this.toggleBtn.textContent = on ? "Masks: On"
      : (this.hiddenRoles ? "Masks: Off (hidden roles)" : "Masks: Off");
    this.toggleBtn.classList.toggle("active", on);
    this.toggleBtn.title = this.hiddenRoles
      ? "Hidden-roles broadcast: the show keeps roles as \u672a\u77e5 itself, so masks are off. Click (or M) to force them on."
      : "Shortcut: M";
  }

  // ── Mute ──

  toggleMute() {
    this.userMuted = !this.userMuted;
    if (this.userMuted) {
      this.video.muted = true;
    } else if (!(this.isNight && this.masksEnabled)) {
      // During a night phase (masks on) audio stays off until dawn;
      // the user's unmute then takes effect in _updateNightState
      this.video.muted = false;
      if (this.video.volume === 0) this.video.volume = this.savedVolume || 1;
    }
    this._updateMuteBtn();
    this._persistVolume();
  }

  // Remember the user's volume/mute choice across reloads (user intent only:
  // the night auto-mute is never persisted)
  _persistVolume() {
    try {
      localStorage.setItem(VOLUME_KEY, JSON.stringify({ volume: this.savedVolume, muted: this.userMuted }));
    } catch {}
  }

  _restoreVolume() {
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem(VOLUME_KEY)); } catch {}
    if (!saved || typeof saved.volume !== "number") return;
    this.savedVolume = Math.min(1, Math.max(0, saved.volume)) || 1;
    this.userMuted = !!saved.muted;
    this.video.volume = this.savedVolume;
    this.video.muted = this.userMuted;
    this.volumeSlider.value = this.userMuted ? 0 : this.savedVolume;
    this._updateMuteBtn();
  }

  _updateMuteBtn() {
    this.muteBtn.textContent = this.video.muted ? "🔇" : "🔊";
    this.muteBtn.classList.toggle("active", this.userMuted);
    this.muteBtn.title = this.userMuted ? "Unmute" : "Mute";
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
      case "n":
      case "N": {
        // N = jump to next night start, Shift+N = previous
        e.preventDefault();
        const starts = (this.metadata?.night_phases || []).map((p) => p.start).sort((a, b) => a - b);
        const t = this.video.currentTime;
        const target = e.shiftKey
          ? [...starts].reverse().find((s) => s < t - 1)
          : starts.find((s) => s > t + 1);
        if (target !== undefined) this.video.currentTime = target;
        break;
      }
      case "ArrowLeft":
        e.preventDefault();
        if (isFinite(this.video.duration)) {
          this.video.currentTime = Math.max(0, this.video.currentTime - 5);
        }
        break;
      case "ArrowRight":
        e.preventDefault();
        if (isFinite(this.video.duration)) {
          this.video.currentTime = Math.min(this.video.duration, this.video.currentTime + 5);
        }
        break;
    }
  }
}
