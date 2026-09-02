#!/usr/bin/env python3
"""Download a YouTube video using yt-dlp."""

import argparse
import json
import os
import subprocess
import sys


def _yt_dlp_bin():
    """Prefer the venv's yt-dlp (kept up to date via pip) over whatever is
    on PATH — YouTube extraction breaks quickly on stale versions."""
    candidate = os.path.join(os.path.dirname(sys.executable), "yt-dlp")
    return candidate if os.path.exists(candidate) else "yt-dlp"


def download_video(video_id, output_dir, quality="1080"):
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "video.mp4")
    # yt-dlp/ffmpeg write to this name; renamed to video.mp4 only on success
    # so an interrupted merge never leaves a truncated video.mp4 that would
    # block re-download
    partial_path = os.path.join(output_dir, "video.download.mp4")
    info_path = os.path.join(output_dir, "info.json")

    if os.path.exists(output_path):
        print(f"Video already exists at {output_path}, skipping download.")
        print("Delete the file to re-download.")
        return output_path

    url = f"https://www.youtube.com/watch?v={video_id}"
    yt_dlp = _yt_dlp_bin()

    # Fetch video title
    try:
        result = subprocess.run(
            [yt_dlp, "--print", "title", "--no-download", url],
            capture_output=True, text=True, check=True,
        )
        title = result.stdout.strip()
    except Exception:
        title = video_id

    # Save info
    with open(info_path, "w", encoding="utf-8") as f:
        json.dump({"title": title, "video_id": video_id}, f, ensure_ascii=False, indent=2)
    print(f"Title: {title}")

    # Format selection based on quality (no fallback to pre-merged 360p)
    if quality == "1080":
        format_spec = "bestvideo[height<=1080][fps<=60]+bestaudio"
    else:
        format_spec = "bestvideo[height<=720][fps<=60]+bestaudio"

    base_cmd = [
        yt_dlp,
        "-f", format_spec,
        "--merge-output-format", "mp4",
        "--concurrent-fragments", "8",
        "-o", partial_path,
        url,
    ]

    # YouTube keeps changing which player clients serve downloadable
    # https formats without a PO token, and yt-dlp rotates its default
    # clients accordingly (2026-08: visionos). Use the defaults first, and
    # fall back to web_embedded, which has worked when the defaults were
    # gated (2026-07). Stream URLs also get invalidated intermittently
    # (HTTP 403 a few % in) under YouTube's PO-token experiments, so each
    # strategy gets two tries with a fresh extraction.
    strategies = [
        ("default clients", []),
        ("web_embedded client", ["--extractor-args", "youtube:player_client=web_embedded"]),
    ]
    tries_per_strategy = 2

    print(f"Downloading {url} at {quality}p...")
    last_err = None
    for label, extra_args in strategies:
        for attempt in range(1, tries_per_strategy + 1):
            print(f"[download.py] {label}, attempt {attempt}/{tries_per_strategy}")
            try:
                subprocess.run([base_cmd[0]] + extra_args + base_cmd[1:], check=True)
                last_err = None
                break
            except subprocess.CalledProcessError as e:
                last_err = e
                print(f"[download.py] {label} attempt {attempt} failed (exit {e.returncode})")
        if last_err is None:
            break
    if last_err is not None:
        raise last_err
    os.replace(partial_path, output_path)
    print(f"Downloaded to {output_path}")
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download werewolf tournament video")
    parser.add_argument("--video-id", default="65R0r19JyYk", help="YouTube video ID")
    parser.add_argument("--quality", default="1080", choices=["720", "1080"], help="Video quality")
    parser.add_argument("--output-dir", default=None, help="Output directory")
    args = parser.parse_args()

    if args.output_dir is None:
        args.output_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "videos", args.video_id,
        )

    download_video(args.video_id, args.output_dir, args.quality)
