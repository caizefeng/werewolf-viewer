#!/usr/bin/env python3
"""Refresh role_map / hidden_roles of downloaded videos without re-running
night detection and without touching manual edits.

Re-analyze (analyze.py, the library's ↻) replaces everything in
metadata.json, including hand-corrected night phases and masks. This tool
only re-scans the sidebar roles (about 2 minutes per video) and rewrites
role_map and hidden_roles; name_masks are refreshed only when the user never
edited them (no original_name_masks field).

Usage: python3 processing/update_role_maps.py            # every video with metadata
       python3 processing/update_role_maps.py ID [ID...] # specific videos
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_names import analyze_name_regions_full

VIDEOS_DIR = os.environ.get("WEREWOLF_VIDEOS_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "videos")


def update(video_id):
    video_path = os.path.join(VIDEOS_DIR, video_id, "video.mp4")
    meta_path = os.path.join(VIDEOS_DIR, video_id, "metadata.json")
    if not os.path.exists(video_path) or not os.path.exists(meta_path):
        print(f"{video_id}: skipped (no video.mp4 / metadata.json)")
        return False
    t0 = time.time()
    result = analyze_name_regions_full(video_path)
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    meta["role_map"] = result["role_map"]
    meta["hidden_roles"] = result["hidden_roles"]
    if "original_name_masks" not in meta:
        meta["name_masks"] = result["name_masks"]
    tmp = meta_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    os.replace(tmp, meta_path)
    rows = sum(len(v) for v in result["role_map"].values())
    print(f"{video_id}: role_map {rows} rows, hidden_roles={result['hidden_roles']} ({time.time() - t0:.0f}s)")
    return True


def main():
    parser = argparse.ArgumentParser(description="Refresh role maps without re-running night detection")
    parser.add_argument("video_ids", nargs="*", help="video IDs (default: all with metadata.json)")
    args = parser.parse_args()
    ids = args.video_ids or sorted(
        d for d in os.listdir(VIDEOS_DIR)
        if os.path.exists(os.path.join(VIDEOS_DIR, d, "metadata.json")))
    done = sum(1 for vid in ids if update(vid))
    print(f"Updated {done}/{len(ids)} video(s)")


if __name__ == "__main__":
    main()
