#!/usr/bin/env python3
"""Benchmark night + card-viewing detection: parallel vs sequential, validate
against ground truth (nights, 看牌 tours, and S22 first nights)."""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from analyze_night import analyze_phases

# Ground truth from CLAUDE.md (±TOLERANCE). Since 2026-10-25 a first night
# (and the night after a re-deal) starts where the card viewing (看牌) ends,
# the cut from the last seat close-up to the table; in S21 that is 2-7 s
# before the red light comes on, which the older entries used.
GROUND_TRUTH = {
    "65R0r19JyYk": [
        (747, 1025), (1781, 1981), (2011, 2163), (3488, 3631),
    ],
    "EC-1bimFjo4": [   # re-dealt: the first night (7:26-8:24) was interrupted
        (446, 504), (944, 1130), (1691, 1958), (1995, 2207), (2784, 2914),
    ],
    "-ESYZWvQMH4": [
        (498, 743), (4388, 4579), (6365, 6505), (7752, 7866), (8716, 8756),
    ],
    "ZusP81Ycn-U": [
        (447, 688), (4968, 5231), (5266, 5405), (6290, None),  # last has no exit
    ],
    "ieLaR4NBPz4": [
        (670, 908), (2070, 2328), (2358, 2542),
    ],
    "Xk65eicHSyw": [
        (1000, 1268), (2530, 2760), (4252, 4416), (5358, 5482),
    ],
    "WkVPdddUiio": [
        (365, 592), (3490, 3674), (5468, 5580), (7148, 7250),
    ],
    "F2J0QK_3gUo": [
        (622, 854), (1689, 1880), (1907, 2068), (3570, 3640),
    ],
    "Jnf_dLaVNMU": [
        (702, 914), (2566, 2820),
    ],
    # S23 (cut-heavy nights; boundaries verified frame by frame, day counter cross-checked)
    "xNDz6SStaLo": [   # S23E24 第一局 -- 26s self-destruct day 2 at 63:46 (dawn banner 63:48, night banner 64:14)
        (557, 793), (3638, 3826), (3852, 3955),
    ],
    "QNxo5hmWLN0": [   # S23E24 第二局 (hidden-roles broadcast; overlay off in the viewer) -- 24s self-destruct day at 91:57; dawn banner 94:48
        # re-dealt: the first game was abandoned at its first dawn (9:46);
        # the second deal's night 1 is covered by the commentators until 21:50
        (423, 586), (1040, 1310), (5313, 5517), (5541, 5685),
    ],
    "bzsBWNpIwpo": [   # S23E25 第一局 (day 2 lasts only ~5.5 min)
        (670, 900), (3846, 4000), (4339, 4441),
    ],
    "fgw-4eUV0JE": [   # S23E25 第二局
        (381, 624), (4672, 4854),
    ],
    # S23E26 (2026-10-15 broadcasts; phase banners + self-destruct days + a 152s wolves' close-up gap)
    "X5J6PIMh368": [   # S23E26 第一局 预女猎白混 -- game ends on day 1
        (427, 693),
    ],
    "3oifxz_xLr4": [   # S23E26 第二局 假面舞会 -- 28s self-destruct day between the last two
        (435, 676), (2996, 3277), (3305, 3352),
    ],
    "40RdPP2AuMs": [   # S23E26 第三局 机械狼通灵师 -- night 1 has a 152s wolves' discussion gap; 34s self-destruct day at 30:00
        (472, 825), (1581, 1800), (1831, 2013),
    ],
    "CBZfebaxD0E": [   # S23E26 第四局 机械狼通灵师
        (487, 796), (3531, 3715), (4188, 4348),
    ],
    # S22, every night checked on frames 2026-10-26. Both games have a short
    # day lit purple (R/G ~1.6) on the table shot, which the ratio merge rule
    # took for night close-ups and merged with the nights around it
    "d3jNiPSqMuI": [   # S22E47 第一局 -- 30s day 28:27-28:57; the game ends on day 5 (final board 1:01:40)
        (462, 709), (1544, 1706), (1737, 1846), (2292, 2389),
    ],
    "zla5T_T4UKQ": [   # S22E49 第三局 -- 23s day 27:15-27:38; the game ends on day 5 (final board 45:50)
        (414, 678), (1215, 1453), (1495, 1634), (1658, 1815),
    ],
}

# Card viewing (看牌) tours, every one checked on frames (2026-10-25): the shot
# before is the commentators / introductions, the first and last tour shots
# are seat close-ups, the shot after is the table at nightfall
CARD_GROUND_TRUTH = {
    "-ESYZWvQMH4": [(455, 498)], "65R0r19JyYk": [(704, 747)], "EC-1bimFjo4": [(408, 446), (906, 944)],
    "F2J0QK_3gUo": [(575, 622)], "ieLaR4NBPz4": [(628, 670)], "Jnf_dLaVNMU": [(654, 702)],
    "WkVPdddUiio": [(324, 365)], "Xk65eicHSyw": [(958, 1000)], "ZusP81Ycn-U": [(398, 447)],
    "d3jNiPSqMuI": [(426, 462)], "iDD3JgXWA-0": [(509, 549)], "7SG4f3ZpZP0": [(528, 566)],
    "Im5713oy3b4": [(480, 516)], "9Yij3uRUp1M": [(470, 524)], "Dv0dRH80XGo": [(400, 441)],
    "zHCN-nyQ9jA": [(403, 446)], "02bLRRi6RZk": [(349, 390)], "zla5T_T4UKQ": [(375, 414)],
    "xNDz6SStaLo": [(517, 557)], "QNxo5hmWLN0": [(387, 423), (999, 1040)],
    "pZ0vo8VRDkA": [(448, 485), (827, 863)], "bzsBWNpIwpo": [(624, 670)], "fgw-4eUV0JE": [(345, 381)],
    "HpIM5xTU-t8": [(377, 416)], "X5J6PIMh368": [(388, 427)], "3oifxz_xLr4": [(397, 435)],
    "40RdPP2AuMs": [(434, 472)], "CBZfebaxD0E": [(450, 487)],
    # S23E28 (2026-10-27): a 2x2 split screen of the four table cameras instead
    # of a tour, from the cut away from the commentators to the cut to the
    # night's table (checked on frames)
    "40WQgtMozXM": [(615, 639)], "VP2EVqrsWOE": [(469, 491)], "8myFCIe-Yeo": [(291, 314)],
}
CARD_TOLERANCE = 3  # seconds (Xk65eicHSyw's tour starts ~2.5 s early: a split commentators' shot)

# S22 first nights (start = 看牌 end, end = red light off or, in the hidden-
# roles games, the cut from the commentators back to the table), checked on
# frames 2026-10-25. Third value: seconds the detected end may overshoot.
# (d3jNiPSqMuI and zla5T_T4UKQ moved to GROUND_TRUTH with all their nights.)
FIRST_NIGHT_GT = {
    "Dv0dRH80XGo": (441, 726, 0), "zHCN-nyQ9jA": (446, 689, 0), "02bLRRi6RZk": (390, 653, 0),
    "Im5713oy3b4": (516, 755, 0),    # hidden roles: commentators until 12:34
    "iDD3JgXWA-0": (549, 815, 0),    # hidden roles: table still red-lit 13:33-13:35
    "7SG4f3ZpZP0": (566, 829, 0),    # hidden roles: commentators until 13:49
    # No red light for night 1 at all; dawn is 13:17, and the night is ended at
    # the first sidebar sighting, ~35 s later
    "9Yij3uRUp1M": (524, 797, 40),
    # S23 hidden-roles games whose first nights the red light never showed
    # (none was detected before 2026-10-25): commentators until the dawn cut
    "HpIM5xTU-t8": (416, 710, 0),    # S23E25 第三局: commentators until 11:49
    "pZ0vo8VRDkA": (485, 540, 0),    # S23E24 第三局, first deal (abandoned at dawn, table red until 9:00);
                                     # the second deal's night 1 is 14:22-18:13
    # S23E28: night 1 from the split screen's end to the red light going off
    "40WQgtMozXM": (639, 890, 0), "VP2EVqrsWOE": (491, 768, 0), "8myFCIe-Yeo": (314, 569, 0),
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


def check_cards(cards, ground_truth):
    """Check detected card-viewing tours against ground truth."""
    if len(cards) != len(ground_truth):
        return False, f"Count mismatch: got {len(cards)}, expected {len(ground_truth)}"
    bad = [f"  Tour {i}: {c['start']}-{c['end']} vs {s}-{e}"
           for i, (c, (s, e)) in enumerate(zip(cards, ground_truth))
           if abs(c["start"] - s) > CARD_TOLERANCE or abs(c["end"] - e) > CARD_TOLERANCE]
    return (False, "\n".join(bad)) if bad else (True, "All tours match")


def check_first_night(phases, gt):
    """Check the first night only: (start, end, allowed overshoot of the end)."""
    s, e, late = gt
    if not phases:
        return False, "no night"
    p = min(phases, key=lambda q: q["start"])
    ok = abs(p["start"] - s) <= TOLERANCE and -TOLERANCE <= p["end"] - e <= TOLERANCE + late
    return ok, f"first night {p['start']}-{p['end']} vs {s}-{e}"


def benchmark_video(video_id, video_path):
    """Run sequential and parallel, compare results and timing."""
    print(f"\n{'='*60}")
    print(f"Video: {video_id}")
    print(f"{'='*60}")

    # Sequential (workers=1)
    print("\n--- Sequential (workers=1) ---")
    t0 = time.time()
    seq = analyze_phases(video_path, num_workers=1)
    seq_time = time.time() - t0
    print(f"Time: {seq_time:.1f}s")

    # Parallel (auto workers)
    print("\n--- Parallel (auto workers) ---")
    t0 = time.time()
    par = analyze_phases(video_path, num_workers=0)
    par_time = time.time() - t0
    print(f"Time: {par_time:.1f}s")
    seq_phases, par_phases = seq["night_phases"], par["night_phases"]

    # Compare sequential vs parallel results
    if seq == par:
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
    elif video_id in FIRST_NIGHT_GT:
        gt = True
        seq_ok, seq_detail = check_first_night(seq_phases, FIRST_NIGHT_GT[video_id])
        par_ok, par_detail = check_first_night(par_phases, FIRST_NIGHT_GT[video_id])
        print(f"\nFirst night (sequential): {'PASS' if seq_ok else 'FAIL'} - {seq_detail}")
        print(f"First night (parallel):   {'PASS' if par_ok else 'FAIL'} - {par_detail}")
    else:
        print(f"\nNo night ground truth for {video_id}")
    cards_ok = None
    if video_id in CARD_GROUND_TRUTH:
        cards_ok, detail = check_cards(par["card_phases"], CARD_GROUND_TRUTH[video_id])
        print(f"Card viewing:              {'PASS' if cards_ok else 'FAIL'} - {detail}")

    speedup = seq_time / par_time if par_time > 0 else 0
    print(f"\nSpeedup: {speedup:.2f}x ({seq_time:.1f}s → {par_time:.1f}s)")

    return {
        "video_id": video_id,
        "seq_time": seq_time,
        "par_time": par_time,
        "speedup": speedup,
        "results_match": seq == par,
        "gt_seq_ok": seq_ok if gt else None,
        "gt_par_ok": par_ok if gt else None,
        "cards_ok": cards_ok,
    }


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    # The production library, then the dev instance's (scripts/dev-library.sh)
    libraries = [os.environ.get("WEREWOLF_VIDEOS_DIR") or os.path.join(base_dir, "videos"),
                 os.path.join(base_dir, "videos-dev")]

    # Use specific video IDs if provided, otherwise all ground truth videos
    if len(sys.argv) > 1:
        video_ids = sys.argv[1:]
    else:
        video_ids = list(dict.fromkeys([*GROUND_TRUTH, *FIRST_NIGHT_GT, *CARD_GROUND_TRUTH]))

    results = []
    for vid in video_ids:
        video_path = next((os.path.join(lib, vid, "video.mp4") for lib in libraries
                           if os.path.exists(os.path.join(lib, vid, "video.mp4"))), None)
        if video_path is None:
            print(f"\nSkipping {vid}: video not found")
            continue
        results.append(benchmark_video(vid, video_path))

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"{'Video':<20} {'Seq':>7} {'Par':>7} {'Speedup':>8} {'Match':>6} {'GT':>4} {'看牌':>5}")
    print("-" * 66)
    status = lambda v: "OK" if v else ("FAIL" if v is False else "N/A")
    for r in results:
        print(f"{r['video_id']:<20} {r['seq_time']:>6.1f}s {r['par_time']:>6.1f}s "
              f"{r['speedup']:>7.2f}x {str(r['results_match']):>6} {status(r.get('gt_par_ok')):>4} "
              f"{status(r.get('cards_ok')):>5}")

    total_seq = sum(r["seq_time"] for r in results)
    total_par = sum(r["par_time"] for r in results)
    all_match = all(r["results_match"] for r in results)
    all_gt = all(r.get("gt_par_ok") is not False and r.get("cards_ok") is not False for r in results)
    print("-" * 66)
    print(f"{'TOTAL':<20} {total_seq:>6.1f}s {total_par:>6.1f}s "
          f"{total_seq/total_par if total_par else 0:>7.2f}x {str(all_match):>6} "
          f"{'OK' if all_gt else 'FAIL':>4}")


if __name__ == "__main__":
    main()
