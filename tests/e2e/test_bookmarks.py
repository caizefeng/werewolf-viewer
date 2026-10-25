"""Bookmarks and resume points: API contract, library UI, info bar, filter,
resume behaviour, persistence across reloads/devices, and their interplay
with re-analysis and deletion."""
import json
import re
import threading
import time
import urllib.error

from harness import (DURATION, G1, G2, G3, DEMO_IDS, active_id, api, ctl, current_time, log, open_app,
                     park_mouse, read_state, seek_by_bar, show_controls, wait_jobs_idle, watch_errors)

STAR_ON, STAR_OFF = "★", "☆"
COUNT = STAR_ON + "\u2009"          # "★ n" uses a thin space


def _layout(page):
    """Episode headers and the info bar must stay on one line, unclipped."""
    return page.evaluate("""(() => {
        const one = (el) => el && el.getClientRects().length <= 1;
        const heads = [...document.querySelectorAll('#video-list li.lib-group')].map(h => {
            const parts = [...h.children].filter(c => getComputedStyle(c).display !== 'none' && c.textContent.trim());
            const d = h.querySelector('.lib-group-date');
            return {group: h.dataset.group, height: Math.round(h.getBoundingClientRect().height),
                    oneLine: parts.every(c => one(c) && c.getBoundingClientRect().height < 24),
                    dateClipped: d.scrollWidth > d.clientWidth + 1,
                    overflow: h.scrollWidth > h.clientWidth + 1};
        });
        const bar = document.getElementById('info-bar');
        return {heads, infoHeight: Math.round(bar.getBoundingClientRect().height),
                statusOneLine: one(document.getElementById('status'))};
    })()""")


def _layout_ok(lay):
    return all(h["oneLine"] and not h["dateClipped"] and not h["overflow"] and h["height"] < 40 for h in lay["heads"])


def _row(page, vid):
    return page.evaluate(f"""(() => {{
        const li = document.querySelector('#video-list li.lib-item[data-id="{vid}"]');
        if (!li) return null;
        const star = li.querySelector('.video-star');
        const chip = li.querySelector('.video-resume');
        const bar = li.querySelector('.video-progress > span');
        const cs = getComputedStyle(li);
        return {{starred: li.classList.contains('starred'), star: star && star.textContent,
                 pressed: star && star.getAttribute('aria-pressed'), chip: chip && chip.textContent,
                 bar: bar ? parseFloat(bar.style.width) : null, visible: cs.display !== 'none'}};
    }})()""")


def _header(page, key):
    return page.evaluate(f"""(() => {{
        const h = document.querySelector('#video-list li.lib-group[data-group="{key}"]');
        if (!h) return null;
        return {{stars: h.querySelector('.lib-group-stars').textContent, visible: getComputedStyle(h).display !== 'none',
                 collapsed: h.classList.contains('collapsed')}};
    }})()""")


def _info_star(page):
    return page.evaluate("""(() => { const b = document.getElementById('bookmark-btn');
        return {hidden: b.hidden, text: b.textContent, pressed: b.getAttribute('aria-pressed')}; })()""")


def _wait_state(run_dir, vid, pred, timeout=6.0):
    end = time.time() + timeout
    s = read_state(run_dir, vid)
    while time.time() < end:
        s = read_state(run_dir, vid)
        if pred(s):
            return s
        time.sleep(0.2)
    return s


def run(base, run_dir, C, browser):
    # ---------------- API contract ----------------
    st, videos = api(base, "/api/videos")
    C.check("API: library lists every demo game with an empty viewer state",
            st == 200 and sorted(v["id"] for v in videos) == sorted(DEMO_IDS)
            and all(v["bookmarked"] is False and v["position"] is None and v["watchedAt"] is None for v in videos),
            str(videos)[:160])
    for name, body, code in [
        ("an invalid videoId", {"videoId": "../etc", "bookmarked": True}, 400),
        ("an unknown game", {"videoId": "nosuchgame1", "bookmarked": True}, 404),
        ("bookmarked that is not a boolean", {"videoId": G3, "bookmarked": "yes"}, 400),
        ("a negative position", {"videoId": G3, "position": -1}, 400),
        ("a position sent as a string", {"videoId": G3, "position": "12"}, 400),
        ("a position beyond 48 hours", {"videoId": G3, "position": 1e9}, 400),
        ("a zero duration", {"videoId": G3, "position": 5, "duration": 0}, 400),
        ("a duration without a position", {"videoId": G3, "duration": 100}, 400),
        ("an empty update", {"videoId": G3}, 400),
    ]:
        st, r = api(base, "/api/state", body)
        C.check(f"API: rejects {name} ({code})", st == code, f"{st} {r}")
    st, _ = api(base, "/api/state", {"videoId": G3, "bookmarked": True}, headers={"Origin": "http://evil.example"})
    C.check("API: rejects a cross-origin write (403)", st == 403, str(st))
    big = json.dumps({"videoId": G3, "bookmarked": True, "pad": "x" * 1_200_000}).encode()
    try:
        st, _ = api(base, "/api/state", raw=big)
    except (ConnectionError, OSError, urllib.error.URLError) as e:
        st = f"connection closed ({type(e).__name__})"
    C.check("API: rejects an oversized body", st == 413 or "connection closed" in str(st), str(st))
    C.check("API: rejected requests write nothing", read_state(run_dir, G3) is None)

    st, r = api(base, "/api/state", {"videoId": G3, "bookmarked": True})
    s = read_state(run_dir, G3)
    C.check("API: a bookmark is saved to viewer_state.json",
            st == 200 and r["bookmarked"] is True and s and s["bookmarked"] is True and s.get("bookmarkedAt"), f"{r} {s}")
    st, r = api(base, "/api/state", {"videoId": G3, "position": 100.04, "duration": 240.0})
    s = read_state(run_dir, G3)
    C.check("API: a resume point merges in without losing the bookmark",
            st == 200 and r["position"] == 100.0 and r["bookmarked"] is True and s["duration"] == 240.0 and s.get("watchedAt"), str(r))
    st, r = api(base, "/api/state", {"videoId": G3, "bookmarked": False})
    C.check("API: removing the bookmark keeps the resume point", st == 200 and r["bookmarked"] is False and r["position"] == 100.0, str(r))
    st, videos = api(base, "/api/videos")
    g3 = {v["id"]: v for v in videos}[G3]
    C.check("API: /api/videos reports the stored state",
            g3["bookmarked"] is False and g3["position"] == 100.0 and g3["duration"] == 240.0 and g3["watchedAt"], str(g3))

    # concurrent writers: the synchronous read-modify-write must not lose fields
    errors = []
    def hammer(i):
        body = {"videoId": G3, "bookmarked": i % 2 == 0} if i % 3 else {"videoId": G3, "position": float(i), "duration": 240.0}
        try:
            api(base, "/api/state", body)
        except Exception as e:
            errors.append(str(e))
    threads = [threading.Thread(target=hammer, args=(i,)) for i in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    s = read_state(run_dir, G3)
    C.check("API: 30 concurrent writes leave a valid file with every field",
            not errors and s and all(k in s for k in ("bookmarked", "position", "duration", "watchedAt", "bookmarkedAt"))
            and not (run_dir / G3 / "viewer_state.json.tmp").exists(), f"errors={errors[:2]} state={s}")

    (run_dir / G3 / "viewer_state.json").write_text("{not json")
    st, videos = api(base, "/api/videos")
    C.check("API: a corrupt viewer_state.json reads as empty instead of failing the library",
            st == 200 and {v["id"]: v for v in videos}[G3]["position"] is None)
    st, r = api(base, "/api/state", {"videoId": G3, "bookmarked": True})
    s = read_state(run_dir, G3)
    C.check("API: the next write replaces a corrupt file", st == 200 and isinstance(s, dict) and s.get("bookmarked") is True, str(s))
    (run_dir / G3 / "viewer_state.json").unlink()

    # ---------------- Library UI ----------------
    ctx = browser.new_context(viewport={"width": 1600, "height": 1000})
    pg = ctx.new_page()
    errs = watch_errors(pg)
    open_app(pg, base)
    pg.evaluate("localStorage.clear()")
    open_app(pg, base)
    rows = {v: _row(pg, v) for v in DEMO_IDS}
    C.check("UI: every game row has a star, all off",
            all(r and r["star"] == STAR_OFF and r["pressed"] == "false" and not r["starred"] for r in rows.values()), str(rows))
    C.check("UI: with nothing in progress the first game opens", active_id(pg) == G1, str(active_id(pg)))
    C.check("UI: info bar shows the open game's star, off", _info_star(pg) == {"hidden": False, "text": STAR_OFF, "pressed": "false"}, str(_info_star(pg)))
    pg.wait_for_timeout(1500)
    C.check("UI: opening a game writes no viewer state", all(read_state(run_dir, v) is None for v in DEMO_IDS))

    pg.click(f'#video-list li[data-id="{G2}"] .video-star')
    s = _wait_state(run_dir, G2, lambda s: s and s.get("bookmarked") is True)
    r = _row(pg, G2)
    C.check("UI: the row star turns on", r["starred"] and r["star"] == STAR_ON and r["pressed"] == "true", str(r))
    C.check("UI: the bookmark is saved on the server", s and s.get("bookmarked") is True, str(s))
    C.check("UI: clicking a star does not open that game", active_id(pg) == G1, str(active_id(pg)))
    C.check("UI: the episode header counts the bookmark", _header(pg, "S01E01")["stars"] == f"{COUNT}1", str(_header(pg, "S01E01")))
    lay = _layout(pg)
    C.check("UI: a header with a bookmark count stays on one line, nothing clipped (1600 wide)", _layout_ok(lay), str(lay["heads"]))
    C.check("UI: the other episode shows no count", _header(pg, "S01E02")["stars"] == "", str(_header(pg, "S01E02")))
    C.check("UI: the info bar star still describes the open game (off)", _info_star(pg)["pressed"] == "false")

    pg.click("#bookmark-btn")
    _wait_state(run_dir, G1, lambda s: s and s.get("bookmarked") is True)
    C.check("UI: the info bar star bookmarks the open game and its row follows",
            _info_star(pg)["pressed"] == "true" and _row(pg, G1)["starred"] and read_state(run_dir, G1)["bookmarked"] is True)
    C.check("UI: the header count follows (2)", _header(pg, "S01E01")["stars"] == f"{COUNT}2")
    park_mouse(pg)
    pg.keyboard.press("b")
    _wait_state(run_dir, G1, lambda s: s and s.get("bookmarked") is False)
    C.check("UI: the B key toggles the open game's bookmark",
            _info_star(pg)["pressed"] == "false" and not _row(pg, G1)["starred"] and read_state(run_dir, G1)["bookmarked"] is False)
    pg.click("#search-input")
    pg.keyboard.press("b")
    pg.wait_for_timeout(600)
    C.check("UI: typing b in the search field does not toggle a bookmark",
            _info_star(pg)["pressed"] == "false" and read_state(run_dir, G1)["bookmarked"] is False)
    pg.fill("#search-input", "")

    open_app(pg, base)
    C.check("UI: bookmarks survive a reload", _row(pg, G2)["starred"] and not _row(pg, G1)["starred"] and not _row(pg, G3)["starred"])
    C.check("UI: with nothing in progress, the first bookmarked game opens", active_id(pg) == G2, str(active_id(pg)))

    pg.click('#video-list li.lib-group[data-group="S01E01"]')
    pg.wait_for_timeout(300)
    h = _header(pg, "S01E01")
    C.check("UI: a collapsed episode still shows its bookmark count", h["collapsed"] and h["stars"] == f"{COUNT}1" and not _row(pg, G2)["visible"], str(h))
    pg.click('#video-list li.lib-group[data-group="S01E01"]')
    pg.wait_for_timeout(300)

    pg.click("#lib-filter-btn")
    pg.wait_for_timeout(300)
    vis = {v: _row(pg, v)["visible"] for v in DEMO_IDS}
    C.check("UI: the filter shows only bookmarked games", vis == {G1: False, G2: True, G3: False}, str(vis))
    C.check("UI: the filter hides episodes without bookmarks", _header(pg, "S01E01")["visible"] and not _header(pg, "S01E02")["visible"])
    C.check("UI: the filter button shows its state", pg.evaluate("document.getElementById('lib-filter-btn').getAttribute('aria-pressed')") == "true")
    open_app(pg, base)
    C.check("UI: the filter choice survives a reload", not _row(pg, G1)["visible"] and _row(pg, G2)["visible"])
    pg.click(f'#video-list li[data-id="{G2}"] .video-star')
    _wait_state(run_dir, G2, lambda s: s and s.get("bookmarked") is False)
    pg.wait_for_timeout(300)
    empty_visible = pg.evaluate("getComputedStyle(document.querySelector('#video-list li.lib-empty')).display !== 'none'")
    C.check("UI: un-starring in the filtered view removes the row and shows the empty hint",
            not _row(pg, G2)["visible"] and empty_visible)
    pg.click("#lib-filter-btn")
    pg.wait_for_timeout(300)
    C.check("UI: turning the filter off shows every game again and hides the hint",
            all(_row(pg, v)["visible"] for v in DEMO_IDS)
            and pg.evaluate("getComputedStyle(document.querySelector('#video-list li.lib-empty')).display === 'none'"))

    # ---------------- Resume points ----------------
    pg.click(f'#video-list li[data-id="{G3}"]')
    pg.wait_for_timeout(2000)
    seek_by_bar(pg, 1 / 3)
    s = _wait_state(run_dir, G3, lambda s: s and s.get("position"))
    want = DURATION[G3] / 3
    C.check("UI: a seek is saved as the resume point", s and abs(s["position"] - want) < 6 and abs(s["duration"] - DURATION[G3]) < 1, str(s))
    pg.wait_for_timeout(300)
    r = _row(pg, G3)
    C.check("UI: the row shows a resume chip and a progress line",
            r["chip"] and re.fullmatch(r"▶ \d+:\d\d", r["chip"]) and r["bar"] is not None and abs(r["bar"] - 33.3) < 3, str(r))
    saved = read_state(run_dir, G3)

    open_app(pg, base)
    C.check("UI: on reload the game in progress opens (not the first game)", active_id(pg) == G3, str(active_id(pg)))
    t = current_time(pg)
    C.check("UI: it resumes at the saved point", abs(t - saved["position"]) < 1.5, f"{t} vs {saved['position']}")
    note = pg.evaluate("(() => { const n = document.getElementById('resume-note'); return {hidden: n.hidden, text: document.getElementById('resume-text').textContent}; })()")
    C.check("UI: the info bar says where it resumed", not note["hidden"] and note["text"].startswith("Resumed at "), str(note))
    lay = _layout(pg)
    C.check("UI: with the resume note the info bar stays on one line (1600 wide)",
            lay["statusOneLine"] and lay["infoHeight"] < 50, f"height={lay['infoHeight']}")
    pg.wait_for_timeout(1500)
    C.check("UI: resuming does not rewrite the saved point", read_state(run_dir, G3) == saved)

    ctl(pg, "#start-over-btn")
    s = _wait_state(run_dir, G3, lambda s: s and s.get("position", 99) < 1)
    C.check("UI: Start over goes back to 0:00 and records it",
            current_time(pg) < 1 and s["position"] < 1 and pg.evaluate("document.getElementById('resume-note').hidden"), f"{current_time(pg)} {s}")
    pg.wait_for_timeout(300)
    C.check("UI: a game back at the start shows no resume chip", _row(pg, G3)["chip"] is None)

    ctl(pg, "#play-btn")
    pg.wait_for_timeout(7000)
    playing = not pg.evaluate("document.getElementById('video').paused")
    s1 = read_state(run_dir, G3)
    pg.wait_for_timeout(5500)
    s2 = read_state(run_dir, G3)
    C.check("UI: playback saves the position every few seconds",
            playing and s1["position"] > 2 and s2["position"] > s1["position"], f"playing={playing} {s1['position']} -> {s2['position']}")
    ctl(pg, "#play-btn")
    pg.wait_for_timeout(800)
    t = current_time(pg)
    s = read_state(run_dir, G3)
    C.check("UI: pausing saves the exact position", abs(s["position"] - t) < 0.6, f"{s['position']} vs {t}")

    pg.evaluate("document.getElementById('video').currentTime = 150")
    pg.wait_for_timeout(250)
    pg.click(f'#video-list li[data-id="{G1}"]')
    s = _wait_state(run_dir, G3, lambda s: s and abs(s["position"] - 150) < 1, timeout=4)
    C.check("UI: switching games saves the place of the game being left", s and abs(s["position"] - 150) < 1, str(s))
    pg.click(f'#video-list li[data-id="{G3}"]')
    pg.wait_for_timeout(2000)
    C.check("UI: coming back resumes it", abs(current_time(pg) - 150) < 1.5, str(current_time(pg)))

    pg.evaluate(f"document.getElementById('video').currentTime = {DURATION[G3] - 2}")
    pg.wait_for_timeout(300)
    ctl(pg, "#play-btn")
    pg.wait_for_function("document.getElementById('video').ended", timeout=15000)
    s = _wait_state(run_dir, G3, lambda s: s and s["position"] > DURATION[G3] - 1)
    pg.wait_for_timeout(300)
    r = _row(pg, G3)
    C.check("UI: a game watched to the end is marked watched, without a progress line",
            s and r["chip"] == "✓ watched" and r["bar"] is None, f"{s} {r}")
    pg.click(f'#video-list li[data-id="{G1}"]')
    pg.wait_for_timeout(1500)
    pg.click(f'#video-list li[data-id="{G3}"]')
    pg.wait_for_timeout(2000)
    C.check("UI: a watched game opens from the start", current_time(pg) < 1 and pg.evaluate("document.getElementById('resume-note').hidden"),
            str(current_time(pg)))

    pg.evaluate("document.getElementById('video').currentTime = 100")
    pg.wait_for_timeout(250)
    C.check("UI: page errors so far", not errs, "; ".join(errs)[:300])
    pg.close()
    s = _wait_state(run_dir, G3, lambda s: s and abs(s["position"] - 100) < 1, timeout=4)
    C.check("UI: closing the tab right after a seek still saves the place", s and abs(s["position"] - 100) < 1, str(s))

    # ---------------- Another device ----------------
    api(base, "/api/state", {"videoId": G2, "bookmarked": True})
    other = browser.new_context(viewport={"width": 1366, "height": 768})
    pg2 = other.new_page()
    errs2 = watch_errors(pg2)
    open_app(pg2, base)
    C.check("UI: another device sees the same bookmarks and opens the game in progress",
            _row(pg2, G2)["starred"] and not _row(pg2, G1)["starred"] and active_id(pg2) == G3, f"active={active_id(pg2)}")
    C.check("UI: ...and resumes it at the same point", abs(current_time(pg2) - 100) < 1.5, str(current_time(pg2)))
    lay = _layout(pg2)
    C.check("UI: at 1366 wide the headers and the info bar stay on one line",
            _layout_ok(lay) and lay["statusOneLine"] and lay["infoHeight"] < 50, str(lay))
    C.check("UI: the hidden-roles game can be bookmarked too", pg2.evaluate(
        f"document.querySelector('#video-list li[data-id=\"{G2}\"]').classList.contains('hidden-roles')") and _row(pg2, G2)["starred"])

    touch = browser.new_context(viewport={"width": 820, "height": 1180}, has_touch=True, is_mobile=True)
    pg3 = touch.new_page()
    open_app(pg3, base)
    hover_none = pg3.evaluate("matchMedia('(hover: none)').matches")
    op = pg3.evaluate(f"parseFloat(getComputedStyle(document.querySelector('#video-list li[data-id=\"{G1}\"] .video-star')).opacity)")
    C.check("UI: on a touch screen the outline stars stay visible without hover", (not hover_none) or op >= 0.6, f"hover:none={hover_none} opacity={op}")
    pg3.tap(f'#video-list li[data-id="{G1}"] .video-star')
    _wait_state(run_dir, G1, lambda s: s and s.get("bookmarked") is True)
    C.check("UI: tapping a star bookmarks on a touch screen", read_state(run_dir, G1)["bookmarked"] is True)
    touch.close()

    # ---------------- Interplay with re-analysis and deletion ----------------
    pg2.on("dialog", lambda d: d.accept())
    before = read_state(run_dir, G3)
    pg2.hover(f'#video-list li[data-id="{G3}"]')
    pg2.click(f'#video-list li[data-id="{G3}"] .video-re-btn')
    log("re-analysing a demo game through the library button (about 2 minutes)")
    pg2.wait_for_timeout(2000)
    wait_jobs_idle(base)
    pg2.wait_for_timeout(3500)
    st, job = api(base, "/api/job-status")
    jg = next((j for j in job["jobs"] if j["videoId"] == G3), None)
    after = read_state(run_dir, G3)
    C.check("UI: re-analysis completes and leaves the viewer state untouched",
            jg and jg["done"] and not jg["error"] and after == before, f"job={jg and jg['phase']} {before} -> {after}")
    r = _row(pg2, G3)
    C.check("UI: after the library refresh the row still shows the resume chip", r and r["chip"] and r["chip"].startswith("▶"), str(r))

    pg2.hover(f'#video-list li[data-id="{G2}"]')
    pg2.click(f'#video-list li[data-id="{G2}"] .video-del-btn:not(.video-re-btn)')
    pg2.wait_for_timeout(1500)
    C.check("UI: deleting a bookmarked game removes it and its state",
            _row(pg2, G2) is None and not (run_dir / G2).exists() and _header(pg2, "S01E01")["stars"] == f"{COUNT}1")
    pg2.fill("#search-input", "demo cup")
    pg2.click("#search-btn")
    pg2.wait_for_selector(f'.sr-btn-dl[data-id="{G2}"]', timeout=30000)
    pg2.click(f'.sr-btn-dl[data-id="{G2}"]')
    log("downloading and analysing it again (about 2 minutes)")
    pg2.wait_for_timeout(3000)
    wait_jobs_idle(base)
    pg2.wait_for_timeout(4000)
    r = _row(pg2, G2)
    C.check("UI: downloaded again, it comes back without the old bookmark", r and not r["starred"] and r["chip"] is None
            and read_state(run_dir, G2) is None, str(r))
    C.check("UI: no page or console errors on the second device", not errs2, "; ".join(errs2)[:300])
    other.close()
    ctx.close()
