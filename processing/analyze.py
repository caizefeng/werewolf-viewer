#!/usr/bin/env python3
"""Main analysis pipeline: orchestrates night detection and name detection."""

import argparse
import json
import os
import subprocess
import sys
import tempfile

from analyze_night import analyze_night_phases


def _print_log_tail(log_path, lines=15):
    """Print the last lines of a subprocess log for error context."""
    try:
        with open(log_path, "r", errors="replace") as f:
            tail = [l.rstrip() for l in f if l.strip()][-lines:]
    except OSError:
        return
    for l in tail:
        print(f"    {l}")


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
        from analyze_names import analyze_name_regions_full
        name_result = analyze_name_regions_full(video_path)
        print()
    else:
        # Parallel: run name detection as a subprocess (separate GIL + process)
        # while night detection runs in the main process with threaded scanning
        name_tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, dir=video_dir)
        name_tmp.close()
        name_log_path = name_tmp.name + ".log"

        name_result = None
        try:
            # Subprocess output goes to a log file (avoids interleaving with
            # night detection output; printed on failure for diagnosis)
            with open(name_log_path, "w") as log_f:
                name_proc = subprocess.Popen(
                    [venv_python, "-c",
                     f"import json; from analyze_names import analyze_name_regions_full; "
                     f"r = analyze_name_regions_full({video_path!r}); "
                     f"open({name_tmp.name!r}, 'w').write(json.dumps(r, default=str))"],
                    cwd=processing_dir,
                    stdout=log_f, stderr=subprocess.STDOUT,
                )

            # Run night detection in main process
            print("--- Night Phase Detection ---")
            try:
                night_phases = analyze_night_phases(video_path, num_workers=num_workers)
            except BaseException:
                name_proc.kill()  # don't leave the OCR subprocess orphaned
                raise
            finally:
                name_proc.wait()
            print()

            print("--- Character Name Detection ---")
            if name_proc.returncode == 0:
                try:
                    with open(name_tmp.name, "r") as f:
                        name_result = json.load(f)
                    print(f"  Name detection completed "
                          f"({len(name_result['name_masks'])} mask regions, "
                          f"{sum(len(v) for v in name_result.get('role_map', {}).values())} players mapped)")
                except (OSError, ValueError):
                    print("  Name detection output unreadable, retrying...")
            else:
                print(f"Name detection subprocess failed (exit {name_proc.returncode}):")
                _print_log_tail(name_log_path)
                print("Retrying in-process...")
            if name_result is None:
                from analyze_names import analyze_name_regions_full
                name_result = analyze_name_regions_full(video_path)
        finally:
            for p in (name_tmp.name, name_log_path):
                try:
                    os.unlink(p)
                except OSError:
                    pass
        print()

    # Write metadata
    metadata = {
        "video_file": video_file,
        "night_phases": night_phases,
        "name_masks": name_result["name_masks"],
        "role_map": name_result.get("role_map", {}),
        # True when the broadcast itself hides roles (未知 labels): the
        # viewer turns masks/overlay off and disables role reveal
        "close_vision": bool(name_result.get("close_vision", False)),
    }

    metadata_path = os.path.join(video_dir, "metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    print("=" * 60)
    print(f"Analysis complete!")
    print(f"  Night phases found: {len(night_phases)}")
    print(f"  Name mask regions: {len(name_result['name_masks'])}")
    if name_result.get("close_vision"):
        print("  Close-vision game: yes (masks/role reveal disabled in viewer)")
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
