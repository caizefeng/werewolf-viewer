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
import os
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np


RED_THRESH = 2.5   # R/G ratio indicating red ambient light (night, table view)
ENTRY_BUFFER = 3.5  # seconds of buffer before night entry
EXIT_BUFFER = 2     # seconds of buffer after night exit
CUT_THRESH = 40    # frame diff above this = camera cut (not a lighting change)
MIN_PHASE_DURATION = 35  # minimum raw phase duration in seconds (filters false positives)

SCAN_INTERVAL = 2  # seconds between sampled frames


def _compute_rg_ratio(roi):
    """Compute R/G color ratio for a region of interest."""
    mean = roi.mean(axis=(0, 1))
    return mean[2] / (mean[1] + 1)


def _scan_segment(args):
    """Worker function for parallel video scanning.

    Processes a contiguous segment of the video, computing R/G ratios from
    bottom corners and frame-to-frame diffs. Each worker opens its own
    VideoCapture and seeks to its segment start.

    For correct boundary diffs, workers with need_prev=True read one extra
    frame before their segment to use as prev_frame for the first diff.
    """
    video_path, start_sec, end_sec, scan_interval, need_prev = args

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    skip = int(scan_interval * fps) - 1

    prev_frame = None

    if need_prev and start_sec >= scan_interval:
        # Seek to one interval before segment start, read as prev_frame
        prev_sec = start_sec - scan_interval
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(prev_sec * fps))
        ret, prev_frame = cap.read()
        if not ret:
            prev_frame = None
        # Advance to segment start
        for _ in range(skip):
            cap.grab()
    elif start_sec > 0:
        # Seek to segment start (no prev frame needed)
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(start_sec * fps))

    timestamps = []
    ratios = []
    diffs = []

    for sec in range(start_sec, end_sec, scan_interval):
        ret, frame = cap.read()
        if not ret:
            break
        h, w = frame.shape[:2]
        bl = frame[int(h * 0.88):int(h * 0.93), int(w * 0.02):int(w * 0.12)]
        br = frame[int(h * 0.88):int(h * 0.93), int(w * 0.88):int(w * 0.98)]
        rg_bl = _compute_rg_ratio(bl)
        rg_br = _compute_rg_ratio(br)
        timestamps.append(sec)
        ratios.append(max(rg_bl, rg_br))

        if prev_frame is not None:
            diffs.append(cv2.absdiff(frame, prev_frame).mean())
        else:
            diffs.append(0.0)
        prev_frame = frame

        # Skip frames until next sample
        for _ in range(skip):
            cap.grab()

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
    skip = int(SCAN_INTERVAL * fps) - 1

    for sec in range(0, duration, SCAN_INTERVAL):
        ret, frame = cap.read()
        if not ret:
            break
        h, w = frame.shape[:2]
        bl = frame[int(h * 0.88):int(h * 0.93), int(w * 0.02):int(w * 0.12)]
        br = frame[int(h * 0.88):int(h * 0.93), int(w * 0.88):int(w * 0.98)]
        rg_bl = _compute_rg_ratio(bl)
        rg_br = _compute_rg_ratio(br)
        timestamps.append(sec)
        ratios.append(max(rg_bl, rg_br))

        if prev_frame is not None:
            diffs.append(cv2.absdiff(frame, prev_frame).mean())
        else:
            diffs.append(0.0)
        prev_frame = frame

        for _ in range(skip):
            cap.grab()

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

    # Filter phases bounded by camera cuts on both sides (not real transitions)
    phases = filter_cut_bounded_phases(phases, timestamps, diffs)

    # Filter by minimum duration
    phases = [(s, e) for s, e in phases if e - s >= MIN_PHASE_DURATION]

    # Filter phases starting at the very beginning (intro red lighting, not real night)
    phases = [(s, e) for s, e in phases if s > 0]

    # Add buffer to each boundary
    results = []
    for s, e in phases:
        results.append({
            "start": max(0, int(s - ENTRY_BUFFER)),
            "end": min(duration - 1, int(e + EXIT_BUFFER)),
        })

    print(f"Found {len(results)} night phase(s)")
    for p in results:
        s, e = p["start"], p["end"]
        dur = e - s
        def _fmt(t):
            m, sec = divmod(t, 60)
            h, m = divmod(m, 60)
            return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"
        print(f"  {_fmt(s)} - {_fmt(e)} ({dur}s)")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Detect night phases in werewolf video")
    parser.add_argument("video_path", help="Path to video file")
    parser.add_argument("--workers", type=int, default=0,
                        help="Number of parallel workers (0=auto, 1=sequential)")
    args = parser.parse_args()

    phases = analyze_night_phases(args.video_path, num_workers=args.workers)
    print(json.dumps(phases, indent=2, ensure_ascii=False))
