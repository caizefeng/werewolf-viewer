#!/usr/bin/env python3
"""Benchmark night detection: parallel vs sequential, validate against ground truth."""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from analyze_night import analyze_night_phases

# Ground truth from CLAUDE.md (±2s tolerance)
GROUND_TRUTH = {
    "65R0r19JyYk": [
        (751, 1025), (1781, 1981), (2011, 2163), (3488, 3631),
    ],
    "EC-1bimFjo4": [
        (448, 504), (949, 1130), (1691, 1958), (1995, 2207), (2784, 2914),
    ],
    "-ESYZWvQMH4": [
        (504, 743), (4388, 4579), (6365, 6505), (7752, 7866), (8716, 8756),
    ],
    "ZusP81Ycn-U": [
        (454, 688), (4968, 5231), (5266, 5405), (6290, None),  # last has no exit
    ],
    "ieLaR4NBPz4": [
        (672, 908), (2070, 2328), (2358, 2542),
    ],
    "Xk65eicHSyw": [
        (1004, 1268), (2530, 2760), (4252, 4416), (5358, 5482),
    ],
    "WkVPdddUiio": [
        (366, 592), (3490, 3674), (5468, 5580), (7148, 7250),
    ],
    "F2J0QK_3gUo": [
        (624, 854), (1689, 1880), (1907, 2068), (3570, 3640),
    ],
    "Jnf_dLaVNMU": [
        (704, 914), (2566, 2820),
    ],
    # S23 (cut-heavy nights; boundaries verified frame by frame, day counter cross-checked)
    "xNDz6SStaLo": [   # S23E24 第一局 -- 26s self-destruct day 2 at 63:46 (dawn banner 63:48, night banner 64:14)
        (557, 793), (3638, 3826), (3852, 3955),
    ],
    "QNxo5hmWLN0": [   # S23E24 第二局 (hidden-roles broadcast; overlay off in the viewer) -- 24s self-destruct day at 91:57; dawn banner 94:48
        (423, 586), (5313, 5517), (5541, 5685),
    ],
    "bzsBWNpIwpo": [   # S23E25 第一局 (day 2 lasts only ~5.5 min)
        (670, 900), (3846, 4000), (4339, 4441),
    ],
    "fgw-4eUV0JE": [   # S23E25 第二局
        (381, 624), (4672, 4854),
    ],
    # S23E26 (2026-10-15 broadcasts; phase banners + self-destruct days + a 152s wolves' close-up gap)
    "X5J6PIMh368": [   # S23E26 第一局 预女猎白混 -- game ends on day 1
        (428, 693),
    ],
    "3oifxz_xLr4": [   # S23E26 第二局 假面舞会 -- 28s self-destruct day between the last two
        (435, 676), (2996, 3277), (3305, 3352),
    ],
    "40RdPP2AuMs": [   # S23E26 第三局 机械狼通灵师 -- night 1 has a 152s wolves' discussion gap; 34s self-destruct day at 30:00
        (473, 825), (1581, 1800), (1831, 2013),
    ],
    "CBZfebaxD0E": [   # S23E26 第四局 机械狼通灵师
        (488, 796), (3531, 3715), (4188, 4348),
    ],
}

TOLERANCE = 5  # seconds (ground truth approximate, buffer settings may differ)


def check_results(video_id, phases, ground_truth):
    """Check detected phases against ground truth. Returns (ok, details)."""
    gt = ground_truth
    if len(phases) != len(gt):
        return False, f"Count mismatch: got {len(phases)}, expected {len(gt)}"

    issues = []
    for i, (phase, (gt_start, gt_end)) in enumerate(zip(phases, gt)):
        s, e = phase["start"], phase["end"]
        if abs(s - gt_start) > TOLERANCE:
            issues.append(f"  Phase {i}: start {s} vs expected {gt_start} (diff={s-gt_start})")
        if gt_end is not None and abs(e - gt_end) > TOLERANCE:
            issues.append(f"  Phase {i}: end {e} vs expected {gt_end} (diff={e-gt_end})")

    if issues:
        return False, "\n".join(issues)
    return True, "All phases match"


def benchmark_video(video_id, video_path):
    """Run sequential and parallel, compare results and timing."""
    print(f"\n{'='*60}")
    print(f"Video: {video_id}")
    print(f"{'='*60}")

    # Sequential (workers=1)
    print("\n--- Sequential (workers=1) ---")
    t0 = time.time()
    seq_phases = analyze_night_phases(video_path, num_workers=1)
    seq_time = time.time() - t0
    print(f"Time: {seq_time:.1f}s")

    # Parallel (auto workers)
    print("\n--- Parallel (auto workers) ---")
    t0 = time.time()
    par_phases = analyze_night_phases(video_path, num_workers=0)
    par_time = time.time() - t0
    print(f"Time: {par_time:.1f}s")

    # Compare sequential vs parallel results
    if seq_phases == par_phases:
        print("\nResults: IDENTICAL (sequential == parallel)")
    else:
        print("\nResults: DIFFER!")
        print(f"  Sequential: {seq_phases}")
        print(f"  Parallel:   {par_phases}")

    # Check against ground truth
    gt = GROUND_TRUTH.get(video_id)
    if gt:
        seq_ok, seq_detail = check_results(video_id, seq_phases, gt)
        par_ok, par_detail = check_results(video_id, par_phases, gt)
        print(f"\nGround truth (sequential): {'PASS' if seq_ok else 'FAIL'} - {seq_detail}")
        print(f"Ground truth (parallel):   {'PASS' if par_ok else 'FAIL'} - {par_detail}")
    else:
        print(f"\nNo ground truth for {video_id}")

    speedup = seq_time / par_time if par_time > 0 else 0
    print(f"\nSpeedup: {speedup:.2f}x ({seq_time:.1f}s → {par_time:.1f}s)")

    return {
        "video_id": video_id,
        "seq_time": seq_time,
        "par_time": par_time,
        "speedup": speedup,
        "results_match": seq_phases == par_phases,
        "gt_seq_ok": seq_ok if gt else None,
        "gt_par_ok": par_ok if gt else None,
    }


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    videos_dir = os.path.join(base_dir, "videos")

    # Use specific video IDs if provided, otherwise all ground truth videos
    if len(sys.argv) > 1:
        video_ids = sys.argv[1:]
    else:
        video_ids = list(GROUND_TRUTH.keys())

    results = []
    for vid in video_ids:
        video_path = os.path.join(videos_dir, vid, "video.mp4")
        if not os.path.exists(video_path):
            print(f"\nSkipping {vid}: video not found")
            continue
        results.append(benchmark_video(vid, video_path))

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"{'Video':<20} {'Seq':>7} {'Par':>7} {'Speedup':>8} {'Match':>6} {'GT':>4}")
    print("-" * 60)
    for r in results:
        gt_status = "OK" if r.get("gt_par_ok") else ("FAIL" if r.get("gt_par_ok") is False else "N/A")
        print(f"{r['video_id']:<20} {r['seq_time']:>6.1f}s {r['par_time']:>6.1f}s "
              f"{r['speedup']:>7.2f}x {str(r['results_match']):>6} {gt_status:>4}")

    total_seq = sum(r["seq_time"] for r in results)
    total_par = sum(r["par_time"] for r in results)
    all_match = all(r["results_match"] for r in results)
    all_gt = all(r.get("gt_par_ok") is not False for r in results)
    print("-" * 60)
    print(f"{'TOTAL':<20} {total_seq:>6.1f}s {total_par:>6.1f}s "
          f"{total_seq/total_par if total_par else 0:>7.2f}x {str(all_match):>6} "
          f"{'OK' if all_gt else 'FAIL':>4}")


if __name__ == "__main__":
    main()
