#!/usr/bin/env python3
"""Detect the card-viewing phase (看牌): players look at their role cards
right before the first night.

What it looks like (studied 2026-10-25 on S21-S23 games, open and
hidden-role broadcasts alike): after the pre-game (commentators, player
introductions) the director tours the twelve seats in order, 1 -> 12 or
12 -> 1, while each player checks their card. That is 35-55 s of seat
close-ups joined by fast camera pans, then a cut to the table wide shot as
the first night falls. Nothing on screen labels it, and the tablecloth behind
some seats is red, so the night detector's red light can't tell the tour from
the night (S22 first nights used to start 10-40 s early, inside the tour).

Camera motion is what sets the tour apart: the commentators, the
introductions and the night table shot hold still, and the few other moving
stretches before the first day are slow drifts rather than seat-to-seat
pans. Detection:
1. Coarse: the night scan's motion samples (32x18 thumbnail change over
   0.25 s, every 2 s). Runs of fast-moving samples are tour candidates.
2. Fine: around each candidate, sample every 0.5 s (pairs 0.25 s apart),
   split into shots, and grow the run over short shots until a long static
   shot on each side (commentators before, the table after).
3. Accept runs whose length and pan density look like a seat tour.
A broadcast can deal twice (a game restarted before day 1: S21E05 G2, S23E24
G2 and G3), so a later candidate is kept too as long as no day lies between,
i.e. the player sidebar does not show just before it.

Since S23E28 (2026-10-27) the broadcast shows the card viewing differently:
four fixed cameras, three seats each, as a 2x2 split screen for ~22 s while all
twelve players check their cards at once, then a cut to the night's table.
Nothing moves, so the tour search finds nothing; when it finds no tour, the
split screen is looked for instead (see GRID_*). A hidden-roles broadcast in
that format (S23E29 G3, 2026-10-28) cuts from the split screen straight back to
the commentators, who cover the whole first night, so no red light follows it.
"""

import cv2
import numpy as np

from analyze_night import (DAWN_SEARCH_TO, REFINE_STEP, RED_THRESH, SCAN_INTERVAL, _cover_span,
                           _frame_redness, _frames, _thumb)


CARD_COARSE = 12        # coarse: a 2 s sample "moves" above this (0-255 thumbnail change)
CARD_BRIDGE = 12        # s; still stretches inside the tour (held close-ups, S21 holds longer)
CARD_MIN_CORE = 16      # s; shortest run of moving coarse samples worth a fine scan
CARD_MOTION = 15        # fine: a sample moves (pan or cut) above this
CARD_LONG_SHOT = 15     # s; a shot this long ends the tour on that side
CARD_CUT = 25           # fine: thumbnail change over 0.5 s that counts as a cut or a pan step
CARD_MIN_LEN = 25       # s; accepted tour length range
CARD_MAX_LEN = 80
CARD_MIN_FAST = 0.30    # share of 0.5 s steps inside the tour that are cuts / pan steps
CARD_MIN_BUSY = 0.30    # share of samples inside the tour that move
# A slower tour (S21 holds each seat longer) is accepted at these lower
# densities when the night's red light comes on within CARD_RED_WITHIN of its end
CARD_LOOSE_FAST = 0.15
CARD_LOOSE_BUSY = 0.20
CARD_RED_WITHIN = 30
CARD_SEARCH_END = 2700  # s; tours later than this are not looked for (pre-games run 5-20 min)
CARD_MAX_SCANS = 6      # fine scans at most (each decodes ~2-3 min of video)
CARD_REDEAL_WITHIN = 900  # s; a second deal comes this soon after the first tour (seen: 5.7-9.6 min)
FINE_STEP = 0.5
FINE_PAIR = 0.25
FINE_MARGIN = 60        # s of context scanned on each side of a core
NOT_RED = 1.8           # corner R/G clearly below the night light (RED_THRESH)
SAME_SET = 15           # mean thumbnail difference below which two shots show the same set
NIGHT_SHOT_WINDOW = 15  # s; the night's table shot starts this close to the return to that set
# Split screen (S23E28 on). Its seams lie exactly on the frame's centre lines,
# which are also block edges of the scan's 32x18 thumbnails (60 px at 1080p).
# Night shows use 2x2 grids too (the wolves: S21 F2J0QK_3gUo, S22
# d3jNiPSqMuI), so only a grid before the first night's red light counts
GRID_COARSE = 1.6       # thumbnail: horizontal centre line vs the lines beside it (card grids 2.4-6.8)
GRID_MIN_CORE = 10      # s; shortest run of such coarse samples (the card grids last 21-24 s)
GRID_SEAM = 3.0         # full frame: weakest half seam (card grids >= 3.7, three-panel layouts <= 2.8)
# A frame is past the grid's cut below this: single pictures score under 1,
# while the grid keeps 2.7+ as the studio dims for nightfall (S23E28 G1)
GRID_EDGE_SEAM = 1.5
GRID_NIGHT_RUN = 6      # s; red light this long before a grid means a night has begun
GRID_EDGE_SEARCH = 12   # s; how far past the coarse run its cuts are looked for
# The night after a grid shows as its red light, or in a hidden-roles
# broadcast as the commentators covering it (analyze_night._cover_span). A
# covered grid counts only when the player sidebar then shows within
# GRID_DAY_WITHIN of the commentators leaving, as day 1 begins (25-50 s after
# the covered first nights of seven hidden-roles games, S22-S23); a pre-game
# grid between two commentator shots would not have that
GRID_DAY_WITHIN = 120   # s
GRID_DAY_STEP = 30      # s between those sidebar checks


def coarse_cores(timestamps, motions, motion=CARD_COARSE, bridge=CARD_BRIDGE,
                 min_core=CARD_MIN_CORE, t_max=CARD_SEARCH_END):
    """Runs of moving coarse samples (gaps up to `bridge` s), at least
    `min_core` s long, starting before t_max. Returns [(t0, t1)]."""
    out = []
    s = last = None
    for t, m in zip(timestamps, motions):
        if m < motion:
            continue
        if s is not None and t - last > bridge:
            out.append((s, last))
            s = None
        if s is None:
            # No run starts past t_max (until 2026-10-27 this held only before
            # the first run, so a game without a tour had candidates
            # fine-scanned all through it, up to CARD_MAX_SCANS of them)
            if t > t_max:
                break
            s = t
        last = t
    if s is not None:
        out.append((s, last))
    return [(float(a), float(b)) for a, b in out if b - a >= min_core]


def fine_scan(cap, fps, t0, t1):
    """Samples every FINE_STEP in [t0, t1]: (times, motion, change, redness,
    thumbs). motion = thumbnail change over FINE_PAIR after the sample;
    change = over FINE_STEP before it (a cut or a pan step); redness =
    corner R/G; thumbs = the samples' 32x18 grey thumbnails."""
    t0 = max(0.0, t0)
    want = {}
    t = t0
    while t <= t1:
        want.setdefault(int(round(t * fps)), []).append(("a", t))
        want.setdefault(int(round((t + FINE_PAIR) * fps)), []).append(("b", t))
        t = round(t + FINE_STEP, 3)
    first, last = min(want), max(want)
    cap.set(cv2.CAP_PROP_POS_FRAMES, first)
    pos = first
    a, b, red = {}, {}, {}
    while pos <= last:
        if pos in want:
            ok, frame = cap.read()
            if not ok:
                break
            th = _thumb(frame)
            for role, t in want[pos]:
                if role == "a":
                    a[t] = th
                    red[t] = _frame_redness(frame)
                else:
                    b[t] = th
        elif not cap.grab():
            break
        pos += 1
    times = sorted(t for t in a if t in b)
    if not times:
        return np.array([]), np.array([]), np.array([]), np.array([]), np.zeros((0, 18, 32))
    motion = np.array([np.abs(b[t] - a[t]).mean() for t in times])
    change = np.array([0.0] + [np.abs(a[u] - a[t]).mean() for t, u in zip(times, times[1:])])
    return (np.array(times), motion, change, np.array([red[t] for t in times]),
            np.array([a[t] for t in times]))


def shots_from(times, change, cut=CARD_CUT):
    """[(start, duration)] split at every sample whose change exceeds `cut`
    (the cut happened in the FINE_STEP before it)."""
    if len(times) == 0:
        return []
    starts = [times[0]] + [t for t, c in zip(times[1:], change[1:]) if c > cut]
    ends = starts[1:] + [times[-1] + FINE_STEP]
    return [(float(s), float(e - s)) for s, e in zip(starts, ends)]


def _night_shot(sh, i, j, after_core, times, motion, redness, thumbs):
    """Index of the night's table shot among the tour's trailing shots, or
    None. Hidden-roles broadcasts show the table for only a few seconds
    before cutting to the commentators, so it is short enough to pass for one
    more seat close-up. It is
    (1) the first still shot after the core (after_core..j) in which the red
        light comes on, or
    (2) when the broadcast then returns to the very set it left for the tour
        (the long shots on both sides look alike), the last still red shot
        starting within NIGHT_SHOT_WINDOW of that return (a transition
        animation may come between; the core itself can reach into the
        table shot).
    "Still" allows a moving sample or two: the light coming on is itself a
    big change between samples. (1) is not searched inside the core: seat
    close-ups settling on the red tablecloth after a pan look the same."""
    def samples(k):
        s, d = sh[k]
        return (times >= s) & (times < s + d)

    def still(k):
        return (motion[samples(k)] >= CARD_MOTION).mean() <= 0.25

    for k in range(after_core, j + 1):
        red = redness[samples(k)]
        if still(k) and len(red) and red[0] < NOT_RED and red.max() >= RED_THRESH:
            return k
    if i == 0 or j + 1 >= len(sh):
        return None
    bs, bd = sh[i - 1]
    before = (times >= max(bs, bs + bd - 4)) & (times < bs + bd - FINE_STEP)
    as_, ad = sh[j + 1]
    after = (times > as_) & (times < as_ + min(ad, 4))
    if not before.any() or not after.any():
        return None
    if np.abs(thumbs[before].mean(axis=0) - thumbs[after].mean(axis=0)).mean() >= SAME_SET:
        return None
    for k in range(j, i, -1):
        if sh[k][0] < as_ - NIGHT_SHOT_WINDOW:
            break
        red = redness[samples(k)]
        if still(k) and len(red) and np.median(red) >= RED_THRESH:
            return k
    return None


def grow_tour(core, times, motion, change, redness, thumbs):
    """Grow a coarse core over the short shots around it to the long shot on
    each side. Returns a dict of tour statistics, or None. `open_start` /
    `open_end` flag a run that reached the scanned window's edge."""
    a, b = core
    sh = shots_from(times, change)
    # Shots within the core. The core's first coarse sample often straddles
    # the cut into the tour (its motion pair spans it), so the shot before
    # must overlap the core by more than that sliver to count
    inside = [k for k, (s, d) in enumerate(sh) if s + d > a + 1.0 and s <= b]
    if not inside:
        return None
    i, j = inside[0], inside[-1]
    while i > 0 and sh[i - 1][1] < CARD_LONG_SHOT:
        i -= 1
    while j + 1 < len(sh) and sh[j + 1][1] < CARD_LONG_SHOT:
        j += 1
    night = _night_shot(sh, i, j, inside[-1] + 1, times, motion, redness, thumbs)
    if night is not None:
        j = night - 1
    start = sh[i][0]
    end = sh[j + 1][0] if j + 1 < len(sh) else sh[j][0] + sh[j][1]
    m = (times >= start) & (times < end)
    if not m.any():
        return None
    # A shot starts at the first sample after its cut, which happened within
    # the FINE_STEP before: report the middle of that step
    return {
        "start": round(max(0.0, start - FINE_STEP / 2), 2), "end": round(end - FINE_STEP / 2, 2),
        "length": round(end - start, 2),
        "fast": round(float((change[m] > CARD_CUT).mean()), 3),
        "busy": round(float((motion[m] >= CARD_MOTION).mean()), 3),
        "before": round(sh[i - 1][1], 1) if i > 0 else 0.0,
        "after": round(sh[j + 1][1], 1) if j + 1 < len(sh) else 0.0,
        "open_start": i == 0, "open_end": j + 1 >= len(sh),
    }


def is_tour(stats, red_follows=False):
    """Does a grown run look like the seat tour? red_follows: the red night
    light comes on within CARD_RED_WITHIN after it."""
    if stats is None or not CARD_MIN_LEN <= stats["length"] <= CARD_MAX_LEN:
        return False
    if stats["fast"] >= CARD_MIN_FAST and stats["busy"] >= CARD_MIN_BUSY:
        return True
    return red_follows and stats["fast"] >= CARD_LOOSE_FAST and stats["busy"] >= CARD_LOOSE_BUSY


def red_after(timestamps, ratios, t, within=CARD_RED_WITHIN):
    """Any red-light sample in (t - 2, t + within]?"""
    m = (timestamps > t - 2) & (timestamps <= t + within)
    return bool((ratios[m] >= RED_THRESH).any())


def scan_core(cap, fps, core):
    """Fine-scan around a coarse core (widening once if the tour runs to the
    window's edge) and return its tour statistics, or None."""
    lo, hi = core[0] - FINE_MARGIN, core[1] + FINE_MARGIN
    for _ in range(2):
        times, motion, change, redness, thumbs = fine_scan(cap, fps, lo, hi)
        stats = grow_tour(core, times, motion, change, redness, thumbs)
        if stats is None:
            return None
        widen_lo = stats["open_start"] and lo > 0
        if not widen_lo and not stats["open_end"]:
            return stats
        lo -= FINE_MARGIN if widen_lo else 0
        hi += FINE_MARGIN if stats["open_end"] else 0
    return stats


def centre_lines(thumbs):
    """Per scan thumbnail (32x18 colour): how sharply it splits at its
    horizontal centre line, the contrast across that line over the contrast
    across the lines beside it, the weaker of the left and right halves."""
    t = np.asarray(thumbs, dtype=np.float32)
    rows = np.abs(t[:, 1:] - t[:, :-1]).mean(axis=3)      # [:, r]: across the line below row r
    halves = [rows[:, 8, s].mean(axis=1) / (rows[:, [6, 7, 9, 10], s].mean(axis=(1, 2)) + 1)
              for s in (slice(0, 16), slice(16, 32))]
    return np.minimum(*halves)


def grid_seams(frame):
    """How clearly a frame is a 2x2 grid of four pictures: the weakest of its
    four half seams (upper / lower half of the vertical centre line, left /
    right half of the horizontal one), each the median step across the seam
    over the median step 3-8 px beside it. Four pictures meet in a seam one
    pixel wide; a single picture scores under 1."""
    h, w = frame.shape[:2]
    cx, cy = w // 2, h // 2
    worst = np.inf
    for band, split in ((frame[:, cx - 8:cx + 8], cy), (frame[cy - 8:cy + 8].transpose(1, 0, 2), cx)):
        steps = np.abs(np.diff(band.astype(np.int16).sum(axis=2), axis=1))  # [:, 7]: across the centre line
        for half in (steps[:split], steps[split:]):
            med = np.median(half, axis=0)
            beside = np.median(np.concatenate([med[:4], med[11:]]))
            worst = min(worst, med[6:9].max() / (beside + 2.0))
    return float(worst)


def night_before(timestamps, ratios, t, run=GRID_NIGHT_RUN):
    """Was the red night light on for `run` s at a stretch before t?"""
    start = None
    for u, r in zip(timestamps, ratios):
        if u >= t:
            break
        if r < RED_THRESH:
            start = None
        elif start is None:
            start = u
        elif u - start >= run:
            return True
    return False


def _frame_at(cap, fps, t):
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * fps)))
    ok, frame = cap.read()
    return frame if ok else None


def _grid_edge(cap, fps, t, direction):
    """The cut into (direction -1) or out of (+1) the grid showing at t: the
    middle of the step between the last grid frame and the first frame past
    it, looked for at REFINE_STEP up to GRID_EDGE_SEARCH s away (t if none)."""
    for k in range(int(GRID_EDGE_SEARCH / SCAN_INTERVAL)):
        if direction < 0:
            lo, hi = max(0.0, t - (k + 1) * SCAN_INTERVAL), t - k * SCAN_INTERVAL
        else:
            lo, hi = t + k * SCAN_INTERVAL + REFINE_STEP, t + (k + 1) * SCAN_INTERVAL + REFINE_STEP
        if hi <= lo:
            break
        other = [u for u, frame in _frames(cap, fps, lo, hi) if grid_seams(frame) < GRID_EDGE_SEAM]
        if other:
            return max(other) + REFINE_STEP / 2 if direction < 0 else min(other) - REFINE_STEP / 2
    return t


def _day_before(sidebar_at, t):
    """Is the player sidebar (daytime) up 3 s or 33 s before t?"""
    return sidebar_at(t - 3) or sidebar_at(t - 33)


def find_grid(cap, fps, timestamps, thumbs, ratios, sidebar_at=None):
    """The split-screen card viewing as [(start, end)], or []: the first 2x2
    grid (a run of coarse samples split at the horizontal centre line, then
    all four seams checked on full frames) before any night light, outside
    daytime and followed by the night: its red light within CARD_RED_WITHIN,
    or the commentators covering it until day 1 (see GRID_DAY_WITHIN)."""
    runs = coarse_cores(timestamps, centre_lines(thumbs), motion=GRID_COARSE,
                        bridge=2 * SCAN_INTERVAL, min_core=GRID_MIN_CORE)
    checks = 0
    for a, b in runs:
        if night_before(timestamps, ratios, a):
            break                       # the first night has begun: later grids are the wolves'
        cover = None
        if not red_after(timestamps, ratios, b):
            cover = _cover_span(timestamps, thumbs, a, b, b + DAWN_SEARCH_TO)
            if cover is None:
                continue                # no night follows
        if checks >= CARD_MAX_SCANS:
            break
        checks += 1
        probes = [_frame_at(cap, fps, a + (b - a) * f) for f in (0.25, 0.5, 0.75)]
        if sum(p is not None and grid_seams(p) >= GRID_SEAM for p in probes) < 2:
            continue                    # not four pictures (e.g. a three-panel layout)
        start, end = _grid_edge(cap, fps, a, -1), _grid_edge(cap, fps, b, +1)
        head = f"  Split-screen candidate {_fmt(start)}-{_fmt(end)} ({end - start:.0f}s): "
        if sidebar_at is not None and _day_before(sidebar_at, start):
            print(head + "rejected (the player sidebar is up: daytime)")
            break
        note = ""
        if cover is not None:
            dawn = cover[1] + SCAN_INTERVAL     # the commentators leave within the next sample
            if sidebar_at is not None and not any(
                    sidebar_at(dawn + k * GRID_DAY_STEP) for k in range(1, GRID_DAY_WITHIN // GRID_DAY_STEP + 1)):
                print(head + f"rejected (no red light, and no day after the commentators at {_fmt(dawn)})")
                continue
            note = f" (no red light: the commentators cover the night until {_fmt(dawn)})"
        print(head + "card viewing" + note)
        return [(round(start, 2), round(end, 2))]
    return []


def find_card_phases(video_path, timestamps, motions, ratios, sidebar_at=None, thumbs=None):
    """The card-viewing phases as [(start, end)], earliest first: the seat
    tours, or when there is none the split screen (thumbs: the scan's colour
    thumbnails; a broadcast restarted in that format would show a second grid,
    not seen yet, so only the first is taken).

    timestamps / motions / ratios: the night scan's coarse samples (ratios =
    corner R/G, for the red light after a slow tour). sidebar_at(t) -> bool
    says whether the player sidebar (daytime) is on screen at t: a tour is
    never in daytime (the sidebar up just before it), which matters because
    the night search ignores all red light before the first tour (a false tour
    on day 1 would erase night 1). After the first tour a later one is only a
    re-deal, within CARD_REDEAL_WITHIN and before the first day, so the search
    ends there.
    """
    cores = coarse_cores(timestamps, motions)
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    found = []
    scans = 0
    try:
        for core in cores:
            if scans >= CARD_MAX_SCANS:
                break
            if found and core[0] <= found[-1][1]:
                continue
            if found and (core[0] > found[-1][1] + CARD_REDEAL_WITHIN
                          or sidebar_at is None or _day_before(sidebar_at, core[0])):
                break
            stats = scan_core(cap, fps, core)
            scans += 1
            ok = is_tour(stats, stats is not None and red_after(timestamps, ratios, stats["end"]))
            verdict = "tour" if ok else "rejected"
            if ok and sidebar_at is not None and _day_before(sidebar_at, stats["start"]):
                ok, verdict = False, "rejected (the player sidebar is up: daytime)"
            if stats is not None:
                print(f"  Card-viewing candidate {_fmt(stats['start'])}-{_fmt(stats['end'])} "
                      f"({stats['length']:.0f}s, pans {stats['fast']:.0%}, moving {stats['busy']:.0%}): "
                      f"{verdict}")
            if ok:
                found.append((stats["start"], stats["end"]))
        if not found and thumbs is not None:
            found = find_grid(cap, fps, timestamps, thumbs, ratios, sidebar_at)
    finally:
        cap.release()
    return found


def _fmt(t):
    m, s = divmod(int(t), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
