"""Browser end-to-end test harness.

Each suite runs against a throwaway Vite dev server (the same web/ code as
the real one) serving a fresh copy of the synthetic demo library, so tests
can click, bookmark, edit, re-analyse and delete freely without ever
touching videos/. The demo games are rendered by
processing/demo/make_demo_video.py and analysed once by the real pipeline;
both are cached under tests/.cache/ (delete it, or pass --fresh, after
changing the renderer or the analysis).
"""
import contextlib
import json
import os
import shutil
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / "processing" / "venv" / "bin" / "python3"
CACHE = ROOT / "tests" / ".cache"
RENDERED = ROOT / "processing" / "demo" / "library"
ANALYZED = CACHE / "demo-analyzed"
# (game id, duration s) as rendered by make_demo_video.py; g2 is hidden-roles
G1, G2, G3 = "demoS01E01g1", "demoS01E01g2", "demoS01E02g1"
DEMO_IDS = (G1, G2, G3)
DURATION = {G1: 360, G2: 180, G3: 240}
CHROMIUM_ARGS = ["--autoplay-policy=no-user-gesture-required", "--mute-audio"]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def prepare_demo_library(fresh=False):
    """Rendered and analysed demo games in tests/.cache/demo-analyzed."""
    if fresh and ANALYZED.exists():
        shutil.rmtree(ANALYZED)
    CACHE.mkdir(parents=True, exist_ok=True)
    if not all((RENDERED / v / "video.mp4").exists() for v in DEMO_IDS):
        log("rendering the demo games (ffmpeg, about a minute)")
        subprocess.run([str(PY), "processing/demo/make_demo_video.py", str(RENDERED)], cwd=ROOT, check=True)
    env = {**os.environ, "WEREWOLF_VIDEOS_DIR": str(ANALYZED), "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True"}
    for v in DEMO_IDS:
        d = ANALYZED / v
        if (d / "metadata.json").exists():
            continue
        d.mkdir(parents=True, exist_ok=True)
        for f in ("video.mp4", "info.json"):
            shutil.copy2(RENDERED / v / f, d / f)
        log(f"analysing {v} with the real pipeline (about 2 minutes)")
        with open(CACHE / f"analyze-{v}.log", "w") as out:
            subprocess.run([str(PY), "processing/analyze.py", f"--video-id={v}"], cwd=ROOT, env=env,
                           check=True, stdout=out, stderr=subprocess.STDOUT)
    return ANALYZED


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def demo_server(library):
    """A Vite dev server on a fresh copy of `library`; yields (base_url, run_dir)."""
    run_dir = CACHE / f"run-{os.getpid()}-{int(time.time() * 1000)}"
    shutil.copytree(library, run_dir)
    port = _free_port()
    env = {**os.environ, "WEREWOLF_VIDEOS_DIR": str(run_dir), "WEREWOLF_DEMO": "1",
           "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True"}
    cmd = ('eval "$(fnm env --shell bash)" && cd web && fnm use --silent-if-unchanged >/dev/null 2>&1; '
           'corepack enable >/dev/null 2>&1; '
           f"exec pnpm exec vite --host 127.0.0.1 --port {port} --strictPort")
    log_path = CACHE / f"server-{port}.log"
    out = open(log_path, "w")
    proc = subprocess.Popen(["bash", "-c", cmd], cwd=ROOT, env=env, stdout=out, stderr=subprocess.STDOUT,
                            start_new_session=True)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 60
        while True:
            try:
                urllib.request.urlopen(base + "/api/videos", timeout=2).read()
                break
            except Exception:
                if proc.poll() is not None or time.time() > deadline:
                    raise RuntimeError(f"demo server did not start, see {log_path}")
                time.sleep(0.5)
        log(f"demo server on {base} serving {run_dir.name}")
        yield base, run_dir
    finally:
        wait_jobs_idle(base, timeout=600)
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=10)
        except Exception:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                pass
        out.close()
        shutil.rmtree(run_dir, ignore_errors=True)


def api(base, path, body=None, headers=None, raw=None, timeout=30):
    """(status, parsed JSON or None) for GET (no body) or POST."""
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    hdrs = {"Content-Type": "application/json"} if data is not None else {}
    hdrs.update(headers or {})
    req = urllib.request.Request(base + path, data=data, headers=hdrs, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None


def wait_jobs_idle(base, timeout=900):
    """Block until the server reports no active job (or is gone)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            st, data = api(base, "/api/job-status", timeout=5)
        except Exception:
            return
        if st != 200 or not data.get("active"):
            return
        time.sleep(3)


def read_state(run_dir, vid):
    """A game's viewer_state.json as a dict, None if absent, "CORRUPT" if unreadable."""
    p = Path(run_dir) / vid / "viewer_state.json"
    try:
        return json.loads(p.read_text())
    except FileNotFoundError:
        return None
    except ValueError:
        return "CORRUPT"


class Checks:
    def __init__(self, suite):
        self.suite = suite
        self.results = []

    def check(self, name, ok, detail=""):
        ok = bool(ok)
        self.results.append((name, ok, detail))
        print(f"{'PASS' if ok else 'FAIL'} {name}" + (f"  [{detail}]" if detail else ""), flush=True)
        return ok

    @property
    def failed(self):
        return [r for r in self.results if not r[1]]


def watch_errors(page):
    """Collect page errors and console errors on a page."""
    errors = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error" else None)
    return errors


def wrapper_box(page):
    return page.evaluate("(() => { const b = document.getElementById('video-wrapper').getBoundingClientRect();"
                         " return {x: b.x, y: b.y, w: b.width, h: b.height}; })()")


def show_controls(page):
    """The controls auto-hide; a real user moves the mouse over the player first."""
    w = wrapper_box(page)
    page.mouse.move(w["x"] + w["w"] / 2, w["y"] + w["h"] / 2)
    page.wait_for_timeout(150)
    return w


def ctl(page, selector):
    show_controls(page)
    page.click(selector)


def seek_by_bar(page, fraction):
    """Seek like a user: click the progress bar at `fraction` of its width."""
    show_controls(page)
    b = page.evaluate("(() => { const r = document.getElementById('progress-bar').getBoundingClientRect();"
                      " return {x: r.x, y: r.y, w: r.width, h: r.height}; })()")
    page.mouse.click(b["x"] + b["w"] * fraction, b["y"] + b["h"] / 2)


def open_panel(page, side="right"):
    w = wrapper_box(page)
    x = w["x"] + w["w"] - 6 if side == "right" else w["x"] + 6
    page.mouse.move(x, w["y"] + w["h"] / 2 - 30)
    page.wait_for_timeout(700)


def park_mouse(page):
    w = wrapper_box(page)
    page.mouse.move(w["x"] + w["w"] / 2, max(2, w["y"] - 40))
    page.wait_for_timeout(300)


def active_id(page):
    return page.evaluate("document.querySelector('#video-list li.lib-item.active')?.dataset.id || null")


def current_time(page):
    return page.evaluate("document.getElementById('video').currentTime")


def open_app(page, base):
    page.goto(base + "/", wait_until="networkidle")
    # attached, not visible: the bookmark filter may hide the first rows
    page.wait_for_selector("#video-list li.lib-item", state="attached")
    page.wait_for_timeout(1500)
