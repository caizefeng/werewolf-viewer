#!/usr/bin/env python3
"""Main analysis pipeline: orchestrates night detection and name detection."""

import argparse
import json
import os
import subprocess
import sys
import tempfile

from analyze_night import analyze_night_phases


def run_analysis(video_path, sequential=False, num_workers=0):
    """Run full analysis pipeline and write metadata.json.

    sequential: if True, run night + name detection one after the other.
    num_workers: passed to night detection (0=auto, 1=sequential scan).
    """
    video_path = os.path.abspath(video_path)
    video_dir = os.path.dirname(video_path)
    video_file = os.path.basename(video_path)
    processing_dir = os.path.dirname(os.path.abspath(__file__))
    venv_python = os.path.join(processing_dir, "venv", "bin", "python3")

    print("=" * 60)
    print("WEREWOLF VIEWER - Video Analysis Pipeline")
    print("=" * 60)
    print(f"Video: {video_path}")
    if not sequential:
        print("Mode: parallel (night + name detection in separate processes)")
    print()

    if sequential:
        # Original sequential execution
        print("--- Night Phase Detection ---")
        night_phases = analyze_night_phases(video_path, num_workers=num_workers)
        print()

        print("--- Character Name Detection ---")
        from analyze_names import analyze_name_regions
        name_masks = analyze_name_regions(video_path)
        print()
    else:
        # Parallel: run name detection as a subprocess (separate GIL + process)
        # while night detection runs in the main process with threaded scanning
        name_tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, dir=video_dir)
        name_tmp.close()

        env = os.environ.copy()
        env["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
        name_proc = subprocess.Popen(
            [venv_python, "-c",
             f"import json; from analyze_names import analyze_name_regions; "
             f"r = analyze_name_regions({video_path!r}); "
             f"open({name_tmp.name!r}, 'w').write(json.dumps(r, default=str))"],
            cwd=processing_dir, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

        # Run night detection in main process
        print("--- Night Phase Detection ---")
        night_phases = analyze_night_phases(video_path, num_workers=num_workers)
        print()

        # Wait for name detection subprocess
        print("--- Character Name Detection ---")
        name_proc.wait()
        if name_proc.returncode != 0:
            print(f"Name detection subprocess failed (exit {name_proc.returncode}), retrying...")
            from analyze_names import analyze_name_regions
            name_masks = analyze_name_regions(video_path)
        else:
            with open(name_tmp.name, "r") as f:
                name_masks = json.load(f)
            print(f"  Name detection completed ({len(name_masks)} mask regions)")
        os.unlink(name_tmp.name)
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
    parser.add_argument(
        "--sequential", action="store_true",
        help="Run night + name detection sequentially (default: parallel)",
    )
    parser.add_argument(
        "--workers", type=int, default=0,
        help="Number of parallel workers for night scan (0=auto, 1=sequential)",
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

    run_analysis(video_path, sequential=args.sequential, num_workers=args.workers)
