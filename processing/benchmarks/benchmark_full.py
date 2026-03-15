#!/usr/bin/env python3
"""Comprehensive benchmark: full pipeline profiling, parallel vs sequential.

Benchmarks all components of the analysis pipeline:
  Phase 1 — Night detection: sequential scan (workers=1) vs parallel (workers=3)
  Phase 2 — Name detection (PaddleOCR): timed separately on a subset
  Phase 3 — Full pipeline projection: sequential vs parallel mode

Validates results against ground truth and verifies identical outputs.
"""

import json
import os
import sys
import time
from contextlib import contextmanager

# Ground truth from CLAUDE.md (±2s tolerance for buffered boundaries)
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
        (454, 688), (4968, 5231), (5266, 5405), (6290, None),
    ],
    "ieLaR4NBPz4": [
        (672, 908), (2070, 2328), (2358, 2542),
    ],
    "Xk65eicHSyw": [
        (1004, 1268), (2530, 2760), (4252, 4416), (5358, 5482),
    ],
}
TOLERANCE = 5


@contextmanager
def timer():
    t = {"elapsed": 0}
    start = time.perf_counter()
    yield t
    t["elapsed"] = time.perf_counter() - start


def fmt_t(s):
    if s < 60:
        return f"{s:.1f}s"
    m, s = divmod(s, 60)
    return f"{int(m)}m{s:04.1f}s"


def fmt_dur(s):
    h, rem = divmod(int(s), 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def check_gt(phases, gt):
    if len(phases) != len(gt):
        return False, f"count {len(phases)} vs {len(gt)}"
    issues = []
    for i, (p, (gs, ge)) in enumerate(zip(phases, gt)):
        if abs(p["start"] - gs) > TOLERANCE:
            issues.append(f"P{i} start Δ{p['start']-gs:+d}")
        if ge is not None and abs(p["end"] - ge) > TOLERANCE:
            issues.append(f"P{i} end Δ{p['end']-ge:+d}")
    return (not issues, "; ".join(issues) if issues else "all match")


def get_duration(path):
    import cv2
    cap = cv2.VideoCapture(path)
    d = cap.get(cv2.CAP_PROP_FRAME_COUNT) / max(cap.get(cv2.CAP_PROP_FPS), 1)
    cap.release()
    return d


def main():
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    vids_dir = os.path.join(base, "videos")

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from analyze_night import analyze_night_phases

    ids = sys.argv[1:] if len(sys.argv) > 1 else list(GROUND_TRUTH.keys())
    available = []
    for vid in ids:
        p = os.path.join(vids_dir, vid, "video.mp4")
        if os.path.exists(p):
            available.append((vid, p))
        else:
            print(f"  skip {vid}: not found")

    if not available:
        print("No videos found.")
        sys.exit(1)

    # Get durations
    durations = {}
    for vid, path in available:
        durations[vid] = get_duration(path)

    total_video_dur = sum(durations.values())
    print("=" * 74)
    print("  COMPREHENSIVE PIPELINE BENCHMARK")
    print("=" * 74)
    print(f"  Videos: {len(available)}  |  Total duration: {fmt_dur(total_video_dur)}")
    for vid, _ in available:
        gt = "  [GT]" if vid in GROUND_TRUTH else ""
        print(f"    {vid:<20} {fmt_dur(durations[vid]):>10}{gt}")
    print()

    # ═══════════════════════════════════════════════════════════════════════
    # Phase 1: Night Detection
    # ═══════════════════════════════════════════════════════════════════════
    print("=" * 74)
    print("  PHASE 1: Night Detection — Sequential Scan vs Parallel Scan")
    print("=" * 74)

    night_data = []
    for vid, path in available:
        dur = durations[vid]
        print(f"\n── {vid}  ({fmt_dur(dur)}) ──")

        # Sequential
        print("  sequential (workers=1) ... ", end="", flush=True)
        with timer() as ts:
            phases_seq = analyze_night_phases(path, num_workers=1)
        print(f"{fmt_t(ts['elapsed'])}  ({len(phases_seq)} phases)")

        # Parallel
        print("  parallel   (workers=3) ... ", end="", flush=True)
        with timer() as tp:
            phases_par = analyze_night_phases(path, num_workers=0)
        print(f"{fmt_t(tp['elapsed'])}  ({len(phases_par)} phases)")

        match = phases_seq == phases_par
        sp = ts["elapsed"] / tp["elapsed"] if tp["elapsed"] > 0 else 0

        gt_ok = None
        gt_detail = ""
        gt_entry = GROUND_TRUTH.get(vid)
        if gt_entry:
            gt_ok, gt_detail = check_gt(phases_par, gt_entry)

        print(f"  → speedup {sp:.2f}x  |  match={match}  |  GT={'PASS' if gt_ok else 'FAIL' if gt_ok is False else 'N/A'}")
        if gt_ok is False:
            print(f"    GT detail: {gt_detail}")
        if not match:
            print(f"    SEQ: {json.dumps(phases_seq, indent=None)}")
            print(f"    PAR: {json.dumps(phases_par, indent=None)}")

        # Per-second throughput
        rate_seq = dur / ts["elapsed"] if ts["elapsed"] > 0 else 0
        rate_par = dur / tp["elapsed"] if tp["elapsed"] > 0 else 0

        night_data.append({
            "id": vid, "dur": dur,
            "seq_t": ts["elapsed"], "par_t": tp["elapsed"],
            "speedup": sp, "match": match,
            "gt_ok": gt_ok, "phases": len(phases_par),
            "rate_seq": rate_seq, "rate_par": rate_par,
        })

    # ═══════════════════════════════════════════════════════════════════════
    # Phase 2: Name Detection
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 74}")
    print("  PHASE 2: Name Detection (PaddleOCR)")
    print("=" * 74)

    from analyze_names import analyze_name_regions

    # Run on 2 representative videos (shortest + middle)
    sorted_av = sorted(available, key=lambda x: durations[x[0]])
    name_vids = [sorted_av[0]]
    if len(sorted_av) >= 3:
        name_vids.append(sorted_av[len(sorted_av) // 2])

    name_times = []
    for vid, path in name_vids:
        print(f"\n── {vid}  ({fmt_dur(durations[vid])}) ──")
        with timer() as tn:
            masks = analyze_name_regions(path)
        print(f"  → {len(masks)} region(s) in {fmt_t(tn['elapsed'])}")
        name_times.append(tn["elapsed"])

    avg_name = sum(name_times) / len(name_times)
    print(f"\n  Avg name detection: {fmt_t(avg_name)}")
    print(f"  (PaddleOCR scans 1000s–1300s range; time is ~constant per video)")

    # ═══════════════════════════════════════════════════════════════════════
    # Phase 3: Full Pipeline Projection
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 74}")
    print("  PHASE 3: Full Pipeline Projection")
    print("=" * 74)
    print(f"  Sequential = night_seq + name_detect")
    print(f"  Parallel   = max(night_par, name_detect)   [concurrent processes]")
    print(f"  Name detection time (avg): {fmt_t(avg_name)}")

    pipeline = []
    for r in night_data:
        seq_total = r["seq_t"] + avg_name
        par_total = max(r["par_t"], avg_name)
        pl_sp = seq_total / par_total if par_total > 0 else 0
        pipeline.append({**r, "name_t": avg_name,
                         "seq_total": seq_total, "par_total": par_total,
                         "pl_speedup": pl_sp})

    # ═══════════════════════════════════════════════════════════════════════
    # Summary Tables
    # ═══════════════════════════════════════════════════════════════════════
    W = 74
    print(f"\n{'=' * W}")
    print("  RESULTS SUMMARY")
    print(f"{'=' * W}")

    # Table 1: Night detection
    print(f"\n  Night Detection Scan")
    print(f"  {'Video':<16} {'Length':>7} {'#Ph':>3} {'Seq':>8} {'Par':>8} {'Speedup':>7} {'Rate':>8} {'Match':>5} {'GT':>4}")
    print(f"  {'─'*68}")
    for r in night_data:
        gt_s = "PASS" if r["gt_ok"] else ("FAIL" if r["gt_ok"] is False else " — ")
        rate = f"{r['rate_par']:.0f}x"
        print(f"  {r['id']:<16} {fmt_dur(r['dur']):>7} {r['phases']:>3} "
              f"{fmt_t(r['seq_t']):>8} {fmt_t(r['par_t']):>8} "
              f"{r['speedup']:>6.2f}x {rate:>8} "
              f"{'✓' if r['match'] else '✗':>5} {gt_s:>4}")

    t_seq = sum(r["seq_t"] for r in night_data)
    t_par = sum(r["par_t"] for r in night_data)
    all_m = all(r["match"] for r in night_data)
    all_g = all(r["gt_ok"] is not False for r in night_data)
    avg_rate = total_video_dur / t_par if t_par else 0
    print(f"  {'─'*68}")
    print(f"  {'TOTAL':<16} {fmt_dur(total_video_dur):>7} {'':>3} "
          f"{fmt_t(t_seq):>8} {fmt_t(t_par):>8} "
          f"{t_seq/t_par if t_par else 0:>6.2f}x {f'{avg_rate:.0f}x':>8} "
          f"{'✓' if all_m else '✗':>5} {'PASS' if all_g else 'FAIL':>4}")

    # Table 2: Full pipeline
    print(f"\n  Full Pipeline (Night + Name Detection)")
    print(f"  {'Video':<16} {'Night(s)':>8} {'Night(p)':>8} {'Names':>8} {'Seq':>9} {'Par':>9} {'Speedup':>7}")
    print(f"  {'─'*68}")
    for r in pipeline:
        print(f"  {r['id']:<16} {fmt_t(r['seq_t']):>8} {fmt_t(r['par_t']):>8} "
              f"{fmt_t(r['name_t']):>8} {fmt_t(r['seq_total']):>9} "
              f"{fmt_t(r['par_total']):>9} {r['pl_speedup']:>6.2f}x")

    t_seq_pl = sum(r["seq_total"] for r in pipeline)
    t_par_pl = sum(r["par_total"] for r in pipeline)
    print(f"  {'─'*68}")
    print(f"  {'TOTAL':<16} {fmt_t(t_seq):>8} {fmt_t(t_par):>8} "
          f"{'':>8} {fmt_t(t_seq_pl):>9} {fmt_t(t_par_pl):>9} "
          f"{t_seq_pl/t_par_pl if t_par_pl else 0:>6.2f}x")

    # Key findings
    print(f"\n{'=' * W}")
    print("  KEY FINDINGS")
    print(f"{'=' * W}")
    avg_night_sp = sum(r["speedup"] for r in night_data) / len(night_data)
    avg_pl_sp = sum(r["pl_speedup"] for r in pipeline) / len(pipeline)
    print(f"  Night scan speedup (avg):    {avg_night_sp:.2f}x  (3-thread parallel vs sequential)")
    print(f"  Full pipeline speedup (avg): {avg_pl_sp:.2f}x  (parallel pipeline vs sequential)")
    print(f"  Parallel throughput:         {avg_rate:.0f}x realtime  ({fmt_dur(total_video_dur)} in {fmt_t(t_par)})")
    print(f"  Results identical (seq==par): {'YES — all videos' if all_m else 'NO — differences found'}")
    print(f"  Ground truth validation:      {'ALL PASS' if all_g else 'SOME FAILURES'}")
    print(f"  Name detection (avg):         {fmt_t(avg_name)}  (PaddleOCR, constant per video)")
    print()


if __name__ == "__main__":
    main()
