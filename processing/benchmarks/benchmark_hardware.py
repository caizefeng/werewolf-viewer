#!/usr/bin/env python3
"""Time full analyses on this machine: the figures in the README's
"Processing time" section (wall time, decode time, CPU time, peak memory of
analyze.py together with its OCR subprocess).

    python3 processing/benchmarks/benchmark_hardware.py VIDEO_ID [VIDEO_ID ...]
    python3 processing/benchmarks/benchmark_hardware.py ID1 ID2 --together
    python3 processing/benchmarks/benchmark_hardware.py ID --prefix "taskpolicy -c background"

--together runs the games side by side, as the server's two analysis slots
do; on macOS the taskpolicy prefix keeps a run on the efficiency cores. Put
"--" before IDs that start with a dash. Each game is analysed through a
symlink in a temporary library, so its real metadata.json (and any edits in
it) is never touched.
"""

import argparse
import os
import platform
import resource
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PYTHON = os.path.join(ROOT, "processing", "venv", "bin", "python3")

try:
    import psutil   # installed with PaddleOCR; without it memory isn't reported
except ImportError:
    psutil = None


def machine():
    cpu = platform.processor() or platform.machine()
    try:
        if sys.platform == "darwin":
            cpu = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                                 capture_output=True, text=True).stdout.strip() or cpu
        else:
            with open("/proc/cpuinfo") as f:
                cpu = next((l.split(":", 1)[1].strip() for l in f if l.startswith("model name")), cpu)
    except OSError:
        pass
    mem = f", {psutil.virtual_memory().total / 2**30:.0f} GB" if psutil else ""
    return f"{cpu}, {os.cpu_count()} cores{mem}, {platform.platform()}"


def video_info(path):
    import cv2
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 1
    dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
    fmt = f"{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}p{fps:.0f}"
    cap.release()
    return dur, fmt


def fmt_min(s):
    return "-" if s is None else f"{s / 60:.1f} min"


def fmt_dur(s):
    h, rem = divmod(int(s), 3600)
    return f"{h}:{rem // 60:02d}:{rem % 60:02d}"


class Run:
    """One analyze.py process on a symlinked copy of a game."""

    def __init__(self, video_id, library, prefix, extra):
        self.video_id = video_id
        self.src = os.path.join(ROOT, "videos", video_id, "video.mp4")
        os.makedirs(os.path.join(library, video_id))
        os.symlink(self.src, os.path.join(library, video_id, "video.mp4"))
        cmd = (shlex.split(prefix) + [PYTHON, os.path.join(ROOT, "processing", "analyze.py"),
                                      f"--video-id={video_id}"] + shlex.split(extra))
        env = dict(os.environ, WEREWOLF_VIDEOS_DIR=library, PYTHONUNBUFFERED="1")
        self.start = time.perf_counter()
        self.proc = subprocess.Popen(cmd, cwd=ROOT, env=env, text=True,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.decode = self.wall = None
        self.peak = 0
        self.tail = []
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        for line in self.proc.stdout:
            if self.decode is None and "Sampled" in line:   # the corner scan is done
                self.decode = time.perf_counter() - self.start
            self.tail = (self.tail + [line.rstrip()])[-15:]

    def poll(self):
        """Record the end time and peak memory; return the tree's RSS in bytes."""
        if self.proc.poll() is not None:
            if self.wall is None:
                self.wall = time.perf_counter() - self.start
            return 0
        if psutil is None:
            return 0
        rss = 0
        try:
            root = psutil.Process(self.proc.pid)
            for p in [root] + root.children(recursive=True):
                try:
                    rss += p.memory_info().rss
                except psutil.Error:
                    pass
        except psutil.Error:
            return 0
        self.peak = max(self.peak, rss)
        return rss


def main():
    ap = argparse.ArgumentParser(description="Time full analyses on this machine")
    ap.add_argument("video_ids", nargs="+", metavar="VIDEO_ID", help="downloaded games (videos/<id>/video.mp4)")
    ap.add_argument("--together", action="store_true", help="analyse all the games at once")
    ap.add_argument("--prefix", default="", help='command prefix, e.g. "taskpolicy -c background"')
    ap.add_argument("--args", default="", help='extra analyze.py arguments, e.g. "--sequential --workers 1"')
    a = ap.parse_args()
    missing = [v for v in a.video_ids if not os.path.exists(os.path.join(ROOT, "videos", v, "video.mp4"))]
    if missing:
        sys.exit(f"Not downloaded: {', '.join(missing)}")

    print(f"Machine: {machine()}")
    library = tempfile.mkdtemp(prefix="werewolf-bench-")
    try:
        for group in ([a.video_ids] if a.together else [[v] for v in a.video_ids]):
            before = resource.getrusage(resource.RUSAGE_CHILDREN)
            runs = [Run(v, library, a.prefix, a.args) for v in group]
            peak = 0
            while True:
                peak = max(peak, sum(r.poll() for r in runs))
                if all(r.wall is not None for r in runs):
                    break
                time.sleep(0.5)
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            cpu = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
            for r in runs:
                r.reader.join()
                dur, fmt = video_info(r.src)
                mem = f"  peak {r.peak / 2**30:.1f} GB" if psutil else ""
                status = "" if r.proc.returncode == 0 else f"  FAILED (exit {r.proc.returncode})"
                print(f"{r.video_id:<13} {fmt_dur(dur)} {fmt}  {os.path.getsize(r.src) / 1e9:.1f} GB  "
                      f"analysis {fmt_min(r.wall)} (decode {fmt_min(r.decode)}){mem}{status}")
                if r.proc.returncode:
                    print("\n".join(f"    {l}" for l in r.tail))
            wall = max(r.wall for r in runs)
            together = f", together peak {peak / 2**30:.1f} GB" if psutil and len(runs) > 1 else ""
            print(f"  CPU {cpu / 60:.1f} min, {cpu / wall:.1f} cores busy on average{together}")
    finally:
        shutil.rmtree(library, ignore_errors=True)


if __name__ == "__main__":
    main()
