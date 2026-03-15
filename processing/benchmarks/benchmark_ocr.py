#!/usr/bin/env python3
"""Benchmark different PaddleOCR model configurations for name detection.

Compares execution time and detection results across configurations:
  1. PP-OCRv5 server (current default) — heaviest, most accurate
  2. PP-OCRv5 server, no aux models — skip doc orientation/unwarping
  3. PP-OCRv5 mobile — lightweight v5 models
  4. PP-OCRv5 mobile, no aux models — lightest v5 option
  5. PP-OCRv4 mobile — older but proven mobile models
  6. PP-OCRv4 mobile, no aux models — lightest v4 option

Tests on all 8 downloaded videos, comparing:
  - Initialization time (model loading)
  - Per-video inference time
  - Detection results (detected texts, mask regions)
"""

import json
import os
import sys
import time
from contextlib import contextmanager

os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"


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


# OCR configurations to benchmark
CONFIGS = [
    {
        "name": "v5-server",
        "label": "PP-OCRv5 server (current)",
        "kwargs": {"lang": "ch"},
    },
    {
        "name": "v5-server-noaux",
        "label": "PP-OCRv5 server, no aux",
        "kwargs": {
            "lang": "ch",
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
        },
    },
    {
        "name": "v5-mobile",
        "label": "PP-OCRv5 mobile",
        "kwargs": {
            "lang": "ch",
            "text_detection_model_name": "PP-OCRv5_mobile_det",
            "text_recognition_model_name": "PP-OCRv5_mobile_rec",
        },
    },
    {
        "name": "v5-mobile-noaux",
        "label": "PP-OCRv5 mobile, no aux",
        "kwargs": {
            "lang": "ch",
            "text_detection_model_name": "PP-OCRv5_mobile_det",
            "text_recognition_model_name": "PP-OCRv5_mobile_rec",
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
        },
    },
    {
        "name": "v4-mobile",
        "label": "PP-OCRv4 mobile",
        "kwargs": {"lang": "ch", "ocr_version": "PP-OCRv4"},
    },
    {
        "name": "v4-mobile-noaux",
        "label": "PP-OCRv4 mobile, no aux",
        "kwargs": {
            "lang": "ch",
            "ocr_version": "PP-OCRv4",
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
        },
    },
]


def run_config(config, videos):
    """Run a single OCR configuration across all videos.

    Returns dict with init_time, per-video results (time, texts, masks).
    """
    from paddleocr import PaddleOCR

    from analyze_names import (
        analyze_name_regions_with_ocr,
    )

    name = config["name"]
    print(f"\n{'─' * 70}")
    print(f"  Config: {config['label']}")
    print(f"{'─' * 70}")

    # Initialize OCR
    print(f"  Initializing... ", end="", flush=True)
    with timer() as t_init:
        ocr = PaddleOCR(**config["kwargs"])
    print(f"{fmt_t(t_init['elapsed'])}")

    results = []
    for vid, path in videos:
        print(f"  {vid} ... ", end="", flush=True)
        with timer() as tv:
            masks, texts = analyze_name_regions_with_ocr(ocr, path)
        texts_str = ", ".join(sorted(texts)) if texts else "(none)"
        n_masks = len(masks)
        print(f"{fmt_t(tv['elapsed'])}  [{n_masks} masks, {len(texts)} texts]")
        results.append({
            "video": vid,
            "time": tv["elapsed"],
            "masks": masks,
            "texts": sorted(texts) if texts else [],
            "n_masks": n_masks,
        })

    return {
        "config": name,
        "label": config["label"],
        "init_time": t_init["elapsed"],
        "results": results,
        "total_time": sum(r["time"] for r in results),
    }


def masks_match(m1, m2, tol=0.02):
    """Check if two mask region lists are equivalent within tolerance."""
    if len(m1) != len(m2):
        return False
    for a, b in zip(
        sorted(m1, key=lambda m: m["x"]),
        sorted(m2, key=lambda m: m["x"]),
    ):
        for k in ("x", "y", "w", "h"):
            if abs(a[k] - b[k]) > tol:
                return False
    return True


def main():
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    vids_dir = os.path.join(base, "videos")

    # Find all videos
    ids = sys.argv[1:] if len(sys.argv) > 1 else None
    available = []
    if ids:
        for vid in ids:
            p = os.path.join(vids_dir, vid, "video.mp4")
            if os.path.exists(p):
                available.append((vid, p))
            else:
                print(f"  skip {vid}: not found")
    else:
        for d in sorted(os.listdir(vids_dir)):
            p = os.path.join(vids_dir, d, "video.mp4")
            if os.path.exists(p):
                available.append((d, p))

    if not available:
        print("No videos found.")
        sys.exit(1)

    W = 74
    print("=" * W)
    print("  OCR MODEL BENCHMARK")
    print("=" * W)
    print(f"  Videos: {len(available)}")
    for vid, _ in available:
        print(f"    {vid}")
    print(f"\n  Configurations: {len(CONFIGS)}")
    for c in CONFIGS:
        print(f"    {c['label']}")

    # Run each configuration
    all_results = []
    for config in CONFIGS:
        result = run_config(config, available)
        all_results.append(result)

    # ═══════════════════════════════════════════════════════════════════════
    # Summary Tables
    # ═══════════════════════════════════════════════════════════════════════
    baseline = all_results[0]  # v5-server is the baseline

    print(f"\n{'=' * W}")
    print("  RESULTS SUMMARY")
    print(f"{'=' * W}")

    # Table 1: Timing comparison
    print(f"\n  Initialization Time")
    print(f"  {'Config':<30} {'Init':>8} {'vs baseline':>12}")
    print(f"  {'─' * 54}")
    for r in all_results:
        sp = baseline["init_time"] / r["init_time"] if r["init_time"] > 0 else 0
        marker = " (baseline)" if r == baseline else f" {sp:.2f}x"
        print(f"  {r['label']:<30} {fmt_t(r['init_time']):>8}{marker:>12}")

    print(f"\n  Per-Video Inference Time")
    # Header
    vid_names = [v for v, _ in available]
    print(f"  {'Config':<26}", end="")
    for v in vid_names:
        print(f" {v[:11]:>11}", end="")
    print(f" {'TOTAL':>9} {'Speedup':>7}")
    print(f"  {'─' * (26 + 12 * len(vid_names) + 18)}")

    for r in all_results:
        print(f"  {r['label']:<26}", end="")
        for vr in r["results"]:
            print(f" {fmt_t(vr['time']):>11}", end="")
        sp = baseline["total_time"] / r["total_time"] if r["total_time"] > 0 else 0
        marker = "(base)" if r == baseline else f"{sp:.2f}x"
        print(f" {fmt_t(r['total_time']):>9} {marker:>7}")

    # Table 2: Detection accuracy comparison
    print(f"\n  Detection Results vs Baseline")
    print(f"  {'Config':<26}", end="")
    for v in vid_names:
        print(f" {v[:11]:>11}", end="")
    print()
    print(f"  {'─' * (26 + 12 * len(vid_names))}")

    for r in all_results:
        if r == baseline:
            print(f"  {r['label']:<26}", end="")
            for vr in r["results"]:
                n = len(vr["texts"])
                label = f"{vr['n_masks']}m/{n}t"
            print(f" {label:>11}", end="")
            print("  (baseline)")
            continue

        print(f"  {r['label']:<26}", end="")
        for vr, br in zip(r["results"], baseline["results"]):
            m_ok = masks_match(vr["masks"], br["masks"])
            t_ok = vr["texts"] == br["texts"]
            if m_ok and t_ok:
                status = "✓ same"
            elif m_ok:
                status = "~masks ok"
            else:
                n = len(vr["texts"])
                status = f"{vr['n_masks']}m/{n}t"
            print(f" {status:>11}", end="")
        print()

    # Table 3: Detailed text comparison for configs that differ
    print(f"\n  Detected Texts per Video")
    for vid_idx, (vid, _) in enumerate(available):
        texts_by_config = {}
        for r in all_results:
            key = tuple(r["results"][vid_idx]["texts"])
            if key not in texts_by_config:
                texts_by_config[key] = []
            texts_by_config[key].append(r["label"])

        if len(texts_by_config) == 1:
            texts = list(texts_by_config.keys())[0]
            t_str = ", ".join(texts) if texts else "(none)"
            print(f"  {vid}: {t_str}  [all configs agree]")
        else:
            print(f"  {vid}: DIFFERS")
            for texts, configs in texts_by_config.items():
                t_str = ", ".join(texts) if texts else "(none)"
                c_str = ", ".join(configs)
                print(f"    [{c_str}]: {t_str}")

    # Key findings
    print(f"\n{'=' * W}")
    print("  KEY FINDINGS")
    print(f"{'=' * W}")

    fastest = min(all_results, key=lambda r: r["total_time"])
    fastest_init = min(all_results, key=lambda r: r["init_time"])
    sp_fastest = baseline["total_time"] / fastest["total_time"] if fastest["total_time"] > 0 else 0

    # Check which configs produce identical results to baseline
    identical = []
    for r in all_results[1:]:
        all_match = all(
            masks_match(vr["masks"], br["masks"]) and vr["texts"] == br["texts"]
            for vr, br in zip(r["results"], baseline["results"])
        )
        if all_match:
            identical.append(r["label"])

    print(f"  Baseline (current):    {baseline['label']}")
    print(f"  Baseline total time:   {fmt_t(baseline['total_time'])}  (init: {fmt_t(baseline['init_time'])})")
    print(f"  Fastest config:        {fastest['label']}")
    print(f"  Fastest total time:    {fmt_t(fastest['total_time'])}  ({sp_fastest:.2f}x faster)")
    print(f"  Fastest init:          {fastest_init['label']}  ({fmt_t(fastest_init['init_time'])})")
    if identical:
        print(f"  Identical results:     {', '.join(identical)}")
    else:
        print(f"  Identical results:     (none — all configs differ from baseline)")
    print()


if __name__ == "__main__":
    main()
