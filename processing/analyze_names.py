#!/usr/bin/env python3
"""Detect character role name regions using PaddleOCR."""

import argparse
import json
import os

# Must be set before importing paddleocr: skips PaddleX's model-source
# network check (faster init, works offline)
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

import re
from collections import Counter

import cv2
import numpy as np
from paddleocr import PaddleOCR

# Local model directory (self-contained, no global cache dependency)
_MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")

ROLE_NAMES = [
    "狼人", "狼王", "白狼王", "预言家", "女巫", "猎人",
    "白痴", "守卫", "村民", "平民", "通灵师", "丘比特",
    "盗贼", "长老", "骑士", "野孩子", "石像鬼", "混血儿",
    "假面", "盗宝大师", "机械狼", "黑狼王", "狼术师",
    "典狱长", "狼美人", "黑夜使者", "定序王子", "魔术师",
    "舞者", "毒师", "白神", "蒙面人", "摄梦人", "白夜使者",
    "杠精",
]
ROLE_SET = set(ROLE_NAMES)

# Hardware/stream overlay tokens that sit in the name column area but are not
# player names (GPU badges, quality tags, the channel handle)
NAME_STOPWORDS = {"rtx", "vsr", "hdr", "fps", "live", "hd", "4k", "8k", "ai",
                  "vip", "youtube", "jcdss", "new"}


def sample_frames(video_path, start_sec=60, end_sec=300, interval=1):
    """Yield (sec, frame) tuples from video at given interval.

    Uses sequential grab/read from the start position instead of seeking
    to each frame individually. A frame-index cursor keeps samples
    frame-accurate for fractional frame rates. Generator stops reading
    when the consumer breaks out of the loop.
    """
    cap = cv2.VideoCapture(video_path)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps
        end_sec = min(end_sec, duration)

        # Seek to first sample position; pos = frame index of the next read
        pos = int(round(start_sec * fps))
        if pos > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, pos)

        for sec in range(int(start_sec), int(end_sec), interval):
            target = int(round(sec * fps))
            while pos < target and cap.grab():
                pos += 1
            ret, frame = cap.read()
            if not ret:
                break
            pos += 1
            yield (sec, frame)
    finally:
        cap.release()


def ocr_items_in_frame(ocr, frame, edge_ratio=0.30, min_score=0.5):
    """OCR the left and right edge strips, return every text box found.

    Both crops go through one predict() call. edge_ratio=0.30 keeps the
    center stage out while capturing the director's note column, which sits
    just inward of the role names. Coordinates are normalized to the full
    frame. Boxes exceeding the crop width (PaddleOCR can inflate coords on
    narrow crops) are dropped.
    """
    h, w = frame.shape[:2]
    x_right = int(w * (1 - edge_ratio))
    crops = [
        ("left", 0, frame[:, :int(w * edge_ratio)]),
        ("right", x_right, frame[:, x_right:]),
    ]
    results = ocr.predict([c[2] for c in crops])
    items = []
    for (side, x_offset, crop), result in zip(crops, results):
        crop_w = crop.shape[1]
        texts = result.get("rec_texts", [])
        scores = result.get("rec_scores", [])
        polys = result.get("dt_polys", [])
        for text, score, poly in zip(texts, scores, polys):
            if score < min_score:
                continue
            poly = np.array(poly)
            x1, y1 = poly.min(axis=0)
            x2, y2 = poly.max(axis=0)
            if x2 > crop_w:
                continue
            items.append({
                "side": side, "text": text.strip(), "score": float(score),
                "x0": round((x_offset + x1) / w, 4),
                "x1": round((x_offset + x2) / w, 4),
                "y0": round(y1 / h, 4), "y1": round(y2 / h, 4),
            })
    return items


def _roles_from_items(items):
    """Exact role-name boxes from raw OCR items (exact match: notes and the
    watermark contain role words too)."""
    regions = []
    for it in items:
        if it["text"] in ROLE_SET:
            regions.append({
                "x": it["x0"], "y": it["y0"],
                "w": round(it["x1"] - it["x0"], 4),
                "h": round(it["y1"] - it["y0"], 4),
                "text": it["text"], "side": it["side"],
            })
    return regions


def detect_names_in_frame(ocr, frame, edge_ratio=0.30):
    """Run OCR on the frame edges, return role-name bounding boxes."""
    return _roles_from_items(ocr_items_in_frame(ocr, frame, edge_ratio=edge_ratio))


def analyze_name_regions_with_ocr(ocr, video_path):
    """Run name detection with a pre-initialized OCR instance.

    Returns (masks, unique_texts) tuple (role map omitted).
    """
    masks, _role_map, texts = _analyze(ocr, video_path)
    return masks, texts


def _scan_range(ocr, video_path, start_sec, end_sec, interval, min_named_frames=8):
    """Scan a range. Returns (regions, items, num_sampled).

    Accumulates raw OCR items (for the role map) from frames containing role
    names, stopping after min_named_frames such frames.
    """
    all_regions = []
    all_items = []
    found_any = False
    named = 0
    num_sampled = 0
    gen = sample_frames(video_path, start_sec=start_sec, end_sec=end_sec,
                        interval=interval)
    try:
        for sec, frame in gen:
            num_sampled += 1
            items = ocr_items_in_frame(ocr, frame)
            regions = _roles_from_items(items)
            if regions:
                if not found_any:
                    print(f"  First names detected at {sec}s")
                    found_any = True
                all_regions.extend(regions)
                all_items.extend(items)
                named += 1
                if named >= min_named_frames:
                    print(f"  Collected {named} named frames by {sec}s")
                    break
    finally:
        gen.close()
    return all_regions, all_items, num_sampled


def _cluster_rows(regs, tol=0.05):
    """Group role boxes into player rows by vertical position (majority role
    per row tolerates per-frame OCR noise)."""
    pts = sorted((r["y"] + r["h"] / 2, r["text"]) for r in regs)
    clusters = []
    for yc, role in pts:
        if clusters and yc - clusters[-1]["last"] <= tol:
            c = clusters[-1]
            c["ys"].append(yc); c["roles"].append(role); c["last"] = yc
        else:
            clusters.append({"ys": [yc], "roles": [role], "last": yc})
    return [{"role": Counter(c["roles"]).most_common(1)[0][0],
             "yc": float(np.median(c["ys"])), "count": len(c["ys"])}
            for c in clusters]


def _bands_from_centers(cs):
    """Vertical reveal band for each row: midpoints to the adjacent rows."""
    n = len(cs)
    bands = []
    for i, c in enumerate(cs):
        up = (cs[i - 1] + c) / 2 if i > 0 else (c - (cs[i + 1] - c) / 2 if n > 1 else c - 0.08)
        dn = (cs[i + 1] + c) / 2 if i < n - 1 else (c + (c - cs[i - 1]) / 2 if n > 1 else c + 0.08)
        bands.append((max(0.0, up), min(1.0, dn)))
    return bands


def build_role_map(all_items, all_regions):
    """Map each player row to its role, number, name, and reveal y-band.

    Used by the viewer's role-reveal panel. The role string is only a menu
    label (the revealed pixels are the source of truth), so OCR noise in it
    is harmless.
    """
    role_map = {}
    for side in ("left", "right"):
        regs = [r for r in all_regions if r["side"] == side]
        if not regs:
            continue
        rows = _cluster_rows(regs)
        if not rows:
            continue
        rows.sort(key=lambda r: r["yc"])
        bands = _bands_from_centers([r["yc"] for r in rows])
        sit = [it for it in all_items if it["side"] == side]
        rx0 = float(np.percentile([r["x"] for r in regs], 10))
        rx1 = float(np.percentile([r["x"] + r["w"] for r in regs], 90))

        nums = [[] for _ in rows]
        names = [[] for _ in rows]
        for it in sit:
            yc = (it["y0"] + it["y1"]) / 2
            bi = next((i for i, (a, b) in enumerate(bands) if a <= yc < b), None)
            if bi is None:
                continue
            t = it["text"]
            xc = (it["x0"] + it["x1"]) / 2
            # Numbers and names sit outward of the role column (toward the
            # frame edge); notes sit inward (toward center)
            outward = xc < rx0 if side == "left" else xc > rx1
            if not outward:
                continue
            if re.fullmatch(r"\d{1,2}", t):
                v = int(t)
                if 1 <= v <= 12:
                    nums[bi].append(v)
            elif (t not in ROLE_SET and t.lower() not in NAME_STOPWORDS
                  and not re.fullmatch(r"[\W\d_]+", t) and 1 <= len(t) <= 5):
                has_cjk = 1 if re.search(r"[\u4e00-\u9fff]", t) else 0
                # Prefer Chinese names, then those nearest the role row
                # (drops top-corner overlays like "RTX"/"VSR"), then score
                names[bi].append((has_cjk, -round(abs(yc - rows[bi]["yc"]), 4),
                                  it["score"], t))

        players = []
        for i, row in enumerate(rows):
            number = Counter(nums[i]).most_common(1)[0][0] if nums[i] else None
            name = max(names[i])[3] if names[i] else None
            y0, y1 = bands[i]
            players.append({"number": number, "name": name, "role": row["role"],
                            "y0": round(y0, 4), "y1": round(y1, 4)})
        players.sort(key=lambda p: (p["number"] is None,
                                    p["number"] if p["number"] is not None else 0,
                                    p["y0"]))
        role_map[side] = players
    return role_map


# Fraction of frame width the mask extends inward past the role column, to
# cover the director's running description/opinion next to each role
# ("验9查杀", "觉得1不是狼"…) — those give the role away as much as the name.
# Fixed (not measured): the note column is a fixed-width UI element, and
# measuring it tripped over centered banners (title, config line, ticker).
NOTE_EXTEND = 0.12


def build_masks(all_regions):
    """Mask each side's role column plus the adjacent note column.

    Outer edge = role column edge (10th/90th percentile, so a stray box can't
    widen it); inner edge = role edge + NOTE_EXTEND toward center, clamped so
    the mask can never reach the central stage.
    """
    masks = []
    pad = 0.015
    for side in ("left", "right"):
        regs = [r for r in all_regions if r["side"] == side]
        if not regs:
            continue
        rx0 = float(np.percentile([r["x"] for r in regs], 10))
        rx1 = float(np.percentile([r["x"] + r["w"] for r in regs], 90))
        if side == "left":
            x_min = max(0.0, rx0 - pad)
            x_max = min(0.32, rx1 + NOTE_EXTEND)
        else:
            x_min = max(0.68, rx0 - NOTE_EXTEND)
            x_max = min(1.0, rx1 + pad)
        masks.append({"x": round(x_min, 4), "y": 0,
                      "w": round(x_max - x_min, 4), "h": 1.0})
    return masks


def _analyze(ocr, video_path):
    """Core analysis logic shared by public entry points.

    Returns (masks, role_map, unique_texts).

    Scans 1100s-1400s first. If both sides aren't found, extends the scan
    to 1400s-2000s with a coarser interval to find late-appearing names.
    """
    print("Sampling frames (1100s-1400s at 10s intervals)...")
    all_regions, all_items, num_sampled = _scan_range(
        ocr, video_path, 1100, 1400, interval=10)
    print(f"Processed {num_sampled} frames")

    sides_found = set(r["side"] for r in all_regions)
    missing_sides = {"left", "right"} - sides_found

    if missing_sides and all_regions:
        print(f"  Missing {', '.join(missing_sides)} side. "
              f"Extending scan (1400s-2000s at 30s intervals)...")
        er, ei, es = _scan_range(
            ocr, video_path, 1400, 2000, interval=30, min_named_frames=4)
        num_sampled += es
        all_regions.extend(r for r in er if r["side"] in missing_sides)
        all_items.extend(it for it in ei if it["side"] in missing_sides)
        print(f"  Extended scan: {es} more frames")

    if not all_regions:
        print("  No names in primary range. Trying extended scan "
              "(1400s-2000s at 30s intervals)...")
        all_regions, all_items, es = _scan_range(
            ocr, video_path, 1400, 2000, interval=30, min_named_frames=4)
        num_sampled += es
        print(f"  Extended scan: {es} frames")

    if not all_regions:
        print("No role names detected. Using default mask positions.")
        return [
            {"x": 0.05, "y": 0, "w": 0.10, "h": 1.0},
            {"x": 0.85, "y": 0, "w": 0.10, "h": 1.0},
        ], {}, set()

    unique_texts = set(r["text"] for r in all_regions)
    print(f"Detected texts: {', '.join(sorted(unique_texts))}")

    masks = build_masks(all_regions)
    role_map = build_role_map(all_items, all_regions)
    print(f"Merged into {len(masks)} mask region(s)")
    for m in masks:
        print(f"  x={m['x']:.3f} y={m['y']:.3f} w={m['w']:.3f} h={m['h']:.3f}")
    for sd, players in role_map.items():
        print(f"  role_map[{sd}]: " + ", ".join(
            f"{p['number'] if p['number'] is not None else '?'}={p['role']}"
            for p in players))
    return masks, role_map, unique_texts


def _ensure_models():
    """Download OCR models to local directory if not present.

    Uses PaddleOCR's built-in model resolution to download, then copies
    from the global cache to the project-local models/ directory.
    """
    det_dir = os.path.join(_MODELS_DIR, "PP-OCRv5_server_det")
    rec_dir = os.path.join(_MODELS_DIR, "PP-OCRv5_server_rec")

    det_ok = os.path.isdir(det_dir) and os.path.exists(
        os.path.join(det_dir, "inference.pdiparams"))
    rec_ok = os.path.isdir(rec_dir) and os.path.exists(
        os.path.join(rec_dir, "inference.pdiparams"))

    if det_ok and rec_ok:
        return det_dir, rec_dir

    print("  Models not found locally. Downloading...")
    os.makedirs(_MODELS_DIR, exist_ok=True)

    # Use PaddleOCR with model names to trigger download to global cache,
    # then copy to local directory
    import shutil
    tmp_ocr = PaddleOCR(
        lang="ch",
        text_detection_model_name="PP-OCRv5_server_det",
        text_recognition_model_name="PP-OCRv5_server_rec",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    del tmp_ocr

    # Find downloaded models in global cache
    cache_base = os.path.expanduser("~/.paddlex/official_models")
    for model_name in ["PP-OCRv5_server_det", "PP-OCRv5_server_rec"]:
        src = os.path.join(cache_base, model_name)
        dst = os.path.join(_MODELS_DIR, model_name)
        if os.path.isdir(src) and not os.path.isdir(dst):
            shutil.copytree(src, dst)
            print(f"  Copied {model_name} to local models/")
        elif os.path.isdir(src):
            # Update existing (in case of partial download)
            shutil.rmtree(dst)
            shutil.copytree(src, dst)
            print(f"  Updated {model_name} in local models/")

    return det_dir, rec_dir


def _init_ocr():
    """Initialize PaddleOCR with local models and optimal device."""
    # Ensure models are downloaded
    det_dir, rec_dir = _ensure_models()

    # Detect GPU availability (CUDA only; PaddlePaddle has no Apple MPS support)
    device = "cpu"
    try:
        import paddle
        if paddle.device.is_compiled_with_cuda():
            device = "gpu:0"
            print(f"  Using GPU (CUDA)")
    except Exception:
        pass
    if device == "cpu":
        print(f"  Using CPU")

    return PaddleOCR(
        text_detection_model_dir=det_dir,
        text_recognition_model_dir=rec_dir,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        device=device,
    )


def analyze_name_regions(video_path):
    """Main entry point: masks only (backward-compatible)."""
    return analyze_name_regions_full(video_path)["name_masks"]


def analyze_name_regions_full(video_path):
    """Full name-detection result: {"name_masks": [...], "role_map": {...}}."""
    print("Initializing PaddleOCR...")
    ocr = _init_ocr()
    masks, role_map, _texts = _analyze(ocr, video_path)
    return {"name_masks": masks, "role_map": role_map}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Detect character name regions")
    parser.add_argument("video_path", help="Path to video file")
    args = parser.parse_args()

    result = analyze_name_regions_full(args.video_path)
    print(json.dumps(result, indent=2, ensure_ascii=False))
