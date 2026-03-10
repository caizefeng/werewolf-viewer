#!/usr/bin/env python3
"""Main analysis pipeline: orchestrates night detection and name detection."""

import argparse
import json
import os
import sys

from analyze_night import analyze_night_phases
from analyze_names import analyze_name_regions


def run_analysis(video_path):
    """Run full analysis pipeline and write metadata.json."""
    video_dir = os.path.dirname(video_path)
    video_file = os.path.basename(video_path)

    print("=" * 60)
    print("WEREWOLF VIEWER - Video Analysis Pipeline")
    print("=" * 60)
    print(f"Video: {video_path}")
    print()

    # Step 1: Night phase detection
    print("--- Night Phase Detection ---")
    night_phases = analyze_night_phases(video_path)
    print()

    # Step 2: Character name detection
    print("--- Character Name Detection ---")
    name_masks = analyze_name_regions(video_path)
    print()

    # Write metadata
    metadata = {
        "video_file": video_file,
        "night_phases": night_phases,
        "name_masks": name_masks,
    }

    metadata_path = os.path.join(video_dir, "metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    print("=" * 60)
    print(f"Analysis complete!")
    print(f"  Night phases found: {len(night_phases)}")
    print(f"  Name mask regions: {len(name_masks)}")
    print(f"  Metadata saved to: {metadata_path}")
    print("=" * 60)

    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze werewolf tournament video")
    parser.add_argument(
        "--video-id", default="65R0r19JyYk",
        help="YouTube video ID (used to find video path)",
    )
    parser.add_argument(
        "--video-path", default=None,
        help="Direct path to video file (overrides --video-id)",
    )
    args = parser.parse_args()

    if args.video_path:
        video_path = args.video_path
    else:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        video_path = os.path.join(base_dir, "videos", args.video_id, "video.mp4")

    if not os.path.exists(video_path):
        print(f"Error: Video not found at {video_path}")
        print("Run download.py first to download the video.")
        sys.exit(1)

    run_analysis(video_path)
