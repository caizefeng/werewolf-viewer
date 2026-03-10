#!/usr/bin/env python3
"""Detect character role name regions using PaddleOCR."""

import argparse
import json
import os

import cv2
import numpy as np
from paddleocr import PaddleOCR


ROLE_NAMES = [
    "狼人", "狼王", "白狼王", "预言家", "女巫", "猎人",
    "白痴", "守卫", "村民", "平民", "通灵师", "丘比特",
    "盗贼", "长老", "骑士", "野孩子", "石像鬼", "混血儿",
]


def sample_frames(video_path, start_sec=60, end_sec=300, interval=1):
    """Sample frames from video at given interval."""
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps
    end_sec = min(end_sec, duration)
    frames = []
    for sec in range(int(start_sec), int(end_sec), interval):
        frame_num = int(sec * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ret, frame = cap.read()
        if ret:
            frames.append((sec, frame))
    cap.release()
    return frames


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


def analyze_name_regions(video_path):
    """Main entry point: sample frames, OCR, merge regions."""
    print("Initializing PaddleOCR...")
    ocr = PaddleOCR(lang="ch")

    # Start from 1000s (after intro) and sample every 10s
    print("Sampling frames (1000s-1300s at 10s intervals)...")
    frames = sample_frames(video_path, start_sec=1000, end_sec=1300, interval=10)
    print(f"Sampled {len(frames)} frames")

    all_regions = []
    found_any = False

    for sec, frame in frames:
        regions = detect_names_in_frame(ocr, frame)
        if regions:
            if not found_any:
                print(f"  First names detected at {sec}s")
                found_any = True
            all_regions.extend(regions)
            if len(all_regions) >= 30:
                print(f"  Enough samples collected at {sec}s")
                break

    if not all_regions:
        print("No role names detected. Using default mask positions.")
        return [
            {"x": 0.05, "y": 0, "w": 0.08, "h": 1.0},
            {"x": 0.87, "y": 0, "w": 0.08, "h": 1.0},
        ]

    unique_texts = set(r["text"] for r in all_regions)
    print(f"Detected texts: {', '.join(unique_texts)}")

    merged = merge_regions(all_regions)
    print(f"Merged into {len(merged)} mask region(s)")
    for m in merged:
        print(f"  x={m['x']:.3f} y={m['y']:.3f} w={m['w']:.3f} h={m['h']:.3f}")
    return merged


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Detect character name regions")
    parser.add_argument("video_path", help="Path to video file")
    args = parser.parse_args()

    regions = analyze_name_regions(args.video_path)
    print(json.dumps(regions, indent=2))
