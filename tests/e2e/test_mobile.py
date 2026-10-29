"""Phones and tablets on the demo games: the layouts (no sideways scroll, the
player first, Library / Search tabs on a phone), touch controls (taps, a
dragged progress bar, ±10 s), the PHASES / ROLES panels (docked below the
player on an upright phone, tapped open over the video elsewhere), overlays
that cover the video and nothing else, the browser's fullscreen and the
stand-in an iPhone gets (no Fullscreen API there), the edit handles a finger
needs, a phone turning round, and a desktop width that must stay as it was.

Taps are real touch input (Playwright's tap), and so are drags on Chromium
(CDP touch events): the page sees pointerType "touch" as on a phone. WebKit
(run.py --webkit) has no CDP; there a drag is replayed as touch-type pointer
events on the element under the finger, its moves and lift sent to that same
element as a pointer capture would."""
import json

from harness import G1, G2, G3, active_id, current_time, open_app, watch_errors

PHONE = dict(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True, device_scale_factor=2)
TABLET = dict(viewport={"width": 820, "height": 1180}, has_touch=True, is_mobile=True)
DAY_T = 210                     # demo game 1: day 2, masks up
# iPhone Safari: only a <video> can go fullscreen, so the page has no API
NO_FULLSCREEN_API = """
for (const name of ["requestFullscreen", "webkitRequestFullscreen"]) {
  Object.defineProperty(Element.prototype, name, {value: undefined, configurable: true});
}
Object.defineProperty(Document.prototype, "fullscreenEnabled", {get: () => false, configurable: true});
"""


def _box(pg, sel):
    return pg.evaluate("(sel) => { const e = document.querySelector(sel); if (!e) return null;"
                       " const r = e.getBoundingClientRect();"
                       " return {x: r.x, y: r.y, w: r.width, h: r.height, b: r.bottom, r: r.right}; }", sel)


def _style(pg, sel, prop):
    return pg.evaluate("([sel, prop]) => { const e = document.querySelector(sel); return e && getComputedStyle(e)[prop]; }",
                       [sel, prop])


def _parent(pg, sel):
    return pg.evaluate("(sel) => document.querySelector(sel).parentElement.id", sel)


def _same(a, b, tol=1.0):
    return a and b and all(abs(a[k] - b[k]) <= tol for k in ("x", "y", "w", "h"))


def _seek(pg, t):
    pg.evaluate(f"document.getElementById('video').currentTime = {t}")
    pg.wait_for_function("!document.getElementById('video').seeking")
    pg.wait_for_timeout(700)


def _paused(pg):
    return pg.evaluate("document.getElementById('video').paused")


def _no_sideways_scroll(pg):
    return pg.evaluate("document.documentElement.scrollWidth <= innerWidth")


def _letterboxed(pg):
    """The video's picture inside the wrapper (object-fit: contain)."""
    return pg.evaluate("""(() => { const v = document.getElementById('video');
        const w = document.getElementById('video-wrapper').getBoundingClientRect();
        const s = Math.min(w.width / v.videoWidth, w.height / v.videoHeight);
        return {x: w.x + (w.width - v.videoWidth * s) / 2, y: w.y + (w.height - v.videoHeight * s) / 2,
                w: v.videoWidth * s, h: v.videoHeight * s}; })()""")


POINTER = """([type, x, y]) => {
  if (type === "pointerdown") window.__finger = document.elementFromPoint(x, y);
  window.__finger.dispatchEvent(new PointerEvent(type, {pointerId: 77, pointerType: "touch", isPrimary: true,
    button: 0, buttons: type === "pointerup" ? 0 : 1, clientX: x, clientY: y, bubbles: true, cancelable: true}));
}"""


def _touch_drag(pg, x0, y0, x1, y1, steps=8):
    points = [(x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps) for i in range(steps + 1)]
    if pg.context.browser.browser_type.name != "chromium":
        for i, (x, y) in enumerate(points):
            pg.evaluate(POINTER, ["pointerdown" if i == 0 else "pointermove", x, y])
        pg.evaluate(POINTER, ["pointerup", x1, y1])
        return
    cdp = pg.context.new_cdp_session(pg)
    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x0, "y": y0}]})
    for x, y in points[1:]:
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x, "y": y}]})
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    cdp.detach()


def _tab_point(pg, panel):
    """Where a finger taps a closed panel's tab: just inside the video's
    edge, beside the panel waiting outside it."""
    b = _box(pg, f"#{panel}")
    x = b["r"] + 10 if panel == "night-jump-buttons" else b["x"] - 10
    return x, b["y"] + b["h"] / 2


def _open(pg, panel):
    return pg.evaluate(f"document.getElementById('{panel}').classList.contains('open')")


def run(base, run_dir, C, browser):
    meta_path = run_dir / G1 / "metadata.json"

    # ── An upright phone ──
    ctx = browser.new_context(**PHONE)
    pg = ctx.new_page()
    errs = watch_errors(pg)
    pg.on("dialog", lambda d: d.accept())
    open_app(pg, base)
    pg.evaluate("localStorage.clear()")
    open_app(pg, base)
    pg.wait_for_function("document.getElementById('video').readyState >= 1")
    C.check("phone: the first game opens", active_id(pg) == G1, str(active_id(pg)))
    C.check("phone: no sideways scrolling (the page is as wide as the screen)", _no_sideways_scroll(pg),
            str(pg.evaluate("[document.documentElement.scrollWidth, innerWidth]")))
    attrs = pg.evaluate("['playsinline', 'webkit-playsinline', 'disablepictureinpicture', 'disableremoteplayback']"
                        ".filter(a => !document.getElementById('video').hasAttribute(a))")
    C.check("phone: the video plays inline (an iPhone's own player would show it unmasked), no PiP or casting",
            not attrs, f"missing {attrs}")
    lay = {k: _box(pg, s) for k, s in (("player", "#player-container"), ("tabs", "#pane-tabs"),
                                        ("library", "#sidebar-left"))}
    C.check("phone: the player comes first, then the Library / Search tabs, then the library",
            lay["player"]["b"] <= lay["tabs"]["y"] and lay["tabs"]["b"] <= lay["library"]["y"]
            and abs(lay["player"]["w"] - lay["library"]["w"]) < 1, json.dumps(lay))
    C.check("phone: the search list waits behind its tab", _style(pg, "#sidebar-right", "display") == "none")

    _seek(pg, DAY_T)
    vid, ctl = _box(pg, "#video"), _box(pg, "#custom-controls")
    C.check("phone: the controls sit below the video and show without a tap",
            ctl["y"] >= vid["b"] - 1 and _style(pg, "#custom-controls", "opacity") == "1", f"{vid} {ctl}")
    C.check("phone: the masks and the night overlay cover the video, not the controls below it",
            _same(_box(pg, "#name-masks"), vid) and _same(_box(pg, "#night-overlay"), vid),
            f"{_box(pg, '#name-masks')} {_box(pg, '#night-overlay')} {vid}")
    C.check("phone: two masks up during the day",
            pg.evaluate("[...document.querySelectorAll('.name-mask')].filter(m => !m.classList.contains('hidden')).length") == 2)
    sizes = pg.evaluate("""[...document.querySelectorAll('#controls-row > button, #edit-menu-btn')]
        .filter(b => getComputedStyle(b).display !== 'none').map(b => { const r = b.getBoundingClientRect();
        return [b.id, Math.round(r.x), Math.round(r.right), Math.round(r.height)]; })""")
    C.check("phone: every control fits on screen and is at least 34px tall",
            all(x >= 0 and r <= 390 and h >= 34 for _, x, r, h in sizes), str(sizes))
    C.check("phone: ±10 s buttons, no volume slider (iOS ignores one)",
            _style(pg, "#fwd-btn", "display") != "none" and _style(pg, "#volume-slider", "display") == "none")

    pg.tap("#play-btn")
    pg.wait_for_timeout(700)
    playing = not _paused(pg)
    pg.tap("#video")
    pg.wait_for_timeout(500)
    C.check("phone: the play button plays, a tap on the video pauses", playing and _paused(pg))
    t0 = current_time(pg)
    pg.tap("#fwd-btn")
    pg.wait_for_timeout(500)
    t1 = current_time(pg)
    pg.tap("#back-btn")
    pg.wait_for_timeout(500)
    C.check("phone: +10 and −10 skip ten seconds", abs(t1 - t0 - 10) < 0.6 and abs(current_time(pg) - t0) < 0.6,
            f"{t0:.1f} -> {t1:.1f} -> {current_time(pg):.1f}")

    bar = _box(pg, "#progress-bar")
    y = bar["y"] + bar["h"] / 2
    scroll0 = pg.evaluate("scrollY")
    _touch_drag(pg, bar["x"] + bar["w"] * 0.1, y, bar["x"] + bar["w"] * 0.6, y)
    pg.wait_for_timeout(800)
    frac = current_time(pg) / 420
    C.check("phone: dragging the progress bar with a finger seeks to where it lets go, without scrolling the page",
            abs(frac - 0.6) < 0.02 and pg.evaluate("scrollY") == scroll0, f"{frac:.3f}")

    C.check("phone: the PHASES and ROLES panels are docked below the player",
            _parent(pg, "#night-jump-buttons") == "player-dock" and _parent(pg, "#role-panel") == "player-dock"
            and _box(pg, "#player-dock")["y"] >= _box(pg, "#info-bar")["b"] - 1)
    pg.tap(".night-jump-btn:not(.jump-end)")
    pg.wait_for_timeout(800)
    C.check("phone: a docked night button jumps to that night", 85 < current_time(pg) < 95, str(current_time(pg)))
    _seek(pg, DAY_T)
    pg.tap("#role-panel .rp-modes .rp-mode-btn:nth-child(2)")
    pg.wait_for_timeout(300)
    seats = pg.evaluate("""[...document.querySelectorAll('#role-panel .rp-body .rp-row')].map(r => {
        const b = r.getBoundingClientRect(); return [parseInt(r.querySelector('.rp-num').textContent), b.x, b.y]; })""")
    left = [s for s in seats if s[0] <= 6]
    right = [s for s in seats if s[0] > 6]
    C.check("phone: By seat lays the seats out as the broadcast does, 1-6 left and 7-12 right",
            len(seats) == 12 and max(s[1] for s in left) < min(s[1] for s in right)
            and [s[2] for s in left] == sorted(s[2] for s in left), str(seats))
    pg.tap("#role-panel .rp-body .rp-row:nth-child(2)")
    pg.wait_for_timeout(400)
    revealed = pg.evaluate("[...document.querySelectorAll('#role-panel .rp-row.revealed .rp-num')].map(n => n.textContent)")
    fills = pg.evaluate("[...document.querySelectorAll('.name-mask')].map(m => m.querySelectorAll('.name-mask-fill').length)")
    C.check("phone: tapping seat 2 reveals it and opens its row on the mask", revealed == ["2"] and sum(fills) > 2,
            f"{revealed} {fills}")
    pg.tap("#role-panel .rp-actions .rp-btn:nth-child(1)")
    pg.tap("#role-panel .rp-modes .rp-mode-btn:nth-child(1)")

    hidden = pg.evaluate("['.mask-delete-btn', '.mask-hover-zone', '.remove-phase', '.night-handle']"
                         ".map(s => [s, getComputedStyle(document.querySelector(s)).display])")
    C.check("phone: no invisible × or handle on the masks and markers to hit by accident",
            all(d == "none" for _, d in hidden), str(hidden))
    rows = pg.evaluate("""[...document.querySelectorAll('#video-list li.lib-item .video-del-btn')].map(b => {
        const r = b.getBoundingClientRect(); return [parseFloat(getComputedStyle(b).opacity), r.width, r.height]; })""")
    C.check("phone: the library's ↻ and × show without hover, 32px targets",
            rows and all(o >= 0.5 and w >= 32 and h >= 32 for o, w, h in rows), str(rows))

    pg.tap('#pane-tabs .pane-tab[data-pane="search"]')
    pg.wait_for_timeout(300)
    C.check("phone: the Search tab swaps the library for the search list",
            _style(pg, "#sidebar-right", "display") != "none" and _style(pg, "#sidebar-left", "display") == "none")
    C.check("phone: the search field is 16px (iOS zooms into anything smaller)",
            float(_style(pg, "#search-input", "fontSize").rstrip("px")) >= 16)
    pg.tap('#pane-tabs .pane-tab[data-pane="library"]')
    pg.wait_for_timeout(300)
    pg.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    pg.wait_for_timeout(300)
    pg.tap(f'#video-list li[data-id="{G3}"] .video-title')
    pg.wait_for_timeout(1800)
    top = _box(pg, "#player-container")["y"]
    C.check("phone: picking a game below the player opens it and scrolls back up to it",
            active_id(pg) == G3 and -2 < top < 80, f"{active_id(pg)} top={top}")
    pg.tap(f'#video-list li[data-id="{G2}"] .video-title')
    pg.wait_for_timeout(1800)
    line2 = pg.evaluate("""['#toggle-masks', '#mask-mode-btn', '#phase-indicator', '#edit-menu-wrap']
        .map(s => { const r = document.querySelector(s).getBoundingClientRect(); return r.y + r.height / 2; })""")
    C.check("phone: a hidden-roles game's mask button stays short enough for one line of four",
            _style(pg, "#toggle-masks .mask-note", "display") == "none" and max(line2) - min(line2) <= 2
            and pg.evaluate("document.getElementById('toggle-masks').textContent") == "Masks: Off (hidden roles)",
            str(line2))
    pg.tap(f'#video-list li[data-id="{G1}"] .video-title')
    pg.wait_for_timeout(1800)
    pg.wait_for_function("document.getElementById('video').readyState >= 1")
    _seek(pg, DAY_T)

    # Edit handles: a finger has no hover to reveal them
    before = json.loads(meta_path.read_text())["night_phases"]
    pg.tap("#edit-menu-btn")
    pg.wait_for_timeout(300)
    C.check("phone: ✎ Edit offers the edit handles", _style(pg, "#edit-handles-btn", "display") != "none")
    pg.tap("#edit-handles-btn")
    pg.wait_for_timeout(300)
    shown = pg.evaluate("['.mask-delete-btn', '.night-handle', '.remove-phase'].every(s =>"
                        " getComputedStyle(document.querySelector(s)).display !== 'none')")
    C.check("phone: Show edit handles brings out the handles and × buttons", shown
            and pg.evaluate("document.getElementById('video-wrapper').classList.contains('editing')"))
    h = _box(pg, ".night-marker .night-handle.handle-end")
    _touch_drag(pg, h["x"] + h["w"] / 2, h["y"] + h["h"] / 2, h["x"] + h["w"] / 2 + 15, h["y"] + h["h"] / 2)
    pg.wait_for_timeout(1200)
    after = json.loads(meta_path.read_text())["night_phases"]
    C.check("phone: dragging a night's end handle with a finger moves it and saves",
            after[0]["end"] > before[0]["end"] + 5 and after[0]["start"] == before[0]["start"],
            f"{before[0]} -> {after[0]}")
    masks0 = json.loads(meta_path.read_text())["name_masks"]
    z = _box(pg, ".name-mask.left .mask-hover-zone")
    _touch_drag(pg, z["x"] + z["w"] / 2, z["y"] + z["h"] / 2, z["x"] + z["w"] / 2 + 20, z["y"] + z["h"] / 2)
    pg.wait_for_timeout(1200)
    masks1 = json.loads(meta_path.read_text())["name_masks"]
    left0 = next(m for m in masks0 if m["x"] < 0.5)
    left1 = next(m for m in masks1 if m["x"] < 0.5)
    C.check("phone: dragging a mask's inner edge with a finger widens it and saves",
            left1["w"] > left0["w"] + 0.03, f"{left0} -> {left1}")
    pg.tap("#edit-menu-btn")
    pg.wait_for_timeout(300)
    pg.tap("#reset-masks-btn")
    pg.wait_for_timeout(1200)
    pg.tap("#edit-menu-btn")
    pg.wait_for_timeout(300)
    pg.tap("#reset-nights-btn")
    pg.wait_for_timeout(1200)
    pg.tap("#edit-menu-btn")
    pg.wait_for_timeout(300)
    pg.tap("#edit-handles-btn")
    pg.wait_for_timeout(300)
    C.check("phone: Reset nights and Reset masks restore them, and the handles go away again",
            json.loads(meta_path.read_text())["night_phases"] == before
            and json.loads(meta_path.read_text())["name_masks"] == masks0
            and _style(pg, ".night-handle", "display") == "none")

    # The browser's fullscreen (Android; a browser without the API gets the
    # stand-in tested below)
    api = pg.evaluate("typeof document.documentElement.requestFullscreen === 'function'")
    pg.tap("#fullscreen-btn")
    pg.wait_for_timeout(1500)
    fs = pg.evaluate("document.fullscreenElement ? document.fullscreenElement.id"
                     " : document.getElementById('video-wrapper').classList.contains('pseudo-fs') && 'stand-in'")
    C.check("phone: ⛶ makes the player fullscreen", fs == ("video-wrapper" if api else "stand-in"), str(fs))
    C.check("phone: ...with the controls over the video and the panels back on its edges",
            _style(pg, "#custom-controls", "position") == "absolute"
            and _parent(pg, "#night-jump-buttons") == "video-wrapper" and _parent(pg, "#role-panel") == "video-wrapper")
    C.check("phone: ...and the masks on the letterboxed video", _same(_box(pg, "#name-masks"), _letterboxed(pg)),
            f"{_box(pg, '#name-masks')} {_letterboxed(pg)}")
    if api:
        pg.evaluate("document.exitFullscreen()")
    else:
        pg.tap("#fullscreen-btn")
    pg.wait_for_timeout(1200)
    C.check("phone: leaving fullscreen docks the panels again",
            _parent(pg, "#role-panel") == "player-dock" and _style(pg, "#custom-controls", "position") == "relative")
    C.check("phone: no page or console errors", not errs, "; ".join(errs)[:300])
    ctx.close()

    # ── An iPhone: no Fullscreen API, so the page stands in for it ──
    ctx = browser.new_context(**PHONE)
    ctx.add_init_script(NO_FULLSCREEN_API)
    pg = ctx.new_page()
    errs = watch_errors(pg)
    open_app(pg, base)
    pg.wait_for_function("document.getElementById('video').readyState >= 1")
    _seek(pg, DAY_T)
    pg.tap("#fullscreen-btn")
    pg.wait_for_timeout(800)
    st = pg.evaluate("""(() => { const w = document.getElementById('video-wrapper');
        return {pseudo: w.classList.contains('pseudo-fs'), api: !!document.fullscreenElement,
                overflow: getComputedStyle(document.documentElement).overflow}; })()""")
    C.check("iPhone: ⛶ without a Fullscreen API fixes the player over the whole screen",
            st["pseudo"] and not st["api"] and _same(_box(pg, "#video-wrapper"), {"x": 0, "y": 0, "w": 390, "h": 844})
            and st["overflow"] == "hidden", f"{st} {_box(pg, '#video-wrapper')}")
    C.check("iPhone: ...the masks sit on the letterboxed video",
            _same(_box(pg, "#name-masks"), _letterboxed(pg)), f"{_box(pg, '#name-masks')} {_letterboxed(pg)}")
    C.check("iPhone: ...and the panels are on its edges again", _parent(pg, "#night-jump-buttons") == "video-wrapper")

    x, y = _tab_point(pg, "night-jump-buttons")
    pg.touchscreen.tap(x, y)
    pg.wait_for_timeout(500)
    opened = _open(pg, "night-jump-buttons") and _box(pg, "#night-jump-buttons")["x"] >= -1
    pg.tap(".night-jump-btn:not(.jump-end)")
    pg.wait_for_timeout(800)
    C.check("iPhone: a tap on the PHASES tab slides the panel out; a jump goes there and closes it",
            opened and 85 < current_time(pg) < 95 and not _open(pg, "night-jump-buttons"), f"t={current_time(pg)}")
    paused = _paused(pg)
    pg.touchscreen.tap(*_tab_point(pg, "night-jump-buttons"))
    pg.wait_for_timeout(500)
    pg.tap("#video")
    pg.wait_for_timeout(500)
    C.check("iPhone: a tap on the video closes an open panel and does nothing else",
            not _open(pg, "night-jump-buttons") and _paused(pg) == paused)

    _seek(pg, DAY_T)
    pg.tap("#play-btn")
    pg.wait_for_timeout(3800)          # the overlaid controls hide while playing
    hid = not pg.evaluate("document.getElementById('video-wrapper').classList.contains('controls-visible')")
    pg.tap("#video")
    pg.wait_for_timeout(400)
    first = (not _paused(pg), pg.evaluate("document.getElementById('video-wrapper').classList.contains('controls-visible')"))
    pg.tap("#video")
    pg.wait_for_timeout(400)
    C.check("iPhone: with the controls hidden a tap only brings them up; the next one pauses",
            hid and first == (True, True) and _paused(pg), f"hid={hid} first={first} paused={_paused(pg)}")
    pg.tap("#fullscreen-btn")
    pg.wait_for_timeout(800)
    C.check("iPhone: ⛶ again puts the player back in the page",
            not pg.evaluate("document.getElementById('video-wrapper').classList.contains('pseudo-fs')")
            and _style(pg, "html", "overflow") != "hidden" and _parent(pg, "#role-panel") == "player-dock")

    # ── The phone turns round ──
    pg.set_viewport_size({"width": 844, "height": 390})
    pg.wait_for_timeout(1000)
    wr = _box(pg, "#video-wrapper")
    C.check("landscape phone: no sideways scrolling, the header and the whole video fit the screen",
            _no_sideways_scroll(pg) and wr["b"] <= 390 + 0.5, json.dumps(wr))
    C.check("landscape phone: the panels move onto the video's edges, the controls over the video",
            _parent(pg, "#role-panel") == "video-wrapper" and _style(pg, "#custom-controls", "position") == "absolute")
    C.check("landscape phone: both lists below the player, no tabs",
            _style(pg, "#pane-tabs", "display") == "none" and _style(pg, "#sidebar-right", "display") != "none")
    # real games run past an hour: their time must still leave one line
    pg.evaluate("""(() => { const [c, d] = document.querySelectorAll('#time-display span');
        c.textContent = '1:23:45'; d.textContent = ' / 2:10:00'; })()""")
    row = pg.evaluate("""(() => { const r = document.getElementById('controls-row').getBoundingClientRect();
        const kids = [...document.querySelectorAll('#controls-row > *')].filter(e => getComputedStyle(e).display !== 'none'
            && e.getBoundingClientRect().width > 0);
        return {tops: [...new Set(kids.map(e => Math.round(e.getBoundingClientRect().top + e.getBoundingClientRect().height / 2)))],
                inside: kids.every(e => e.getBoundingClientRect().right <= r.right + 0.5)}; })()""")
    C.check("landscape phone: an hour-long game's controls fit one line over the video",
            max(row["tops"]) - min(row["tops"]) <= 2 and row["inside"], str(row))
    pg.touchscreen.tap(*_tab_point(pg, "role-panel"))
    pg.wait_for_timeout(500)
    opened = _open(pg, "role-panel")
    pg.tap("#role-panel .rp-body .rp-row:nth-child(3)")
    pg.wait_for_timeout(400)
    n = pg.evaluate("document.querySelectorAll('#role-panel .rp-row.revealed').length")
    paused = _paused(pg)
    pg.tap("#video")
    pg.wait_for_timeout(500)
    C.check("landscape phone: the ROLES tab opens on a tap, a row reveals, a tap on the video closes it",
            opened and n >= 1 and not _open(pg, "role-panel") and _paused(pg) == paused, f"opened={opened} n={n}")
    pg.set_viewport_size({"width": 390, "height": 844})
    pg.wait_for_timeout(1000)
    C.check("upright again: the panels dock below the player", _parent(pg, "#role-panel") == "player-dock")
    C.check("iPhone: no page or console errors", not errs, "; ".join(errs)[:300])
    ctx.close()

    # ── A tablet ──
    ctx = browser.new_context(**TABLET)
    pg = ctx.new_page()
    errs = watch_errors(pg)
    open_app(pg, base)
    lay = {k: _box(pg, s) for k, s in (("player", "#player-container"), ("library", "#sidebar-left"),
                                        ("search", "#sidebar-right"))}
    C.check("tablet: the player across the top, library and search side by side below it",
            _no_sideways_scroll(pg) and lay["player"]["w"] > 780 and lay["library"]["y"] >= lay["player"]["b"]
            and abs(lay["library"]["y"] - lay["search"]["y"]) < 1 and lay["library"]["r"] <= lay["search"]["x"],
            json.dumps(lay))
    pg.touchscreen.tap(*_tab_point(pg, "role-panel"))
    pg.wait_for_timeout(500)
    C.check("tablet: the ROLES tab opens on a tap", _open(pg, "role-panel") and _parent(pg, "#role-panel") == "video-wrapper")
    C.check("tablet: no page or console errors", not errs, "; ".join(errs)[:300])
    ctx.close()

    # ── A laptop stays as it was ──
    ctx = browser.new_context(viewport={"width": 1366, "height": 768})
    pg = ctx.new_page()
    open_app(pg, base)
    lay = {k: _box(pg, s) for k, s in (("player", "#player-container"), ("library", "#sidebar-left"),
                                        ("search", "#sidebar-right"))}
    gone = pg.evaluate("['#back-btn', '#pane-tabs', '#player-dock', '#edit-handles-btn']"
                       ".filter(s => getComputedStyle(document.querySelector(s)).display !== 'none')")
    C.check("laptop: three columns, and none of the touch or phone extras",
            abs(lay["library"]["y"] - lay["player"]["y"]) < 1 and abs(lay["search"]["y"] - lay["player"]["y"]) < 1
            and lay["library"]["r"] <= lay["player"]["x"] and not gone
            and _style(pg, "#volume-slider", "display") != "none", f"{json.dumps(lay)} shown={gone}")
    ctx.close()
