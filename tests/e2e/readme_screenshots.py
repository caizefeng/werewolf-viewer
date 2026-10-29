"""Retake the README screenshots (docs/screenshots/) on the demo games.

    processing/venv/bin/python3 tests/e2e/readme_screenshots.py [NAME ...]

NAME is a screenshot without .png (default: all of them). Every shot runs on
a throwaway demo server (see harness.py), so nothing here touches videos/.
bookmarks.png, a crop of the library list, is not retaken here.
"""
import sys
import time

from PIL import Image
from playwright.sync_api import sync_playwright

from harness import (CHROMIUM_ARGS, DEMO_IDS, G1, G2, G3, ROOT, api, demo_server, log, open_app, open_panel,
                     park_mouse, prepare_demo_library, show_controls)

OUT = ROOT / "docs" / "screenshots"
DAY, NIGHT = 210, 300   # demo game 1: day 2 (3:30) and night 2 (5:00)
PHONE = dict(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True, device_scale_factor=2)
PHONE_SIDEWAYS = dict(viewport={"width": 844, "height": 390}, has_touch=True, is_mobile=True, device_scale_factor=2)
# iPhone Safari has no Fullscreen API for the page: the viewer stands in
NO_FULLSCREEN_API = """
for (const name of ["requestFullscreen", "webkitRequestFullscreen"]) {
  Object.defineProperty(Element.prototype, name, {value: undefined, configurable: true});
}
Object.defineProperty(Document.prototype, "fullscreenEnabled", {get: () => false, configurable: true});
"""


def _save(png, name, width=1400):
    im = Image.open(png).convert("RGB")
    im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    # 256 colours, dithered against the palette: the stage's backlight is a
    # smooth gradient, which a plain palette shows as rings (Pillow dithers
    # only when quantizing to a given palette); about 2/3 of a full-colour PNG
    palette = im.quantize(colors=256, method=Image.Quantize.FASTOCTREE)
    im.quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG).save(OUT / f"{name}.png", optimize=True)
    log(f"{name}.png {im.size[0]}x{im.size[1]}")


def _shoot(pg, name, clip_player=False, width=1400):
    tmp = OUT / f".{name}.raw.png"
    if clip_player:
        r = pg.evaluate("(() => { const b = document.getElementById('player-container').getBoundingClientRect();"
                        " return {x: b.x, y: b.y, width: b.width, height: b.height}; })()")
        pg.screenshot(path=str(tmp), clip=r)
    else:
        pg.screenshot(path=str(tmp))
    _save(tmp, name, width)
    tmp.unlink()


def _reset_state(run_dir):
    """Forget bookmarks and resume points, so the next page opens game 1 fresh."""
    for v in DEMO_IDS:
        (run_dir / v / "viewer_state.json").unlink(missing_ok=True)


def _seek(pg, t):
    pg.evaluate(f"document.getElementById('video').currentTime = {t}")
    pg.wait_for_function("document.getElementById('video').readyState >= 2 && !document.getElementById('video').seeking")
    pg.wait_for_timeout(1200)


def _page(browser, base, context=None, init_script=None):
    ctx = browser.new_context(**(context or {"viewport": {"width": 1600, "height": 1000}, "device_scale_factor": 2}))
    if init_script:
        ctx.add_init_script(init_script)
    pg = ctx.new_page()
    pg.on("dialog", lambda d: d.accept())
    open_app(pg, base)
    pg.wait_for_function("document.getElementById('video').readyState >= 2", timeout=20000)
    return pg


def overview(browser, base, run_dir):
    """The whole app on day 2 of game 1, resumed there, two games starred."""
    for body in ({"videoId": G1, "bookmarked": True}, {"videoId": G3, "bookmarked": True},
                 {"videoId": G1, "position": DAY, "duration": 420}):
        api(base, "/api/state", body)
    pg = _page(browser, base)
    pg.wait_for_timeout(2500)
    park_mouse(pg)
    pg.wait_for_timeout(3500)                      # the controls hide
    _shoot(pg, "overview")


def night(browser, base, run_dir):
    """Night 2 under the overlay, with the PHASES panel open."""
    pg = _page(browser, base)
    _seek(pg, NIGHT)
    open_panel(pg, "left")
    pg.wait_for_timeout(800)
    _shoot(pg, "night", clip_player=True)


def mask_roles_mode(browser, base, run_dir):
    """Mask: Roles, where only the role column is covered."""
    pg = _page(browser, base)
    _seek(pg, DAY)
    show_controls(pg)
    pg.click("#mask-mode-btn")
    pg.wait_for_timeout(600)
    show_controls(pg)
    _shoot(pg, "mask-roles-mode", clip_player=True)


def reveal_role(browser, base, run_dir):
    """By role: picking 狼人 1 opens the whole pack on the masks."""
    pg = _page(browser, base)
    _seek(pg, DAY)
    open_panel(pg, "right")
    pg.click("#role-panel .rp-modes .rp-mode-btn:nth-child(1)")
    pg.click("#role-panel .rp-body .rp-row.rp-wolf")
    pg.wait_for_timeout(700)
    _shoot(pg, "reveal-role", clip_player=True)


def reveal_seat(browser, base, run_dir):
    """By seat: seats 2 and 9 revealed."""
    pg = _page(browser, base)
    _seek(pg, DAY)
    open_panel(pg, "right")
    pg.click("#role-panel .rp-modes .rp-mode-btn:nth-child(2)")
    pg.click("#role-panel .rp-body .rp-row:nth-child(2)")
    pg.click("#role-panel .rp-body .rp-row:nth-child(9)")
    pg.wait_for_timeout(700)
    _shoot(pg, "reveal-seat", clip_player=True)


def hidden_roles(browser, base, run_dir):
    """The hidden-roles game, its role panel explaining why nothing can be revealed."""
    for body in ({"videoId": G1, "bookmarked": True}, {"videoId": G3, "bookmarked": True},
                 {"videoId": G1, "position": DAY, "duration": 420},
                 {"videoId": G2, "position": 90, "duration": 180}):   # watched last: opens
        time.sleep(0.05)   # watchedAt is in ms: two writes in one ms tie, and the tie opens game 1
        api(base, "/api/state", body)
    pg = _page(browser, base)
    pg.wait_for_timeout(2500)
    open_panel(pg, "right")
    pg.wait_for_timeout(1000)
    _shoot(pg, "hidden-roles")


def edit_menu(browser, base, run_dir):
    """The ✎ Edit popover in the controls bar."""
    pg = _page(browser, base)
    _seek(pg, DAY)
    show_controls(pg)
    pg.click("#mask-mode-btn")                     # Roles, then back to Full: the status
    pg.click("#mask-mode-btn")                     # line explains Full coverage
    show_controls(pg)
    pg.click("#edit-menu-btn")
    pg.wait_for_timeout(600)
    _shoot(pg, "edit-menu", clip_player=True)


def jobs(browser, base, run_dir):
    """Three jobs: game 1 re-analysing, the other two downloaded from the
    search, one analysing and one queued behind the two analysis slots."""
    for v in (G2, G3):
        api(base, "/api/delete", {"videoId": v})
    pg = _page(browser, base)
    pg.fill("#search-input", "demo cup")
    pg.click("#search-btn")
    pg.wait_for_selector(f'.sr-btn-dl[data-id="{G3}"]')
    pg.hover(f'#video-list li[data-id="{G1}"]')
    pg.click(f'#video-list li[data-id="{G1}"] .video-re-btn')
    for v in (G2, G3):
        pg.click(f'.sr-btn-dl[data-id="{v}"]')
    deadline = time.time() + 120
    while time.time() < deadline:                  # two analyses running, one waiting for a slot
        jobs_now = api(base, "/api/job-status")[1]["jobs"]
        phases = sorted(j["phase"] for j in jobs_now if j["active"])
        if phases == ["processing", "processing", "waiting"]:
            break
        time.sleep(1)
    else:
        raise RuntimeError(f"jobs never reached two analysing + one queued: {phases}")
    pg.wait_for_timeout(2500)                      # the page polls every 2 s
    park_mouse(pg)
    _shoot(pg, "jobs")


def phone(browser, base, run_dir):
    """An upright phone: the controls under the video, the PHASES and ROLES
    panels docked below the player, the wolf pack revealed By role."""
    pg = _page(browser, base, PHONE)
    _seek(pg, DAY)
    pg.tap("#role-panel .rp-modes .rp-mode-btn:nth-child(1)")
    pg.tap("#role-panel .rp-body .rp-row.rp-wolf")
    pg.wait_for_timeout(700)
    pg.evaluate("window.scrollTo(0, 0)")
    pg.wait_for_timeout(300)
    _shoot(pg, "phone", width=780)


def phone_sideways(browser, base, run_dir):
    """A phone on its side in fullscreen (the iPhone stand-in), its ROLES
    panel tapped open."""
    pg = _page(browser, base, PHONE_SIDEWAYS, NO_FULLSCREEN_API)
    _seek(pg, DAY)
    pg.tap("#video")                               # a first tap brings up the controls
    pg.tap("#fullscreen-btn")
    pg.wait_for_timeout(800)
    b = pg.evaluate("(() => { const r = document.getElementById('role-panel').getBoundingClientRect();"
                    " return [r.x, r.y + r.height / 2]; })()")
    pg.touchscreen.tap(b[0] - 10, b[1])             # its tab, just inside the video's edge
    pg.wait_for_timeout(800)
    _shoot(pg, "phone-sideways", width=1200)


SHOTS = {"overview": overview, "night": night, "mask-roles-mode": mask_roles_mode, "reveal-role": reveal_role,
         "reveal-seat": reveal_seat, "hidden-roles": hidden_roles, "edit-menu": edit_menu, "jobs": jobs,
         "phone": phone, "phone-sideways": phone_sideways}


def main():
    names = sys.argv[1:] or list(SHOTS)
    unknown = [n for n in names if n not in SHOTS]
    if unknown:
        sys.exit(f"unknown screenshot(s): {', '.join(unknown)}; known: {', '.join(SHOTS)}")
    library = prepare_demo_library()
    with sync_playwright() as p:
        browser = p.chromium.launch(args=CHROMIUM_ARGS)
        for name in names:
            # one server per shot: each starts from the full demo library
            with demo_server(library) as (base, run_dir):
                _reset_state(run_dir)
                SHOTS[name](browser, base, run_dir)
        browser.close()


if __name__ == "__main__":
    main()
