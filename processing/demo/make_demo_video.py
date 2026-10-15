#!/usr/bin/env python3
"""Render synthetic 12-player werewolf broadcasts for demos and screenshots.

Nothing here comes from a real stream: the stage, the player cards, the
role ribbons, the night tint and the phase banners are all drawn, with
made-up players. The layout follows what the analysis expects (role
ribbons at x~0.10 / x~0.89, rows pitched 0.16 from y=0.125, number badges
outward of the ribbons, sidebar hidden at night, "天黑请闭眼" / "天亮请睁眼"
banners), so the real pipeline can analyse these clips end to end.

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
    {"id": "demoS01E01g1", "title": "Demo Cup S01E01 第一局 预女猎守 260101 werewolf", "dur": 360,
     "roles": ["狼人", "预言家", "平民", "守卫", "猎人", "狼人", "平民", "狼人", "女巫", "平民", "平民", "狼人"],
     "nights": [(30, 100), (220, 270)], "closeups": [(55, 75)],
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


def draw_stage(d, day_no):
    d.rectangle([0, 0, W, H], fill=(34, 32, 40))
    d.rectangle([0, int(H * 0.62), W, H], fill=(58, 54, 62))          # floor
    d.ellipse([W * 0.30, H * 0.40, W * 0.70, H * 0.88], fill=(84, 70, 60), outline=(120, 104, 90), width=6)
    d.ellipse([W * 0.36, H * 0.47, W * 0.64, H * 0.81], fill=(110, 92, 78))
    for i in range(12):                                                 # chairs around the table
        a = 2 * np.pi * i / 12
        cx, cy = W * 0.50 + np.cos(a) * W * 0.23, H * 0.64 + np.sin(a) * H * 0.29
        d.ellipse([cx - 26, cy - 26, cx + 26, cy + 26], fill=(70, 66, 80), outline=(140, 134, 150), width=3)
        d.text((cx, cy), str(i + 1), fill=(220, 215, 205), font=font(22), anchor="mm")
    d.rounded_rectangle([W * 0.40, H * 0.015, W * 0.60, H * 0.075], radius=14, fill=(52, 48, 70), outline=(150, 140, 180), width=2)
    d.text((W * 0.50, H * 0.045), "DEMO CUP · 演示赛", fill=(235, 230, 220), font=font(30), anchor="mm")
    d.text((W * 0.30, H * 0.045), f"Day {day_no}", fill=(200, 196, 190), font=font(26), anchor="mm")
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
    for cx in (W * 0.3, W * 0.7):
        d.ellipse([cx - 190, H * 0.5 - 190, cx + 190, H * 0.5 + 190], fill=(246, 236, 226), outline=(120, 60, 50), width=8)
        d.text((cx, H * 0.5), "?", fill=(90, 50, 44), font=font(150), anchor="mm")
    d.rounded_rectangle([W * 0.32, H * 0.84, W * 0.68, H * 0.93], radius=16, fill=(250, 244, 236))
    d.text((W * 0.5, H * 0.885), "夜间讨论 · 画面已遮挡", fill=(80, 40, 36), font=font(40), anchor="mm")
    return np.asarray(img)


def tint_night(frame, k=1.0):
    """Red studio light; k in [0, 1] fades it in (real lights take seconds,
    and the detector treats a one-frame switch as a camera cut)."""
    f = frame.astype(np.float32)
    f[..., 0] = np.clip(f[..., 0] * (1 + 0.25 * k) + 20 * k, 0, 255)
    f[..., 1] *= 1 - 0.68 * k
    f[..., 2] *= 1 - 0.70 * k
    return f.astype(np.uint8)


FADE = 3.0  # seconds the light (and the sidebar) take to change at each night boundary


def render(game, out_dir):
    nights = game["nights"]
    closeups = game.get("closeups", [])
    notes = game.get("notes", {})
    revealed = game.get("revealed", {})
    days = []
    for day_no in (1, 2, 3):
        img = Image.new("RGB", (W, H))
        d = ImageDraw.Draw(img)
        draw_stage(d, day_no)
        draw_sidebar(d, "left", game["roles"], notes, revealed)
        draw_sidebar(d, "right", game["roles"], notes, revealed)
        days.append(np.asarray(img))
    night_img = Image.new("RGB", (W, H))
    draw_stage(ImageDraw.Draw(night_img), 0)
    stage_only = np.asarray(night_img)
    night_base = tint_night(stage_only)
    closeup = closeup_frame()

    def blend(day_frame, k):
        """k=0 full day (sidebar on, white light) .. k=1 full night (sidebar gone, red light)."""
        mix = (day_frame.astype(np.float32) * (1 - k) + stage_only.astype(np.float32) * k).astype(np.uint8)
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
        if fading and not any(s <= t < e for s, e in closeups):
            s, e = fading
            k = (t - s) / FADE if t < s + FADE else 1 - (t - e) / FADE
            img = Image.fromarray(blend(days[min(day_no if t >= e else day_no, 3) - 1], k))
            if t < s + 5 and t >= s:
                banner_night(img)
            if e <= t < e + 5:
                banner_dawn(img)
        elif night:
            if any(s <= t < e for s, e in closeups):
                frame = closeup
            else:
                frame = night_base
            img = Image.fromarray(frame.copy())
            if t < night[0] + 5:
                banner_night(img)
        else:
            img = Image.fromarray(days[min(day_no, 3) - 1].copy())
            d = ImageDraw.Draw(img)
            a = 2 * np.pi * (int(t // 5) % 12) / 12          # speaker ring moves every 5s
            cx, cy = W * 0.50 + np.cos(a) * W * 0.23, H * 0.64 + np.sin(a) * H * 0.29
            d.ellipse([cx - 34, cy - 34, cx + 34, cy + 34], outline=(255, 215, 90), width=5)
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
