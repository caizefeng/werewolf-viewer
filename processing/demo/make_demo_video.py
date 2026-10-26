#!/usr/bin/env python3
"""Render synthetic 12-player werewolf broadcasts for demos and screenshots.

Nothing here comes from a real stream: the stage, the player cards, the
role ribbons, the night tint and the phase banners are all drawn, with
made-up players. Like a broadcast's speaking shot, the middle of the frame
shows the player who has the floor, as a simple backlit person icon (round
head over a rounded body) at a desk with a seat name plate; the speaker
changes every few seconds, and at night the camera stays on one player, who
wears an eye mask under the red light. The layout follows what the analysis
expects (role ribbons at x~0.10 / x~0.89, rows pitched 0.16 from y=0.125,
number badges outward of the ribbons, sidebar hidden at night, "天黑请闭眼" /
"天亮请睁眼" banners), so the real pipeline can analyse these clips end to
end. Game 1 also opens like a real broadcast: a still studio shot, then the
card-viewing tour (看牌) of the twelve seats, cut straight to the first night.

Usage: make_demo_video.py OUT_DIR            # writes OUT_DIR/<id>/video.mp4 + info.json
Needs ffmpeg on PATH and a CJK font (macOS: STHeiti).
"""
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1920, 1080, 30
FONT_CJK = next((p for p in ("/System/Library/Fonts/STHeiti Medium.ttc", "/System/Library/Fonts/PingFang.ttc",
                              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc") if os.path.exists(p)), None)
if not FONT_CJK:
    sys.exit("No CJK font found")

FACTION = {"狼人": (176, 48, 48), "预言家": (47, 95, 168), "女巫": (47, 95, 168), "猎人": (47, 95, 168),
           "守卫": (47, 95, 168), "平民": (46, 139, 87), "未知": (96, 96, 108)}
ROW_Y = [0.125 + 0.16 * i for i in range(6)]
NAMES = ["Ash", "Bea", "Cal", "Dee", "Eli", "Fay", "Gus", "Hal", "Ivy", "Jun", "Kai", "Lou"]

GAMES = [
    {"id": "demoS01E01g1", "title": "Demo Cup S01E01 第一局 预女猎守 260101 werewolf", "dur": 420,
     "roles": ["狼人", "预言家", "平民", "守卫", "猎人", "狼人", "平民", "狼人", "女巫", "平民", "平民", "狼人"],
     "studio": (0, 50), "tour": (50, 90),
     "nights": [(90, 160), (280, 330)], "closeups": [(115, 135)],
     "notes": {1: "跳预言家", 3: "站边1", 5: "守1", 8: "认平民", 10: "我是好人"}},
    {"id": "demoS01E01g2", "title": "Demo Cup S01E01 第二局 隐藏身份 260101 werewolf", "dur": 180,
     "roles": ["未知"] * 12, "revealed": {2: "狼人", 9: "预言家"},
     "nights": [(25, 70), (120, 165)], "closeups": [], "notes": {}},
    {"id": "demoS01E02g1", "title": "Demo Cup S01E02 第一局 预女猎守 260102 werewolf", "dur": 240,
     "roles": ["平民", "狼人", "女巫", "狼人", "平民", "预言家", "猎人", "平民", "狼人", "守卫", "狼人", "平民"],
     "nights": [(28, 85), (170, 220)], "closeups": [(45, 60)],
     "notes": {2: "跳猎人", 6: "验2查杀", 7: "站边6"}},
]


def font(size, cjk=True):
    return ImageFont.truetype(FONT_CJK, size)


SILHOUETTE = (26, 23, 32)


def _backdrop():
    """Studio wall: dark blue-violet with a warm backlight behind the
    speaker's head, light strips, the desk and the floor."""
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((x - W / 2) / (W * 0.25)) ** 2 + ((y - H * 0.40) / (H * 0.44)) ** 2)
    k = (np.clip(1.15 - r, 0, 1) ** 1.6)[..., None]
    wall = np.array([30, 28, 46], np.float32) * (1 - k) + np.array([224, 194, 160], np.float32) * k
    img = Image.fromarray(wall.astype(np.uint8))
    d = ImageDraw.Draw(img)
    for xs in (0.335, 0.665):                                            # light strips
        d.rounded_rectangle([W * xs - 7, H * 0.10, W * xs + 7, H * 0.74], radius=7, fill=(92, 86, 140))
    d.rectangle([0, int(H * 0.86), W, H], fill=(40, 38, 50))             # floor
    return img


_BACKDROP = []


def backdrop():
    if not _BACKDROP:
        _BACKDROP.append(_backdrop())
    return _BACKDROP[0].copy()


HEAD_Y, HEAD_R = 0.36 * H, 104   # the person icon's head: centre (frame y) and radius at scale 1


def person_mask(cx=W / 2, scale=1.0, top=0.0):
    """'L' mask of a player as a simple person icon: a round head floating
    over a rounded body, the same for everyone (the name plate says who).
    Drawn at twice the size and scaled down for smooth edges."""
    s = 2
    m = Image.new("L", (W * s, H * s), 0)
    d = ImageDraw.Draw(m)
    x, u = cx * s, scale * s
    hy, r = (HEAD_Y + top) * s, HEAD_R * u
    d.ellipse([x - r, hy - r, x + r, hy + r], fill=255)                 # head
    y0 = hy + r + 28 * u                                                 # body, a gap below the head
    d.rounded_rectangle([x - 290 * u, y0, x + 290 * u, y0 + 760 * u], radius=int(260 * u), fill=255)
    return m.resize((W, H), Image.LANCZOS)


def draw_eye_mask(d, cx=W / 2, scale=1.0, top=0.0):
    """The sleep mask players wear at night: a band across the head."""
    hy, r = HEAD_Y + top, HEAD_R * scale
    d.rounded_rectangle([cx - r - 8 * scale, hy - 24 * scale, cx + r + 8 * scale, hy + 20 * scale],
                        radius=int(16 * scale), fill=(214, 210, 222))


def draw_stage(img, label, seat, eye_mask=False):
    """The speaking shot: seat's player as a backlit person icon at the desk,
    with the seat's name plate and a microphone (eye_mask: at night)."""
    img.paste(SILHOUETTE, mask=person_mask())
    d = ImageDraw.Draw(img)
    if eye_mask:
        draw_eye_mask(d)
    d.line([(W * 0.5 + 118, H * 0.80), (W * 0.5 + 80, H * 0.52)], fill=(128, 126, 138), width=8)   # mic
    d.ellipse([W * 0.5 + 58, H * 0.465, W * 0.5 + 102, H * 0.535], fill=(84, 82, 94), outline=(156, 154, 166), width=3)
    d.rounded_rectangle([W * 0.24, H * 0.78, W * 0.76, H * 0.95], radius=18, fill=(52, 46, 58))     # desk
    d.line([(W * 0.24 + 18, H * 0.78), (W * 0.76 - 18, H * 0.78)], fill=(104, 94, 108), width=5)
    y = H * 0.865                                                        # name plate
    d.rounded_rectangle([W * 0.5 - 170, y - 38, W * 0.5 + 170, y + 38], radius=14, fill=(244, 238, 226),
                        outline=(120, 96, 60), width=3)
    d.ellipse([W * 0.5 - 158, y - 28, W * 0.5 - 102, y + 28], fill=(230, 200, 90), outline=(120, 90, 20), width=2)
    d.text((W * 0.5 - 130, y), str(seat), fill=(40, 30, 10), font=font(30), anchor="mm")
    d.text((W * 0.5 + 34, y), NAMES[seat - 1], fill=(50, 40, 30), font=font(44), anchor="mm")
    d.rounded_rectangle([W * 0.40, H * 0.015, W * 0.60, H * 0.075], radius=14, fill=(52, 48, 70), outline=(150, 140, 180), width=2)
    d.text((W * 0.50, H * 0.045), "DEMO CUP · 演示赛", fill=(235, 230, 220), font=font(30), anchor="mm")
    if label:
        d.text((W * 0.30, H * 0.045), label, fill=(200, 196, 190), font=font(26), anchor="mm")
    d.text((W * 0.18, H * 0.965), "配置: 预女猎守", fill=(200, 196, 190), font=font(24), anchor="lm")


def draw_sidebar(d, side, roles, notes, revealed):
    for i in range(6):
        seat = i + 1 if side == "left" else i + 7
        yc = ROW_Y[i] * H
        if side == "left":
            badge_x, avatar_x, ribbon_x0, note_x = W * 0.014, W * 0.045, W * 0.101, W * 0.134
        else:
            badge_x, avatar_x, ribbon_x0, note_x = W * 0.990, W * 0.955, W * 0.877, W * 0.870
        # avatar + name
        d.ellipse([avatar_x - 54, yc - 66, avatar_x + 54, yc + 42], fill=(90, 84, 100), outline=(190, 180, 150), width=4)
        d.text((avatar_x, yc - 12), NAMES[seat - 1][:2].upper(), fill=(235, 230, 220), font=font(34), anchor="mm")
        d.rounded_rectangle([avatar_x - 60, yc + 46, avatar_x + 60, yc + 78], radius=8, fill=(60, 56, 70))
        d.text((avatar_x, yc + 62), NAMES[seat - 1], fill=(235, 230, 220), font=font(22), anchor="mm")
        # number badge, outward of the ribbon
        d.ellipse([badge_x - 20, yc - 60, badge_x + 20, yc - 20], fill=(230, 200, 90), outline=(120, 90, 20), width=2)
        d.text((badge_x, yc - 40), f"{seat:02d}", fill=(40, 30, 10), font=font(20), anchor="mm")
        # role ribbon: vertical label
        role = revealed.get(seat, roles[seat - 1])
        rib_h = 118 if len(role) <= 2 else 136
        d.rounded_rectangle([ribbon_x0, yc - rib_h / 2, ribbon_x0 + W * 0.026, yc + rib_h / 2], radius=10,
                            fill=FACTION.get(role, (96, 96, 108)), outline=(240, 220, 160), width=3)
        fs = 34 if len(role) <= 2 else 30
        step = fs + 4
        top = yc - step * (len(role) - 1) / 2
        for k, ch in enumerate(role):
            d.text((ribbon_x0 + W * 0.013, top + k * step), ch, fill=(255, 255, 255), font=font(fs), anchor="mm")
        # director's note next to the ribbon
        note = notes.get(seat)
        if note:
            anchor = "lm" if side == "left" else "rm"
            d.text((note_x, yc - 30), note, fill=(255, 225, 140), font=font(24), anchor=anchor)


def banner_night(img):
    d = ImageDraw.Draw(img)
    x, top = W * 0.445, H * 0.06
    for k, ch in enumerate("天黑请闭眼"):
        d.text((x, top + k * 78), ch, fill=(255, 250, 240), font=font(68), anchor="mm",
               stroke_width=3, stroke_fill=(40, 20, 20))


def banner_dawn(img):
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([W * 0.36, H * 0.10, W * 0.64, H * 0.18], radius=16, fill=(60, 40, 110))
    d.text((W * 0.50, H * 0.14), "天亮请睁眼", fill=(255, 250, 240), font=font(60), anchor="mm")


def closeup_frame():
    """The wolves' discussion card: brightly lit like a real close-up (a hard
    camera cut from the red table, frame difference well above CUT_THRESH)
    with the studio's red light bleeding in (corner R/G ~1.6)."""
    img = Image.new("RGB", (W, H), (196, 124, 112))
    d = ImageDraw.Draw(img)
    d.rectangle([0, int(H * 0.62), W, H], fill=(206, 130, 118))
    for cx in (W * 0.3, W * 0.7):                                       # two wolves, awake
        img.paste(SILHOUETTE, mask=person_mask(cx=cx, scale=0.85, top=H * 0.06))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([W * 0.32, H * 0.84, W * 0.68, H * 0.93], radius=16, fill=(250, 244, 236))
    d.text((W * 0.5, H * 0.885), "夜间讨论 · 画面已遮挡", fill=(80, 40, 36), font=font(40), anchor="mm")
    return np.asarray(img)


def studio_frame():
    """Pre-game: the commentators' desk, one still shot."""
    img = Image.new("RGB", (W, H), (40, 46, 70))
    d = ImageDraw.Draw(img)
    d.rectangle([0, int(H * 0.70), W, H], fill=(28, 30, 46))
    d.rounded_rectangle([W * 0.18, H * 0.12, W * 0.82, H * 0.58], radius=24, fill=(66, 84, 128), outline=(150, 170, 220), width=6)
    d.text((W * 0.5, H * 0.35), "DEMO CUP 演播室", fill=(235, 238, 248), font=font(96), anchor="mm")
    for cx in (W * 0.36, W * 0.64):                                     # two commentators
        img.paste((18, 20, 34), mask=person_mask(cx=cx, scale=0.6, top=H * 0.15))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([W * 0.08, H * 0.80, W * 0.92, H * 0.86], radius=10, fill=(90, 70, 40))
    return np.asarray(img)


SEAT_COLORS = [(150, 90, 80), (80, 120, 150), (110, 140, 90), (150, 120, 70), (120, 90, 150), (90, 140, 140),
               (160, 100, 120), (100, 110, 160), (140, 140, 90), (90, 120, 110), (150, 110, 100), (110, 100, 140)]


def seat_closeup(seat):
    """Card viewing: one player's close-up, a person icon against the seat's
    wall panels holding a face-down role card, with the seat's name plate on
    the table."""
    img = Image.new("RGB", (W, H), tuple(int(c * 0.55) for c in SEAT_COLORS[seat - 1]))
    d = ImageDraw.Draw(img)
    # Light wall panels: the camera's pans from seat to seat are what the
    # card detector measures, and a dark figure on dark panels barely
    # changes a small grey thumbnail when panned (pans 5%, rejected; ~47% on
    # these, against the 30% the detector needs)
    for k in range(6):
        x0 = W * (0.02 + 0.165 * k)
        d.rectangle([x0, H * 0.06, x0 + W * 0.14, H * 0.52], fill=tuple(int(c * 0.55 + 110) for c in SEAT_COLORS[(seat + k) % 12]))
    img.paste(SILHOUETTE, mask=person_mask(top=H * 0.02))
    d = ImageDraw.Draw(img)
    d.rectangle([0, int(H * 0.78), W, H], fill=(92, 72, 58))            # table edge
    d.rounded_rectangle([W * 0.55, H * 0.58, W * 0.66, H * 0.80], radius=12, fill=(236, 230, 214), outline=(120, 60, 50), width=5)
    d.rounded_rectangle([W * 0.565, H * 0.60, W * 0.645, H * 0.78], radius=8, outline=(176, 80, 64), width=4)
    d.rounded_rectangle([W * 0.40, H * 0.84, W * 0.60, H * 0.95], radius=14, fill=(246, 240, 228), outline=(80, 60, 40), width=3)
    d.text((W * 0.5, H * 0.895), f"{seat}  {NAMES[seat - 1]}", fill=(60, 44, 30), font=font(48), anchor="mm")
    return np.asarray(img)


TOUR_HOLD = 1.6  # seconds held on each seat before panning to the next


def tour_frame(closeups, t, t0, t1):
    """The director tours the seats 1 -> 12: hold each close-up, then pan
    sideways to the next (eased), as the broadcasts do while players look at
    their cards."""
    per = (t1 - t0) / 12
    k = min(11, int((t - t0) // per))
    u = (t - t0) - k * per
    if k == 11 or u < TOUR_HOLD:
        return closeups[k]
    p = (u - TOUR_HOLD) / (per - TOUR_HOLD)
    p = p * p * (3 - 2 * p)
    x = int(round(p * W))
    return np.concatenate([closeups[k][:, x:], closeups[k + 1][:, :x]], axis=1)


def tint_night(frame, k=1.0):
    """Red studio light; k in [0, 1] fades it in (real lights take seconds,
    and the detector treats a one-frame switch as a camera cut)."""
    f = frame.astype(np.float32)
    f[..., 0] = np.clip(f[..., 0] * (1 + 0.25 * k) + 20 * k, 0, 255)
    f[..., 1] *= 1 - 0.68 * k
    f[..., 2] *= 1 - 0.70 * k
    return f.astype(np.uint8)


FADE = 3.0  # seconds the light (and the sidebar) take to change at each night boundary
SPEECH = 6  # seconds each player speaks before the camera moves to the next
# Around a night the camera stays on one player, so the light changes on a
# still shot, which the detector reads as a day/night transition, not a cut
HOLD = 8


def render(game, out_dir):
    nights = game["nights"]
    closeups = game.get("closeups", [])
    notes = game.get("notes", {})
    revealed = game.get("revealed", {})
    stages, frames, night_bases = {}, {}, {}

    def stage(seat, label=None, eye_mask=False):
        """The speaking shot of seat's player, without the sidebar (cached)."""
        key = (seat, label, eye_mask)
        if key not in stages:
            img = backdrop()
            draw_stage(img, label, seat, eye_mask)
            stages[key] = np.asarray(img)
        return stages[key]

    def day_frame(day_no, seat):
        """The speaking shot with the sidebar (cached)."""
        if (day_no, seat) not in frames:
            img = Image.fromarray(stage(seat, f"Day {day_no}").copy())
            d = ImageDraw.Draw(img)
            draw_sidebar(d, "left", game["roles"], notes, revealed)
            draw_sidebar(d, "right", game["roles"], notes, revealed)
            frames[(day_no, seat)] = np.asarray(img)
        return frames[(day_no, seat)]

    def night_seat(s):
        return int((s - HOLD) // SPEECH) % 12 + 1

    def night_stage(s):
        """The night starting at s: its player in an eye mask, no sidebar."""
        return stage(night_seat(s), eye_mask=True)

    def night_base(s):
        if s not in night_bases:
            night_bases[s] = tint_night(night_stage(s))
        return night_bases[s]

    def speaker(t):
        """Who has the floor: the next player every SPEECH seconds, and one
        player through each night and HOLD seconds either side of it."""
        for s, e in nights:
            if s - HOLD <= t < e + HOLD:
                return night_seat(s)
        return int(t // SPEECH) % 12 + 1

    closeup = closeup_frame()
    studio = game.get("studio")
    tour = game.get("tour")
    studio_img = studio_frame() if studio else None
    seat_imgs = [seat_closeup(n) for n in range(1, 13)] if tour else None

    def blend(day_frame, night_frame, k):
        """k=0 full day (sidebar on, white light) .. k=1 full night (sidebar gone, red light)."""
        mix = (day_frame.astype(np.float32) * (1 - k) + night_frame.astype(np.float32) * k).astype(np.uint8)
        return tint_night(mix, k)

    vid_dir = os.path.join(out_dir, game["id"])
    os.makedirs(vid_dir, exist_ok=True)
    out = os.path.join(vid_dir, "video.mp4")
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
                           "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out], stdin=subprocess.PIPE)
    total = game["dur"] * FPS
    for n in range(total):
        t = n / FPS
        night = next(((s, e) for s, e in nights if s <= t < e), None)
        day_no = 1 + sum(1 for s, e in nights if t >= e)
        fading = next(((s, e) for s, e in nights if s <= t < s + FADE or e <= t < e + FADE), None)
        if studio and studio[0] <= t < studio[1]:
            img = Image.fromarray(studio_img)
        elif tour and tour[0] <= t < tour[1]:
            img = Image.fromarray(tour_frame(seat_imgs, t, *tour))
        elif fading and fading[0] == nights[0][0] and t < fading[0] + FADE and tour:
            # the tour cuts straight to the night shot as the first night falls
            img = Image.fromarray(tint_night(night_stage(fading[0]), (t - fading[0]) / FADE))
            banner_night(img)
        elif fading and not any(s <= t < e for s, e in closeups):
            s, e = fading
            k = (t - s) / FADE if t < s + FADE else 1 - (t - e) / FADE
            img = Image.fromarray(blend(day_frame(day_no, speaker(t)), night_stage(s), k))
            if t < s + 5 and t >= s:
                banner_night(img)
            if e <= t < e + 5:
                banner_dawn(img)
        elif night:
            if any(s <= t < e for s, e in closeups):
                frame = closeup
            else:
                frame = night_base(night[0])
            img = Image.fromarray(frame.copy())
            if t < night[0] + 5:
                banner_night(img)
        else:
            img = Image.fromarray(day_frame(day_no, speaker(t)).copy())
            d = ImageDraw.Draw(img)
            d.text((W * 0.70, H * 0.045), f"{int(t) // 60:02d}:{int(t) % 60:02d}", fill=(200, 196, 190), font=font(26), anchor="mm")
            dawn = next((e for s, e in nights if e <= t < e + 5), None)
            if dawn is not None:
                banner_dawn(img)
            if t < 4 and nights and nights[0][0] - 4 <= t:
                banner_night(img)
            elif any(s - 4 <= t < s for s, e in nights):
                banner_night(img)
        ff.stdin.write(np.asarray(img).tobytes())
    ff.stdin.close()
    ff.wait()
    with open(os.path.join(vid_dir, "info.json"), "w", encoding="utf-8") as f:
        json.dump({"title": game["title"], "video_id": game["id"]}, f, ensure_ascii=False, indent=2)
    print(f"{game['id']}: {out} ({game['dur']}s)")


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "library")
    os.makedirs(out_dir, exist_ok=True)
    for game in GAMES:
        render(game, out_dir)
    with open(os.path.join(out_dir, "catalogue.json"), "w", encoding="utf-8") as f:
        json.dump([{"id": g["id"], "title": g["title"], "duration": g["dur"]} for g in GAMES], f, ensure_ascii=False, indent=2)
    print("catalogue written")


if __name__ == "__main__":
    main()
