"""Regression walk of the core player on the demo games: library grouping,
masks and mask modes, per-seat frames, the role panel (pack wolves, seat and
role modes), the card viewing (看牌) marker and jump, night overlay and
auto-mute, night jumps, mute, edit persistence, fullscreen mask fit and the
hidden-roles behaviour."""
import json

from harness import (G1, G2, G3, DEMO_IDS, active_id, api, ctl, current_time, open_app, open_panel, park_mouse,
                     show_controls, watch_errors, wrapper_box)

PACK = {1, 6, 8, 12}          # the 狼人 seats of demo game 1 (all pack wolves)
DAY_T, NIGHT_T = 210, 300     # demo game 1: 看牌 0:50-1:30, nights about 1:30-2:42 and 4:40-5:32
CARD_T = 70                   # inside the card viewing


def _revealed(page):
    return set(page.evaluate("[...document.querySelectorAll('#role-panel .rp-body .rp-row.revealed .rp-num')]"
                             ".map(n => parseInt(n.textContent))"))


def run(base, run_dir, C, browser):
    pg = browser.new_page(viewport={"width": 1600, "height": 1000})
    errs = watch_errors(pg)
    open_app(pg, base)
    pg.evaluate("localStorage.clear()")
    open_app(pg, base)

    heads = pg.evaluate("[...document.querySelectorAll('#video-list li.lib-group')].map(h => [h.dataset.group,"
                        " h.querySelector('.lib-group-count').textContent])")
    C.check("library groups the games by episode", heads == [["S01E01", "2 games"], ["S01E02", "1 game"]], str(heads))
    C.check("only the hidden-roles game carries the badge", pg.evaluate(
        f"!!document.querySelector('#video-list li[data-id=\"{G2}\"] .video-badge') && "
        f"!document.querySelector('#video-list li[data-id=\"{G1}\"] .video-badge')"))
    C.check("every row has star, re-analyse and delete buttons", pg.evaluate(
        "[...document.querySelectorAll('#video-list li.lib-item')].every(li => li.querySelector('.video-star') && "
        "li.querySelector('.video-re-btn') && li.querySelector('.video-del-btn:not(.video-re-btn)'))"))
    C.check("episode headers carry a delete button", pg.evaluate("document.querySelectorAll('#video-list li.lib-group .lib-group-del').length") == 2)

    C.check("the first game opens", active_id(pg) == G1, str(active_id(pg)))
    st = pg.evaluate("document.getElementById('status').textContent")
    C.check("metadata loaded with both nights", "2 night phases" in st, st)
    vs = pg.evaluate("(() => { const v = document.getElementById('video'); return {w: v.videoWidth, err: v.error && v.error.code}; })()")
    C.check("the video decodes in the browser", vs["w"] == 1920 and not vs["err"], json.dumps(vs))
    C.check("the info bar shows the full title", "Demo Cup S01E01" in pg.evaluate("document.getElementById('video-title').textContent"))
    C.check("two night markers on the progress bar", pg.evaluate("document.querySelectorAll('.night-marker').length") == 2)
    C.check("two night entries in the PHASES panel", pg.evaluate("document.querySelectorAll('.night-jump-group').length") == 2)
    C.check("the status names the card viewing", "看牌 at 0:49" in st, st)
    card = pg.evaluate("(() => { const c = [...document.querySelectorAll('.card-marker')]; const n = document.querySelector('.night-marker');"
                       " return {n: c.length, left: c.length && parseFloat(c[0].style.left), night: parseFloat(n.style.left),"
                       " color: c.length && getComputedStyle(c[0]).backgroundColor, tip: c.length && c[0].dataset.tooltip}; })()")
    C.check("one 看牌 marker on the progress bar, before the first night, not red",
            card["n"] == 1 and card["left"] < card["night"] and card["tip"].startswith("看牌")
            and not card["color"].startswith("rgba(224, 72, 72"), json.dumps(card, ensure_ascii=False))

    pg.evaluate(f"document.getElementById('video').currentTime = {DAY_T}")
    pg.wait_for_timeout(1500)
    park_mouse(pg)
    masks = pg.evaluate("[...document.querySelectorAll('.name-mask')].map(m => { const b = m.getBoundingClientRect();"
                        " const w = document.getElementById('video-wrapper').getBoundingClientRect();"
                        " return {hidden: m.classList.contains('hidden'), l: b.x - w.x, r: w.x + w.width - (b.x + b.width),"
                        " frames: m.querySelectorAll('.name-mask-frame').length}; })")
    C.check("two masks visible during the day", len(masks) == 2 and not any(m["hidden"] for m in masks), str(masks))
    C.check("Full masks reach both frame edges", any(m["l"] <= 0 for m in masks) and any(m["r"] <= 0 for m in masks))
    C.check("each mask has six per-seat wire frames", [m["frames"] for m in masks] == [6, 6], str([m["frames"] for m in masks]))
    ctl(pg, "#mask-mode-btn")
    pg.wait_for_timeout(300)
    lefts = pg.evaluate("[...document.querySelectorAll('.name-mask')].map(m => m.getBoundingClientRect().x -"
                        " document.getElementById('video-wrapper').getBoundingClientRect().x)")
    C.check("Roles mode pulls the masks in from the edges",
            pg.evaluate("document.getElementById('mask-mode-btn').textContent") == "Mask: Roles" and all(x > 10 for x in lefts), str(lefts))
    ctl(pg, "#mask-mode-btn")
    pg.wait_for_timeout(300)

    open_panel(pg)
    C.check("the role panel opens on right-edge hover", pg.evaluate("document.getElementById('role-panel').matches(':hover')"))
    pg.click("#role-panel .rp-actions .rp-btn:nth-child(1)")
    pg.click("#role-panel .rp-modes .rp-mode-btn:nth-child(1)")
    pg.wait_for_timeout(300)
    rows = pg.evaluate("document.querySelectorAll('#role-panel .rp-body .rp-row').length")
    C.check("By role lists twelve entries", rows == 12, str(rows))
    pg.click("#role-panel .rp-body .rp-row.rp-wolf")
    pg.wait_for_timeout(400)
    C.check("picking a pack wolf reveals the whole pack (4)",
            pg.evaluate("document.querySelectorAll('#role-panel .rp-body .rp-row.revealed').length") == 4)
    fills = pg.evaluate("[...document.querySelectorAll('.name-mask')].map(m => m.querySelectorAll('.name-mask-fill').length)")
    C.check("the masks open gaps at the revealed rows", sum(fills) > 2, str(fills))
    pg.click("#role-panel .rp-actions .rp-btn:nth-child(1)")
    pg.wait_for_timeout(300)
    C.check("Blind hides everything", pg.evaluate("document.querySelectorAll('#role-panel .rp-row.revealed').length") == 0)
    pg.click("#role-panel .rp-actions .rp-btn:nth-child(2)")
    pg.wait_for_timeout(300)
    C.check("All reveals everyone", pg.evaluate("document.querySelectorAll('#role-panel .rp-row.revealed').length") == 12)
    pg.click("#role-panel .rp-actions .rp-btn:nth-child(1)")
    pg.click("#role-panel .rp-modes .rp-mode-btn:nth-child(2)")
    pg.wait_for_timeout(300)
    seats = pg.evaluate("[...document.querySelectorAll('#role-panel .rp-body .rp-row .rp-num')].map(n => parseInt(n.textContent))")
    C.check("By seat lists seats 1-12", seats == list(range(1, 13)), str(seats))
    C.check("blind seat mode shows no wolf markers", pg.evaluate("document.querySelectorAll('#role-panel .rp-row.rp-wolf, #role-panel .rp-paw').length") == 0)
    pg.click("#role-panel .rp-body .rp-row:nth-child(1)")
    pg.wait_for_timeout(300)
    C.check("seat 1 (a pack wolf) reveals exactly the pack", _revealed(pg) == PACK, str(sorted(_revealed(pg))))
    pg.click("#role-panel .rp-actions .rp-btn:nth-child(1)")
    pg.click("#role-panel .rp-body .rp-row:nth-child(2)")
    pg.wait_for_timeout(300)
    r2 = pg.evaluate("document.querySelector('#role-panel .rp-body .rp-row:nth-child(2) .rp-role').textContent")
    C.check("seat 2 reveals only itself, as 预言家", _revealed(pg) == {2} and r2 == "预言家", f"{sorted(_revealed(pg))} {r2}")
    pg.click("#role-panel .rp-actions .rp-btn:nth-child(1)")
    pg.click("#role-panel .rp-modes .rp-mode-btn:nth-child(1)")
    park_mouse(pg)

    open_panel(pg, "left")
    C.check("the PHASES panel opens on left-edge hover", pg.evaluate("document.getElementById('night-jump-buttons').matches(':hover')"))
    rows = pg.evaluate("[...document.querySelectorAll('#night-jump-buttons > div')].map(d => d.className)")
    C.check("the PHASES panel lists 看牌 first, then the nights",
            rows == ["card-jump-group", "night-jump-group", "night-jump-group"], str(rows))
    pg.click(".card-jump-btn:not(.jump-end)")
    pg.wait_for_timeout(800)
    tc = current_time(pg)
    C.check("the 看牌 button jumps to the card viewing", 45 < tc < 55, str(tc))
    pg.evaluate(f"document.getElementById('video').currentTime = {CARD_T}")
    pg.wait_for_timeout(1200)
    C.check("no night overlay during 看牌", pg.evaluate("document.getElementById('night-overlay').classList.contains('hidden')"))
    C.check("no masks during 看牌 (no roles on screen yet)",
            pg.evaluate("[...document.querySelectorAll('.name-mask')].every(m => m.classList.contains('hidden'))"))
    pg.click(".night-jump-btn:not(.jump-end)")
    pg.wait_for_timeout(800)
    t1 = current_time(pg)
    pg.evaluate("document.getElementById('video').currentTime += 5")
    pg.wait_for_timeout(1200)
    C.check("the first night button jumps to the first night, where 看牌 ends", 85 < t1 < 95, str(t1))
    C.check("the night overlay covers a night", not pg.evaluate("document.getElementById('night-overlay').classList.contains('hidden')"))
    C.check("the phase chip reads Night", pg.evaluate("(() => { const p = document.getElementById('phase-indicator');"
                                                    " return p.textContent.includes('Night') && p.classList.contains('night'); })()"))
    C.check("the video is muted during a night", pg.evaluate("document.getElementById('video').muted"))
    park_mouse(pg)
    pg.keyboard.press("n")
    pg.wait_for_timeout(800)
    C.check("N jumps to the next night", 270 < current_time(pg) < 290, str(current_time(pg)))

    pg.evaluate(f"document.getElementById('video').currentTime = {DAY_T}")
    pg.wait_for_timeout(1500)
    ctl(pg, "#mute-btn")
    pg.wait_for_timeout(200)
    C.check("the mute button mutes", pg.evaluate("document.getElementById('video').muted"))
    ctl(pg, "#mute-btn")
    pg.wait_for_timeout(200)
    C.check("the mute button unmutes", not pg.evaluate("document.getElementById('video').muted"))

    before = pg.evaluate("document.querySelectorAll('.night-marker').length")
    ctl(pg, "#edit-menu-btn")
    pg.wait_for_timeout(200)
    pg.click("#add-phase-btn")
    pg.wait_for_timeout(1200)
    saved = json.loads((run_dir / G1 / "metadata.json").read_text())
    C.check("+ Night phase adds a phase and saves it",
            pg.evaluate("document.querySelectorAll('.night-marker').length") == before + 1 and len(saved["night_phases"]) == before + 1)
    C.check("the detected phases are kept as originals", len(saved.get("original_night_phases", [])) == before)
    ctl(pg, "#edit-menu-btn")
    pg.wait_for_timeout(200)
    pg.click("#reset-nights-btn")
    pg.wait_for_timeout(1200)
    saved = json.loads((run_dir / G1 / "metadata.json").read_text())
    C.check("Reset nights restores the detected phases", len(saved["night_phases"]) == before)

    # A page holding an outdated copy must not undo a newer write (a
    # re-analysis, or a save from another tab): the server refuses it and the
    # page loads the current version
    meta_path = run_dir / G1 / "metadata.json"
    hdr = pg.evaluate(f"fetch('/{G1}/metadata.json').then(r => [r.headers.get('X-Metadata-Version'), r.headers.get('Cache-Control')])")
    C.check("metadata.json is served with a version and never cached", bool(hdr[0]) and hdr[1] == "no-store", str(hdr))
    st, r = api(base, "/api/metadata", {"videoId": G1, "version": "0000000000000000",
                                        "night_phases": saved["night_phases"], "name_masks": saved["name_masks"]})
    C.check("a save against an old version is refused (409)", st == 409 and r.get("stale") is True, f"{st} {r}")
    newer = json.loads(meta_path.read_text())
    newer["night_phases"] = newer["night_phases"] + [{"start": 395.0, "end": 400.0}]
    meta_path.write_text(json.dumps(newer, ensure_ascii=False, indent=2))   # e.g. a re-analysis
    ctl(pg, "#edit-menu-btn")
    pg.wait_for_timeout(200)
    pg.click("#add-phase-btn")
    pg.wait_for_timeout(1500)
    on_disk = json.loads(meta_path.read_text())
    C.check("an edit made on an outdated page does not overwrite the newer file",
            on_disk["night_phases"] == newer["night_phases"], str(len(on_disk["night_phases"])))
    st_text = pg.evaluate("document.getElementById('status').textContent")
    C.check("...the page loads the current version instead and says so",
            "changed since it was opened" in st_text
            and pg.evaluate("document.querySelectorAll('.night-marker').length") == len(newer["night_phases"]), st_text)
    ctl(pg, "#edit-menu-btn")
    pg.wait_for_timeout(200)
    pg.click("#reset-nights-btn")
    pg.wait_for_timeout(1200)
    C.check("...and its next edit saves normally",
            len(json.loads(meta_path.read_text())["night_phases"]) == before
            and "saved" in pg.evaluate("document.getElementById('status').textContent"))

    ctl(pg, "#fullscreen-btn")
    pg.wait_for_timeout(1500)
    fit = pg.evaluate("(() => { const v = document.getElementById('video'); const w = document.getElementById('video-wrapper').getBoundingClientRect();"
                      " const m = document.getElementById('name-masks').getBoundingClientRect();"
                      " const s = Math.min(w.width / v.videoWidth, w.height / v.videoHeight);"
                      " return {fs: !!document.fullscreenElement, m: [m.x, m.y, m.width, m.height],"
                      " v: [(w.width - v.videoWidth * s) / 2, (w.height - v.videoHeight * s) / 2, v.videoWidth * s, v.videoHeight * s]}; })()")
    C.check("in fullscreen the masks sit on the letterboxed video", fit["fs"] and all(abs(a - b) < 1 for a, b in zip(fit["m"], fit["v"])), str(fit))
    pg.evaluate("document.exitFullscreen()")
    pg.wait_for_timeout(1200)

    pg.click(f'#video-list li[data-id="{G2}"]')
    pg.wait_for_timeout(2500)
    C.check("a hidden-roles game starts with masks off",
            pg.evaluate("document.getElementById('toggle-masks').textContent").startswith("Masks: Off"))
    pg.evaluate("document.getElementById('video').currentTime = 100")
    pg.wait_for_timeout(1500)
    C.check("...and no mask shows", pg.evaluate("[...document.querySelectorAll('.name-mask')].every(m => m.classList.contains('hidden'))"))
    open_panel(pg)
    C.check("...its role panel explains instead of listing",
            pg.evaluate("document.querySelectorAll('#role-panel .rp-row').length") == 0 and pg.evaluate("!!document.querySelector('#role-panel .rp-empty')"))
    park_mouse(pg)
    ctl(pg, "#toggle-masks")
    pg.wait_for_timeout(300)
    C.check("...and masks can still be forced on", pg.evaluate("document.getElementById('toggle-masks').textContent") == "Masks: On")

    pg.click('#video-list li.lib-group[data-group="S01E02"]')
    pg.wait_for_timeout(300)
    C.check("an episode collapses on click", pg.evaluate(f"getComputedStyle(document.querySelector('#video-list li[data-id=\"{G3}\"]')).display") == "none")
    pg.click('#video-list li.lib-group[data-group="S01E02"]')
    pg.wait_for_timeout(300)
    C.check("and expands again", pg.evaluate(f"getComputedStyle(document.querySelector('#video-list li[data-id=\"{G3}\"]')).display") != "none")
    C.check("no page or console errors", not errs, "; ".join(errs)[:300])
    pg.close()
