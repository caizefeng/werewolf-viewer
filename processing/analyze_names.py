#!/usr/bin/env python3
"""Detect character role name regions using PaddleOCR."""

import argparse
import json
import os

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


def sample_frames(video_path, start_sec=60, end_sec=300, interval=1):
    """Yield (sec, frame) tuples from video at given interval.

    Uses sequential grab/read from the start position instead of seeking
    to each frame individually. Generator stops reading when the consumer
    breaks out of the loop.
    """
    cap = cv2.VideoCapture(video_path)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps
        end_sec = min(end_sec, duration)

        # Seek to first sample position
        if start_sec > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(start_sec * fps))

        skip = int(interval * fps) - 1

        for sec in range(int(start_sec), int(end_sec), interval):
            ret, frame = cap.read()
            if not ret:
                break
            yield (sec, frame)
            for _ in range(skip):
                cap.grab()
    finally:
        cap.release()


def detect_names_in_frame(ocr, frame, edge_ratio=0.2):
    """Run OCR on left and right edges of frame, return role name bounding boxes."""
    h, w = frame.shape[:2]
    regions = []

    for side in ["left", "right"]:
        if side == "left":
            crop = frame[:, :int(w * edge_ratio)]
            x_offset = 0
        else:
            x_start = int(w * (1 - edge_ratio))
            crop = frame[:, x_start:]
            x_offset = x_start

        crop_w = crop.shape[1]

        for result in ocr.predict(crop):
            texts = result.get("rec_texts", [])
            scores = result.get("rec_scores", [])
            polys = result.get("dt_polys", [])

            for text, score, poly in zip(texts, scores, polys):
                if score < 0.5:
                    continue
                for role in ROLE_NAMES:
                    if role in text:
                        # Reject if the detected text is much longer than the
                        # role name — likely a watermark or show title, not a
                        # player role label (e.g. "京城大师赛狼人")
                        if len(text) > len(role) + 2:
                            break
                        poly = np.array(poly)
                        x1, y1 = poly.min(axis=0)
                        x2, y2 = poly.max(axis=0)
                        # PaddleOCR may resize narrow crops internally and
                        # return inflated coordinates — skip detections that
                        # exceed the actual crop boundaries
                        if x2 > crop_w:
                            break
                        regions.append({
                            "x": round((x_offset + x1) / w, 4),
                            "y": round(y1 / h, 4),
                            "w": round((x2 - x1) / w, 4),
                            "h": round((y2 - y1) / h, 4),
                            "text": text,
                            "side": side,
                        })
                        break

    return regions


def merge_regions(all_regions):
    """Merge detected regions per side into mask areas covering role names only.

    The mask covers only the role-name text and supplemental descriptions,
    NOT the player avatar or number.  Height is always full-frame so that
    names at any vertical position are hidden.
    """
    if not all_regions:
        return []

    merged = []
    for side in ["left", "right"]:
        side_regions = [r for r in all_regions if r["side"] == side]
        if not side_regions:
            continue

        x_min = min(r["x"] for r in side_regions)
        x_max = max(r["x"] + r["w"] for r in side_regions)

        padding = 0.015
        if side == "left":
            # Only cover the text area (do NOT extend to frame edge)
            ext_x_min = max(0, x_min - padding)
            ext_x_max = min(1, x_max + padding)
        else:
            ext_x_min = max(0, x_min - padding)
            ext_x_max = min(1, x_max + padding)

        # Full frame height — covers names at any vertical position
        merged.append({
            "x": round(ext_x_min, 4),
            "y": 0,
            "w": round(ext_x_max - ext_x_min, 4),
            "h": 1.0,
        })

    return merged


def analyze_name_regions_with_ocr(ocr, video_path):
    """Run name detection with a pre-initialized OCR instance.

    Returns (masks, unique_texts) tuple.
    """
    return _analyze(ocr, video_path)


def _scan_range(ocr, video_path, start_sec, end_sec, interval, target_count=30):
    """Scan a time range for name regions. Returns (regions, num_sampled)."""
    all_regions = []
    found_any = False
    num_sampled = 0

    gen = sample_frames(video_path, start_sec=start_sec, end_sec=end_sec,
                        interval=interval)
    try:
        for sec, frame in gen:
            num_sampled += 1
            regions = detect_names_in_frame(ocr, frame)
            if regions:
                if not found_any:
                    print(f"  First names detected at {sec}s")
                    found_any = True
                all_regions.extend(regions)
                if len(all_regions) >= target_count:
                    print(f"  Enough samples collected at {sec}s")
                    break
    finally:
        gen.close()

    return all_regions, num_sampled


def _analyze(ocr, video_path):
    """Core analysis logic shared by public entry points.

    Returns (masks, unique_texts) where unique_texts is a set of detected
    role name strings.

    Scans 1100s-1400s first. If both sides aren't found, extends the scan
    to 1400s-2000s with a coarser interval to find late-appearing names.
    """
    # Primary scan: 1100s-1400s at 10s intervals
    print("Sampling frames (1100s-1400s at 10s intervals)...")
    all_regions, num_sampled = _scan_range(
        ocr, video_path, 1100, 1400, interval=10)
    print(f"Processed {num_sampled} frames")

    # Check if we have both sides covered
    sides_found = set(r["side"] for r in all_regions)
    missing_sides = {"left", "right"} - sides_found

    if missing_sides and all_regions:
        # Found names on one side but not the other — extend scan
        print(f"  Missing {', '.join(missing_sides)} side. "
              f"Extending scan (1400s-2000s at 30s intervals)...")
        extra_regions, extra_sampled = _scan_range(
            ocr, video_path, 1400, 2000, interval=30, target_count=15)
        num_sampled += extra_sampled
        # Only add regions from the missing side(s)
        for r in extra_regions:
            if r["side"] in missing_sides:
                all_regions.append(r)
        print(f"  Extended scan: {extra_sampled} more frames")

    if not all_regions:
        # No names at all — try the extended range before falling back
        print("  No names in primary range. Trying extended scan "
              "(1400s-2000s at 30s intervals)...")
        all_regions, extra_sampled = _scan_range(
            ocr, video_path, 1400, 2000, interval=30, target_count=15)
        num_sampled += extra_sampled
        print(f"  Extended scan: {extra_sampled} frames")

    if not all_regions:
        print("No role names detected. Using default mask positions.")
        return [
            {"x": 0.05, "y": 0, "w": 0.08, "h": 1.0},
            {"x": 0.87, "y": 0, "w": 0.08, "h": 1.0},
        ], set()

    unique_texts = set(r["text"] for r in all_regions)
    print(f"Detected texts: {', '.join(unique_texts)}")

    merged = merge_regions(all_regions)
    print(f"Merged into {len(merged)} mask region(s)")
    for m in merged:
        print(f"  x={m['x']:.3f} y={m['y']:.3f} w={m['w']:.3f} h={m['h']:.3f}")
    return merged, unique_texts


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
    """Main entry point: sample frames, OCR, merge regions."""
    print("Initializing PaddleOCR...")
    ocr = _init_ocr()
    masks, _texts = _analyze(ocr, video_path)
    return masks


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Detect character name regions")
    parser.add_argument("video_path", help="Path to video file")
    args = parser.parse_args()

    regions = analyze_name_regions(args.video_path)
    print(json.dumps(regions, indent=2))
