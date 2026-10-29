#!/usr/bin/env python3
"""Download a YouTube video using yt-dlp."""

import argparse
import json
import os
import subprocess
import sys


# The downloads are AV1 video with Opus audio (YouTube's best 1080p60), which
# Safari, and so every browser on an iPhone, cannot play: AV1 needs an AV1
# decoder (iPhone 15 Pro and later), and WebKit takes no Opus in MP4 at all.
# Each game also gets YouTube's own H.264 + AAC version under this name; the
# player serves it to such browsers. Analysis keeps using video.mp4.
H264_COPY = "video.h264.mp4"
H264_FORMAT = "bestvideo[vcodec^=avc1][height<=1080][fps<=60]+bestaudio[acodec^=mp4a]"


def _yt_dlp_bin():
    """Prefer the venv's yt-dlp (kept up to date via pip) over whatever is
    on PATH — YouTube extraction breaks quickly on stale versions."""
    candidate = os.path.join(os.path.dirname(sys.executable), "yt-dlp")
    return candidate if os.path.exists(candidate) else "yt-dlp"


def _run_yt_dlp(base_cmd):
    """Run a yt-dlp command with the client fallbacks below; raises the last
    CalledProcessError when every attempt fails.

    YouTube keeps changing which player clients serve downloadable https
    formats without a PO token, and yt-dlp rotates its default clients
    accordingly (2026-08: visionos). Use the defaults first, and fall back
    to web_embedded, which has worked when the defaults were gated
    (2026-07). Stream URLs also get invalidated intermittently (HTTP 403 a
    few % in) under YouTube's PO-token experiments, so each strategy gets
    two tries with a fresh extraction."""
    strategies = [
        ("default clients", []),
        ("web_embedded client", ["--extractor-args", "youtube:player_client=web_embedded"]),
    ]
    tries_per_strategy = 2
    last_err = None
    for label, extra_args in strategies:
        for attempt in range(1, tries_per_strategy + 1):
            print(f"[download.py] {label}, attempt {attempt}/{tries_per_strategy}", flush=True)
            try:
                subprocess.run([base_cmd[0]] + extra_args + base_cmd[1:], check=True)
                return
            except subprocess.CalledProcessError as e:
                last_err = e
                print(f"[download.py] {label} attempt {attempt} failed (exit {e.returncode})", flush=True)
    raise last_err


def download_h264_copy(video_id, output_dir):
    """Fetch the game's H.264 + AAC version next to video.mp4 (see
    H264_COPY). Returns its path, or None when YouTube has no such format or
    the download fails: not fatal, the game still plays wherever AV1 does."""
    path = os.path.join(output_dir, H264_COPY)
    if os.path.exists(path):
        print(f"H.264 copy already at {path}")
        return path
    partial = os.path.join(output_dir, "video.h264.download.mp4")
    url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"Downloading the H.264 copy (for iPhones) of {url}...", flush=True)
    try:
        _run_yt_dlp([
            _yt_dlp_bin(),
            "-f", H264_FORMAT,
            "--merge-output-format", "mp4",
            # moov first: a phone starts playing without fetching the end
            "--postprocessor-args", "Merger+ffmpeg_o:-movflags +faststart",
            "--concurrent-fragments", "8",
            "-o", partial,
            url,
        ])
    except subprocess.CalledProcessError:
        print(f"[download.py] WARNING: no H.264 copy for {video_id}; browsers without AV1 (iPhones) "
              "cannot play it", flush=True)
        return None
    os.replace(partial, path)
    print(f"H.264 copy at {path}")
    return path


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
        download_h264_copy(video_id, output_dir)
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

    print(f"Downloading {url} at {quality}p...")
    _run_yt_dlp(base_cmd)
    os.replace(partial_path, output_path)
    print(f"Downloaded to {output_path}")
    download_h264_copy(video_id, output_dir)
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download werewolf tournament video")
    parser.add_argument("--video-id", default=None, help="YouTube video ID (default 65R0r19JyYk)")
    parser.add_argument("--quality", default="1080", choices=["720", "1080"], help="Video quality")
    parser.add_argument("--output-dir", default=None, help="Output directory")
    parser.add_argument("--h264-copy", action="store_true",
                        help="only fetch the H.264 copy (for iPhones) of a game already downloaded")
    parser.add_argument("--all", action="store_true",
                        help="with --h264-copy: every analysed game in videos/ that has no copy yet")
    args = parser.parse_args()
    videos_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "videos")

    if args.h264_copy:
        if not args.all and not args.video_id:
            parser.error("--h264-copy needs --video-id or --all")
        if args.all:
            ids = sorted(d for d in os.listdir(videos_dir)
                         if os.path.exists(os.path.join(videos_dir, d, "metadata.json"))
                         and not os.path.exists(os.path.join(videos_dir, d, H264_COPY)))
            dirs = [(i, os.path.join(videos_dir, i)) for i in ids]
        else:
            dirs = [(args.video_id, args.output_dir or os.path.join(videos_dir, args.video_id))]
        missing = [i for i, d in dirs if download_h264_copy(i, d) is None]
        if missing:
            sys.exit(f"no H.264 copy for: {', '.join(missing)}")
        sys.exit(0)

    args.video_id = args.video_id or "65R0r19JyYk"
    if args.output_dir is None:
        args.output_dir = os.path.join(videos_dir, args.video_id)

    download_video(args.video_id, args.output_dir, args.quality)
