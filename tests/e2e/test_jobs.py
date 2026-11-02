"""Jobs and the files they hold: a stop ends everything the job started (a
process group on macOS and Linux, a process tree on Windows, where a file stays
locked until its process has gone), a game can be deleted while a browser
streams it, and a save waits out a reader holding the file open."""
import threading
import time
import urllib.request

import psutil

from harness import G1, G2, G3, api, log, read_state


def _job(base, vid):
    return next((j for j in api(base, "/api/job-status")[1]["jobs"] if j["videoId"] == vid), None)


def _procs(vid):
    """Command lines of the running processes that name the game."""
    found = []
    for p in psutil.process_iter(["cmdline"]):
        cmd = " ".join(p.info["cmdline"] or [])
        if vid in cmd:
            found.append(cmd)
    return found


def _wait(pred, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.1)
    return pred()


def run(base, run_dir, C, browser):
    game = run_dir / G3

    # ---------------- A stop during a download ----------------
    st, r = api(base, "/api/delete", {"videoId": G3})
    C.check("a game can be deleted to download it again", st == 200 and not game.exists(), f"{st} {r}")
    st, r = api(base, "/api/download", {"videoId": G3})
    C.check("a download starts", st == 200 and r["phase"] == "downloading", f"{st} {r}")
    C.check("...and its process runs", _wait(lambda: _procs(G3) and (game / "video.download.mp4").exists(), 20), str(_procs(G3))[:300])
    st, r = api(base, "/api/stop", {"videoId": G3})
    C.check("Stop stops the download", st == 200 and r["stopped"] is True and _job(base, G3)["stopped"] is True, f"{st} {r}")
    C.check("...ending its processes", _wait(lambda: not _procs(G3), 5), str(_procs(G3))[:300])
    C.check("...and removing the partial game", not game.exists(), str(list(game.glob("*")) if game.exists() else ""))

    # ---------------- A stop during an analysis ----------------
    st, r = api(base, "/api/download", {"videoId": G3})
    C.check("the download can start again at once", st == 200 and r["started"] is True, f"{st} {r}")
    log("downloading a demo game again (about 15 s)")
    C.check("...and reaches the analysis", _wait(lambda: _job(base, G3)["phase"] == "processing", 40), str(_job(base, G3)))
    # The night scan runs in the job's own process, the OCR in a subprocess
    C.check("the analysis runs in more than one process",
            _wait(lambda: any("analyze_names" in c for c in _procs(G3)), 30), str(_procs(G3))[:300])
    st, r = api(base, "/api/delete", {"videoId": G3})
    C.check("deleting a game with a running job is refused (409)", st == 409 and game.exists(), f"{st} {r}")
    st, r = api(base, "/api/stop", {"videoId": G3})
    C.check("Stop stops the analysis", st == 200 and r["stopped"] is True, f"{st} {r}")
    C.check("...ending all of its processes", _wait(lambda: not _procs(G3), 5), str(_procs(G3))[:300])
    C.check("...and keeping the downloaded video", (game / "video.mp4").exists())
    st, r = api(base, "/api/delete", {"videoId": G3})
    C.check("right after that the game can be deleted, nothing holds its files", st == 200 and not game.exists(), f"{st} {r}")

    # ---------------- Files in use ----------------
    with urllib.request.urlopen(base + f"/{G1}/video.mp4", timeout=10) as stream:
        first = stream.read(65536)
        st, r = api(base, "/api/delete", {"videoId": G1})
        C.check("a game can be deleted while its video is being streamed",
                len(first) == 65536 and st == 200 and _wait(lambda: not (run_dir / G1).exists(), 5), f"{st} {r}")
    C.check("...and the server carries on", api(base, "/api/job-status")[0] == 200)

    st, r = api(base, "/api/state", {"videoId": G2, "position": 5.0, "duration": 180.0})
    C.check("a resume point saves", st == 200, f"{st} {r}")
    path = run_dir / G2 / "viewer_state.json"
    reader = open(path, encoding="utf-8")
    threading.Timer(0.4, reader.close).start()
    st, r = api(base, "/api/state", {"videoId": G2, "bookmarked": True})
    state = read_state(run_dir, G2)
    C.check("a save succeeds while something holds the file open for a moment",
            st == 200 and state["bookmarked"] is True and state["position"] == 5.0
            and not (run_dir / G2 / "viewer_state.json.tmp").exists(), f"{st} {r} {state}")
