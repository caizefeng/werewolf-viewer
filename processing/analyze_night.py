#!/usr/bin/env python3
"""Detect night phases in werewolf video using bottom-corner ambient light color.

During night phases, the ambient light turns red (LED strips on the table).
This is most clearly visible in the bottom-left and bottom-right corners of
the frame, where the R/G color ratio jumps from ~1.0 (day) to ~4.0 (night).

Algorithm:
1. Scan every 2 seconds: compute max R/G ratio from both bottom corners,
   and frame-to-frame pixel difference
2. Find "red clusters" — consecutive seconds with R/G >= 2.5
3. Merge nearby clusters into night phases, using frame diffs to distinguish
   real day/night transitions (small diff = same scene, lighting change) from
   camera cuts (large diff = different scene, close-up ↔ table view)
4. Filter by minimum duration, add safety buffer
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np


RED_THRESH = 2.5   # R/G ratio indicating red ambient light (night, table view)
ENTRY_BUFFER = 2.0  # seconds the overlay starts before the light turns red
EXIT_BUFFER = 1.0   # seconds the overlay lasts after the light stops being red
REFINE_STEP = 0.25  # seconds; fine-scan resolution for boundary refinement
CUT_THRESH = 40    # frame diff above this = camera cut (not a lighting change)
MIN_PHASE_DURATION = 35  # minimum raw phase duration in seconds (filters false positives)

SCAN_INTERVAL = 2  # seconds between sampled frames


def _compute_rg_ratio(roi):
    """Compute R/G color ratio for a region of interest."""
    mean = roi.mean(axis=(0, 1))
    return mean[2] / (mean[1] + 1)


def _frame_redness(frame):
    """Max R/G ratio over the bottom-left and bottom-right corner ROIs."""
    h, w = frame.shape[:2]
    bl = frame[int(h * 0.88):int(h * 0.93), int(w * 0.02):int(w * 0.12)]
    br = frame[int(h * 0.88):int(h * 0.93), int(w * 0.88):int(w * 0.98)]
    return max(_compute_rg_ratio(bl), _compute_rg_ratio(br))


def _scan_segment(args):
    """Worker function for parallel video scanning.

    Processes a contiguous segment of the video, computing R/G ratios from
    bottom corners and frame-to-frame diffs. Each worker opens its own
    VideoCapture and seeks to its segment start.

    For correct boundary diffs, workers with need_prev=True read one extra
    frame before their segment to use as prev_frame for the first diff.

    A frame-index cursor (pos) keeps every sample at round(sec * fps), so
    sampling stays frame-accurate for fractional frame rates (e.g. 29.97):
    a fixed skip count would drift ~56s/hour at 29.97 fps.
    """
    video_path, start_sec, end_sec, scan_interval, need_prev = args

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)

    prev_frame = None

    # pos = frame index that the next read() will return
    if need_prev and start_sec >= scan_interval:
        # Seek to one interval before segment start, read as prev_frame
        pos = int(round((start_sec - scan_interval) * fps))
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ret, prev_frame = cap.read()
        pos += 1
        if not ret:
            prev_frame = None
    elif start_sec > 0:
        # Seek to segment start (no prev frame needed)
        pos = int(round(start_sec * fps))
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
    else:
        pos = 0

    timestamps = []
    ratios = []
    diffs = []

    for sec in range(start_sec, end_sec, scan_interval):
        # Advance to the exact frame for this timestamp
        target = int(round(sec * fps))
        while pos < target and cap.grab():
            pos += 1
        ret, frame = cap.read()
        if not ret:
            break
        pos += 1
        timestamps.append(sec)
        ratios.append(_frame_redness(frame))

        if prev_frame is not None:
            diffs.append(cv2.absdiff(frame, prev_frame).mean())
        else:
            diffs.append(0.0)
        prev_frame = frame

    cap.release()
    return timestamps, ratios, diffs


def scan_corner_redness(video_path, num_workers=0):
    """Scan at SCAN_INTERVAL: compute max R/G ratio and frame-to-frame diff.

    Returns (timestamps, ratios, diffs) — parallel arrays of sampled points.
    diffs[i] = mean absolute pixel difference between frame i and frame i-1.

    num_workers: 0=auto (3 threads), 1=sequential, N=use N threads.
    Threading is used because cv2 releases the GIL during video decode.
    """
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    duration = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps)
    cap.release()

    if num_workers == 0:
        num_workers = 3  # optimal: diminishing returns beyond 3 threads

    if num_workers == 1:
        return _scan_sequential(video_path, fps, duration)

    # Split video into segments aligned to SCAN_INTERVAL
    total_samples = len(range(0, duration, SCAN_INTERVAL))
    samples_per_worker = (total_samples + num_workers - 1) // num_workers

    segments = []
    for i in range(num_workers):
        start_sample = i * samples_per_worker
        end_sample = min((i + 1) * samples_per_worker, total_samples)
        if start_sample >= total_samples:
            break
        start_sec = start_sample * SCAN_INTERVAL
        end_sec = end_sample * SCAN_INTERVAL
        segments.append((video_path, start_sec, end_sec, SCAN_INTERVAL, i > 0))

    with ThreadPoolExecutor(max_workers=len(segments)) as pool:
        results = list(pool.map(_scan_segment, segments))

    # Concatenate results from all workers
    all_timestamps = []
    all_ratios = []
    all_diffs = []
    for ts, rs, ds in results:
        all_timestamps.extend(ts)
        all_ratios.extend(rs)
        all_diffs.extend(ds)

    print(f"  Sampled {len(all_timestamps)} frames ({duration}s video, "
          f"{SCAN_INTERVAL}s interval, {len(segments)} workers)")
    return np.array(all_timestamps), np.array(all_ratios), np.array(all_diffs)


def _scan_sequential(video_path, fps, duration):
    """Original sequential scanning (used when num_workers=1)."""
    cap = cv2.VideoCapture(video_path)
    timestamps = []
    ratios = []
    diffs = []
    prev_frame = None
    pos = 0  # frame index of the next read; frame-accurate for fractional fps

    for sec in range(0, duration, SCAN_INTERVAL):
        target = int(round(sec * fps))
        while pos < target and cap.grab():
            pos += 1
        ret, frame = cap.read()
        if not ret:
            break
        pos += 1
        timestamps.append(sec)
        ratios.append(_frame_redness(frame))

        if prev_frame is not None:
            diffs.append(cv2.absdiff(frame, prev_frame).mean())
        else:
            diffs.append(0.0)
        prev_frame = frame

    cap.release()
    print(f"  Sampled {len(timestamps)} frames ({duration}s video, {SCAN_INTERVAL}s interval)")
    return np.array(timestamps), np.array(ratios), np.array(diffs)


def find_red_clusters(timestamps, ratios, threshold=RED_THRESH, max_internal_gap=5):
    """Find clusters of consecutive red samples (allowing brief gaps).

    max_internal_gap is in real seconds (not sample indices).
    Returns list of (start_sec, end_sec) tuples.
    """
    red_mask = ratios >= threshold
    red_times = timestamps[red_mask]
    if len(red_times) == 0:
        return []

    clusters = []
    cs = ce = int(red_times[0])
    for t in red_times[1:]:
        t = int(t)
        if t - ce <= max_internal_gap + SCAN_INTERVAL:
            ce = t
        else:
            clusters.append((cs, ce))
            cs = ce = t
    clusters.append((cs, ce))
    return clusters


CUT_WINDOW = 3  # samples to check around each boundary for camera cuts


def _max_diff_in_window(diffs, center_idx, half_window=CUT_WINDOW // 2):
    """Return max frame diff within a window around center_idx."""
    lo = max(0, center_idx - half_window)
    hi = min(len(diffs), center_idx + half_window + 1)
    return max(diffs[lo:hi]) if hi > lo else 0


GAP_RED_THRESH = 1.3  # R/G ratio threshold for "elevated" (close-up shots during night)
GAP_ELEVATED_FRACTION = 0.6  # fraction of gap samples that must be elevated to merge
GAP_MIN_FLOOR = 1.05  # minimum R/G in gap — below this means genuine daytime (blocks merge)
MAX_MERGE_GAP = 100   # max gap duration (seconds) for ratio-based merging
# Max gap (seconds) that may be bridged on day-evidence grounds: two red
# bursts with no sidebar sighting between them are the same night. Newer
# seasons (S23) cut away from the red table for over a minute at a time
# (wolf close-ups, the night graphic), which fragments a night into bursts
# that neither the camera-cut nor the ratio rule can reconnect.
MAX_EVIDENCE_GAP = 300
# A red burst must be at least this long (seconds) to take part in
# evidence-based merging. Shorter flashes (a red costume in a close-up
# hitting the corner ROI for one sample) must neither extend a night nor
# break a chain of real bursts.
MIN_EVIDENCE_FRAGMENT = 6


def merge_clusters(clusters, timestamps, ratios, diffs, cut_thresh=CUT_THRESH):
    """Merge clusters whose boundaries are camera cuts (not real lighting changes),
    or whose gap still has elevated R/G ratios (night never ended, just close-ups).

    Uses frame-to-frame pixel difference to distinguish:
    - Camera cuts (large diff): close-up ↔ table view during same night → merge
    - Real transitions (small diff): actual lighting change → keep separate

    At each cluster boundary, check if the transition is a camera cut by
    looking at max diff in a window of CUT_WINDOW samples around the
    boundary.  A camera cut can land a few samples before or after the
    red/non-red threshold crossing (e.g. on a borderline frame just
    inside the cluster).  If BOTH the exit and entry are camera cuts,
    the gap is close-ups during an ongoing night → merge.

    Also merges when enough of the gap has elevated R/G ratios (≥ GAP_RED_THRESH),
    indicating the camera is on close-up shots during an ongoing night.
    Close-up R/G (~1.5-2.1) is clearly above daytime (~1.0-1.2).
    Uses a fraction-based check (GAP_ELEVATED_FRACTION) to tolerate occasional
    brief dips below threshold during close-ups, with a floor check (GAP_MIN_FLOOR)
    to reject gaps that contain genuine daytime samples (R/G < 1.05).
    """
    if not clusters:
        return []

    merged = [clusters[0]]
    for cs, ce in clusters[1:]:
        prev_end = merged[-1][1]
        exit_idx = np.searchsorted(timestamps, prev_end, side='right')
        exit_diff = _max_diff_in_window(diffs, exit_idx)

        entry_idx = np.searchsorted(timestamps, cs, side='left')
        entry_diff = _max_diff_in_window(diffs, entry_idx)

        # Both transitions are camera cuts → gap is close-ups during night
        if exit_diff >= cut_thresh and entry_diff >= cut_thresh:
            merged[-1] = (merged[-1][0], ce)
            continue

        # Gap with elevated R/G ratios → close-up shots during night
        gap_duration = cs - prev_end
        if gap_duration <= MAX_MERGE_GAP and exit_idx < entry_idx:
            gap_ratios = ratios[exit_idx:entry_idx]
            if len(gap_ratios) > 0:
                elevated_frac = np.mean(gap_ratios >= GAP_RED_THRESH)
                if (elevated_frac >= GAP_ELEVATED_FRACTION
                        and gap_ratios.min() >= GAP_MIN_FLOOR):
                    merged[-1] = (merged[-1][0], ce)
                    continue

        # Real gap → keep separate
        merged.append((cs, ce))
    return merged


def merge_by_day_evidence(phases, gap_is_night, min_fragment=MIN_EVIDENCE_FRAGMENT):
    """Second merge pass: join consecutive substantial phases whose gap (at
    most MAX_EVIDENCE_GAP) contains no day evidence, i.e. the sidebar was
    never seen between them.

    Only phases at least min_fragment long take part: a stray one-sample
    flash neither extends a night nor interrupts a chain of real bursts
    (it is skipped and later dropped by the minimum-duration filter).
    """
    if gap_is_night is None or len(phases) < 2:
        return phases
    out = []
    last = None  # index in out of the last substantial phase
    for s, e in phases:
        if e - s < min_fragment:
            out.append((s, e))
            continue
        if last is not None:
            ps, pe = out[last]
            gap = s - pe
            if 0 < gap <= MAX_EVIDENCE_GAP and gap_is_night(pe, s):
                out[last] = (ps, e)
                # tiny phases that now fall inside the merged span are absorbed
                out = out[:last + 1] + [q for q in out[last + 1:] if not (ps <= q[0] and q[1] <= e)]
                continue
        out.append((s, e))
        last = len(out) - 1
    return sorted(out)


def _make_gap_checker(video_path, clusters):
    """Lazy day-evidence checker for merge_clusters, or None when no gap
    between clusters is short enough to qualify (then no OCR is loaded)."""
    gaps = [cs - pe for (_, pe), (cs, _) in zip(clusters, clusters[1:])]
    if not any(0 < g <= MAX_EVIDENCE_GAP for g in gaps):
        return None
    state = {}

    def gap_is_night(t0, t1):
        if "ocr" not in state:
            from analyze_names import _init_ocr, day_evidence_in
            print("  Checking cluster gaps for day evidence (sidebar OCR)...")
            state["ocr"] = _init_ocr()
            state["fn"] = day_evidence_in
            state["cap"] = cv2.VideoCapture(video_path)
            state["fps"] = state["cap"].get(cv2.CAP_PROP_FPS)
        return not state["fn"](state["ocr"], state["cap"], state["fps"], t0, t1)

    return gap_is_night


def filter_cut_bounded_phases(phases, timestamps, diffs, cut_thresh=CUT_THRESH):
    """Remove phases whose outer entry AND exit are both camera cuts.

    A real night phase starts and ends with gradual lighting changes
    (small diff, same scene).  If BOTH boundaries are camera cuts, the
    "night" is just the camera briefly showing a red-lit scene — not a
    real day/night transition.
    """
    result = []
    for s, e in phases:
        entry_idx = np.searchsorted(timestamps, s, side='left')
        entry_diff = _max_diff_in_window(diffs, entry_idx)

        exit_idx = np.searchsorted(timestamps, e, side='right')
        exit_diff = _max_diff_in_window(diffs, exit_idx)

        if entry_diff >= cut_thresh and exit_diff >= cut_thresh:
            continue  # both boundaries are camera cuts → FP
        result.append((s, e))
    return result


def _scan_window(cap, fps, t0, t1, step=REFINE_STEP):
    """Yield (t, redness) for t in [t0, t1) at `step` resolution.

    Seeks once, then decodes sequentially (a seek per sample would decode
    from the previous keyframe every time).
    """
    pos = int(round(t0 * fps))
    cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
    for k in range(int(round((t1 - t0) / step))):
        t = t0 + k * step
        target = int(round(t * fps))
        while pos < target and cap.grab():
            pos += 1
        ret, frame = cap.read()
        if not ret:
            return
        pos += 1
        yield t, _frame_redness(frame)


def refine_boundaries(video_path, phases, threshold=RED_THRESH):
    """Locate each phase's exact red-on / red-off time.

    The coarse scan samples every SCAN_INTERVAL seconds, so a raw boundary
    is only known to within one interval: the light turned red somewhere
    in (start - 2*SCAN_INTERVAL, start] (two intervals: see below) and
    stopped being red somewhere in [end, end + SCAN_INTERVAL). Re-scan
    those windows at REFINE_STEP so the
    buffers apply to the real transition instead of the sample grid (which
    made the overlay lead vary between ~1s and ~4s).
    """
    if not phases:
        return phases
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    refined = []
    for s, e in phases:
        # Entry: look back two intervals, not one. A brief camera cut can
        # land exactly on the first red grid sample after the light comes
        # on, which pushes the cluster start one interval late; the real
        # red-on is then just before the (non-red) previous grid sample.
        on = float(s)
        for t, r in _scan_window(cap, fps, max(0.0, s - 2 * SCAN_INTERVAL + REFINE_STEP), s):
            if r >= threshold:
                on = t
                break
        off = float(e)
        for t, r in _scan_window(cap, fps, e + REFINE_STEP, e + SCAN_INTERVAL):
            if r < threshold:
                break
            off = t
        refined.append((on, off))
    cap.release()
    return refined


def analyze_night_phases(video_path, num_workers=0):
    """Detect night phases via bottom-corner ambient light color.

    num_workers: 0=auto, 1=sequential, N=use N workers for frame scanning.
    """
    print("Scanning bottom corners for ambient light changes...")
    timestamps, ratios, diffs = scan_corner_redness(video_path, num_workers)

    if len(timestamps) == 0:
        print("No frames scanned.")
        return []

    duration = int(timestamps[-1]) + SCAN_INTERVAL

    clusters = find_red_clusters(timestamps, ratios)
    print(f"  Found {len(clusters)} red cluster(s)")

    phases = merge_clusters(clusters, timestamps, ratios, diffs)
    phases = merge_by_day_evidence(phases, _make_gap_checker(video_path, clusters))

    # Filter phases bounded by camera cuts on both sides (not real transitions).
    # A phase assembled from several red bursts is a real night whose outer
    # bursts happen to begin/end on cuts, so it is exempt.
    def _n_clusters(s, e):
        return sum(1 for cs, ce in clusters if cs >= s and ce <= e)
    multi = [(s, e) for s, e in phases if _n_clusters(s, e) >= 3]
    single = [(s, e) for s, e in phases if _n_clusters(s, e) < 3]
    phases = sorted(filter_cut_bounded_phases(single, timestamps, diffs) + multi)

    # Filter by minimum duration
    phases = [(s, e) for s, e in phases if e - s >= MIN_PHASE_DURATION]

    # Filter phases starting at the very beginning (intro red lighting, not real night)
    phases = [(s, e) for s, e in phases if s > 0]

    # Pin each boundary to the actual light transition, then add buffers
    phases = refine_boundaries(video_path, phases)
    results = []
    for s, e in phases:
        results.append({
            "start": round(max(0, s - ENTRY_BUFFER), 2),
            "end": round(min(duration - 1, e + EXIT_BUFFER), 2),
        })

    print(f"Found {len(results)} night phase(s)")
    for p in results:
        s, e = p["start"], p["end"]
        dur = e - s
        def _fmt(t):
            m, sec = divmod(int(t), 60)
            h, m = divmod(m, 60)
            return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"
        print(f"  {_fmt(s)} - {_fmt(e)} ({dur:.0f}s)")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Detect night phases in werewolf video")
    parser.add_argument("video_path", help="Path to video file")
    parser.add_argument("--workers", type=int, default=0,
                        help="Number of parallel workers (0=auto, 1=sequential)")
    args = parser.parse_args()

    phases = analyze_night_phases(args.video_path, num_workers=args.workers)
    print(json.dumps(phases, indent=2, ensure_ascii=False))
