#!/usr/bin/env python3
"""Demo stand-in for download.py: copies a rendered demo game into the
library over a few seconds (so the download bar has something to show),
then the real analysis runs on it. Same arguments as download.py."""
import argparse
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video-id", required=True)
    ap.add_argument("--quality", default="1080")
    ap.add_argument("--output-dir", required=True)
    args = ap.parse_args()
    src_dir = os.path.join(os.environ.get("WEREWOLF_DEMO_SOURCE", os.path.join(HERE, "library")), args.video_id)
    src = os.path.join(src_dir, "video.mp4")
    if not os.path.exists(src):
        print(f"ERROR: no demo game {args.video_id} under {src_dir}")
        sys.exit(1)
    os.makedirs(args.output_dir, exist_ok=True)
    with open(os.path.join(src_dir, "info.json"), encoding="utf-8") as f:
        info = json.load(f)
    print(f"Title: {info['title']}")
    tmp = os.path.join(args.output_dir, "video.download.mp4")
    size = os.path.getsize(src)
    with open(src, "rb") as fi, open(tmp, "wb") as fo:
        done = 0
        while True:
            chunk = fi.read(max(size // 10, 1 << 20))
            if not chunk:
                break
            fo.write(chunk)
            done += len(chunk)
            print(f"[download] {100 * done // size}%", flush=True)
            time.sleep(1.2)
    os.replace(tmp, os.path.join(args.output_dir, "video.mp4"))
    with open(os.path.join(args.output_dir, "info.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    print(f"Downloaded to {os.path.join(args.output_dir, 'video.mp4')}")


if __name__ == "__main__":
    main()
