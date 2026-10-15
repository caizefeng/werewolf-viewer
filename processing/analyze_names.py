#!/usr/bin/env python3
"""Detect character role name regions using PaddleOCR."""

import argparse
import json
import os

# Must be set before importing paddleocr: skips PaddleX's model-source
# network check (faster init, works offline)
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

import re
from collections import Counter

import cv2
import numpy as np
from paddleocr import PaddleOCR

# Local model directory (self-contained, no global cache dependency)
_MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")

# OCR models. PP-OCRv6 medium (paddleocr >= 3.7.0) replaced PP-OCRv5 server
# in 2026-10: on 72 verified vertical role labels + 18 未知 labels it scored
# 69/72 (v5 server 68/72, v5 mobile 59/72) with zero false roles, and it is
# the smaller/faster model. Apple Vision was also tried and cannot read the
# vertical labels at all (0/72).
OCR_DET_MODEL = "PP-OCRv6_medium_det"
OCR_REC_MODEL = "PP-OCRv6_medium_rec"

ROLE_NAMES = [
    "狼人", "狼王", "白狼王", "预言家", "女巫", "猎人",
    "白痴", "守卫", "村民", "平民", "通灵师", "丘比特",
    "盗贼", "长老", "骑士", "野孩子", "石像鬼", "混血儿",
    "假面", "盗宝大师", "机械狼", "黑狼王", "狼术师",
    "典狱长", "狼美人", "黑夜使者", "定序王子", "魔术师",
    "舞者", "毒师", "白神", "蒙面人", "摄梦人", "白夜使者",
    "杠精",
]
ROLE_SET = set(ROLE_NAMES)

# Standard 12-player sidebar layout: seats 1-6 top-to-bottom on the left,
# 7-12 on the right, at a fixed row pitch. Used to infer a row's seat number
# from its vertical position whenever its number badge wasn't OCR'd.
SEAT_BASE = {"left": 1, "right": 7}
SEAT_ROW_SPACING = 0.16   # fallback row pitch (fraction of frame height)
SEAT_FIRST_ROW_Y = 0.125  # fallback center of the first row

# Label the broadcast shows instead of a role in "hidden-roles" games: the
# show itself keeps roles as 未知 and reveals some as the game goes (deaths,
# claims), so the audience is already blind
UNKNOWN_LABEL = "未知"


def sample_frames(video_path, start_sec=60, end_sec=300, interval=1):
    """Yield (sec, frame) tuples from video at given interval.

    Uses sequential grab/read from the start position instead of seeking
    to each frame individually. A frame-index cursor keeps samples
    frame-accurate for fractional frame rates. Generator stops reading
    when the consumer breaks out of the loop.
    """
    cap = cv2.VideoCapture(video_path)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps
        end_sec = min(end_sec, duration)

        # Seek to first sample position; pos = frame index of the next read
        pos = int(round(start_sec * fps))
        if pos > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, pos)

        for sec in range(int(start_sec), int(end_sec), interval):
            target = int(round(sec * fps))
            while pos < target and cap.grab():
                pos += 1
            ret, frame = cap.read()
            if not ret:
                break
            pos += 1
            yield (sec, frame)
    finally:
        cap.release()


def ocr_items_in_frame(ocr, frame, edge_ratio=0.30, min_score=0.5):
    """OCR the left and right edge strips, return every text box found.

    Both crops go through one predict() call. edge_ratio=0.30 keeps the
    center stage out while capturing the director's note column, which sits
    just inward of the role names. Coordinates are normalized to the full
    frame. Boxes exceeding the crop width (PaddleOCR can inflate coords on
    narrow crops) are dropped.
    """
    h, w = frame.shape[:2]
    x_right = int(w * (1 - edge_ratio))
    crops = [
        ("left", 0, frame[:, :int(w * edge_ratio)]),
        ("right", x_right, frame[:, x_right:]),
    ]
    results = ocr.predict([c[2] for c in crops])
    items = []
    for (side, x_offset, crop), result in zip(crops, results):
        crop_w = crop.shape[1]
        texts = result.get("rec_texts", [])
        scores = result.get("rec_scores", [])
        polys = result.get("dt_polys", [])
        for text, score, poly in zip(texts, scores, polys):
            if score < min_score:
                continue
            poly = np.array(poly)
            x1, y1 = poly.min(axis=0)
            x2, y2 = poly.max(axis=0)
            if x2 > crop_w:
                continue
            items.append({
                "side": side, "text": text.strip(), "score": float(score),
                "x0": round((x_offset + x1) / w, 4),
                "x1": round((x_offset + x2) / w, 4),
                "y0": round(y1 / h, 4), "y1": round(y2 / h, 4),
            })
    return items


def _roles_from_items(items):
    """Exact role-name boxes from raw OCR items (exact match: notes and the
    watermark contain role words too)."""
    regions = []
    for it in items:
        if it["text"] in ROLE_SET:
            regions.append({
                "x": it["x0"], "y": it["y0"],
                "w": round(it["x1"] - it["x0"], 4),
                "h": round(it["y1"] - it["y0"], 4),
                "text": it["text"], "side": it["side"],
            })
    return regions


def _levenshtein(a, b):
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _snap_role(text):
    """Map an OCR'd role-column label to the role it most likely is.

    OCR of the vertical labels occasionally drops or adds a character
    ("械狼" for 机械狼, "狼人学" for 狼人, "自神" for 白神). Containment in
    either direction wins, then edit distance 1; anything further apart
    (including 未知) stays unmatched.
    """
    if text in ROLE_SET:
        return text
    if len(text) < 2:
        return None
    best = None
    for role in ROLE_NAMES:
        if role in text or text in role:
            cand = (0, abs(len(role) - len(text)), role)
        elif _levenshtein(text, role) <= 1:
            cand = (1, 1, role)
        else:
            continue
        if best is None or cand < best:
            best = cand
    return best[2] if best else None


def _recover_misread_roles(all_regions, all_items):
    """Add role boxes for role-column labels the OCR misread.

    The role column's x-range is known from the exact matches. Any short CJK
    box centered in that column that isn't an exact role is a misread role
    label (notes sit inward of the column, numbers outward), so snap it to
    the nearest role name. Without this a misread row vanishes from the
    role map and can't be revealed.
    """
    recovered = list(all_regions)
    for side in ("left", "right"):
        regs = [r for r in all_regions if r["side"] == side]
        if not regs:
            continue
        rx0 = float(np.percentile([r["x"] for r in regs], 10))
        rx1 = float(np.percentile([r["x"] + r["w"] for r in regs], 90))
        cx = (rx0 + rx1) / 2
        col_w = max(rx1 - rx0, 0.01)
        for it in all_items:
            t = it["text"]
            if it["side"] != side or t in ROLE_SET:
                continue
            if not (2 <= len(t) <= 5) or not re.search(r"[\u4e00-\u9fff]", t):
                continue
            xc = (it["x0"] + it["x1"]) / 2
            if abs(xc - cx) > col_w * 0.6 or (it["x1"] - it["x0"]) > col_w * 1.6:
                continue
            role = _snap_role(t)
            if role is None:
                continue
            recovered.append({"x": it["x0"], "y": it["y0"],
                              "w": round(it["x1"] - it["x0"], 4),
                              "h": round(it["y1"] - it["y0"], 4),
                              "text": role, "side": side})
    return recovered


def detect_names_in_frame(ocr, frame, edge_ratio=0.30):
    """Run OCR on the frame edges, return role-name bounding boxes."""
    return _roles_from_items(ocr_items_in_frame(ocr, frame, edge_ratio=edge_ratio))


def analyze_name_regions_with_ocr(ocr, video_path):
    """Run name detection with a pre-initialized OCR instance.

    Returns (masks, unique_texts) tuple (role map omitted).
    """
    masks, _role_map, texts, _hidden_roles = _analyze(ocr, video_path)
    return masks, texts


def probe_sidebar(ocr, video_path, fractions=(0.15, 0.25, 0.35, 0.5, 0.65, 0.8, 0.9)):
    """OCR the sidebar at a few points spread over the whole video.

    Returns [{t, unknown, roles}] per probe. Used (a) to detect hidden-roles
    broadcasts robustly -- the sidebar can be absent for minutes (intermission
    screens) or show a transient placeholder, so one scan window is not
    enough -- and (b) to pick the role-scan window: the first probe that
    shows role labels tells where the game is on screen.
    """
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
    probes = []
    for fr in fractions:
        t = int(dur * fr)
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * fps)))
        ok, frame = cap.read()
        if not ok:
            continue
        items = ocr_items_in_frame(ocr, frame)
        probes.append({
            "t": t,
            "unknown": sum(1 for it in items if it["text"] == UNKNOWN_LABEL),
            "roles": len(_roles_from_items(items)),
        })
    cap.release()
    return probes


def _scan_range(ocr, video_path, start_sec, end_sec, interval, min_named_frames=8):
    """Scan a range. Returns (regions, items, num_sampled, unknown_frames).

    Accumulates raw OCR items (for the role map) from frames containing role
    names, stopping after min_named_frames such frames. unknown_frames counts
    frames showing two or more 未知 labels (hidden-roles games); once three
    such frames are seen with no role names at all, the scan stops early.
    """
    all_regions = []
    all_items = []
    found_any = False
    named = 0
    num_sampled = 0
    unknown_frames = 0
    gen = sample_frames(video_path, start_sec=start_sec, end_sec=end_sec,
                        interval=interval)
    try:
        for sec, frame in gen:
            num_sampled += 1
            items = ocr_items_in_frame(ocr, frame)
            if sum(1 for it in items if it["text"] == UNKNOWN_LABEL) >= 2:
                unknown_frames += 1
            regions = _roles_from_items(items)
            if regions:
                if not found_any:
                    print(f"  First names detected at {sec}s")
                    found_any = True
                all_regions.extend(regions)
                all_items.extend(items)
                named += 1
                if named >= min_named_frames:
                    print(f"  Collected {named} named frames by {sec}s")
                    break
            elif unknown_frames >= 3 and named == 0:
                print(f"  Hidden-roles labels in {unknown_frames} frames, no roles — stopping scan at {sec}s")
                break
    finally:
        gen.close()
    return all_regions, all_items, num_sampled, unknown_frames


def _cluster_rows(regs, tol=0.05):
    """Group role boxes into player rows by vertical position (majority role
    per row tolerates per-frame OCR noise)."""
    pts = sorted((r["y"] + r["h"] / 2, r["text"]) for r in regs)
    clusters = []
    for yc, role in pts:
        if clusters and yc - clusters[-1]["last"] <= tol:
            c = clusters[-1]
            c["ys"].append(yc); c["roles"].append(role); c["last"] = yc
        else:
            clusters.append({"ys": [yc], "roles": [role], "last": yc})
    return [{"role": Counter(c["roles"]).most_common(1)[0][0],
             "yc": float(np.median(c["ys"])), "count": len(c["ys"])}
            for c in clusters]


def _bands_from_centers(cs):
    """Vertical reveal band for each row: midpoints to the adjacent rows."""
    n = len(cs)
    bands = []
    for i, c in enumerate(cs):
        up = (cs[i - 1] + c) / 2 if i > 0 else (c - (cs[i + 1] - c) / 2 if n > 1 else c - 0.08)
        dn = (cs[i + 1] + c) / 2 if i < n - 1 else (c + (c - cs[i - 1]) / 2 if n > 1 else c + 0.08)
        bands.append((max(0.0, up), min(1.0, dn)))
    return bands


def _infer_seats(rows, ocr_nums, side):
    """Seat number for every row from vertical position, anchored on the
    badges OCR did read.

    Seats run top-to-bottom (1-6 left, 7-12 right) at a fixed pitch, so for
    any anchored row the seat of row i is anchor_seat + round(dy / pitch).
    Every anchored row votes for every row; the majority wins. With no
    anchor on a side, fall back to the standard layout geometry.
    """
    n = len(rows)
    ys = [r["yc"] for r in rows]
    diffs = [b - a for a, b in zip(ys, ys[1:]) if b - a > 0.05]
    pitch = float(np.median(diffs)) if diffs else SEAT_ROW_SPACING
    anchors = [(ys[i], Counter(v).most_common(1)[0][0])
               for i, v in enumerate(ocr_nums) if v]

    def positional():
        seats = [SEAT_BASE[side] + int(round((y - SEAT_FIRST_ROW_Y) / pitch)) for y in ys]
        return seats if len(set(seats)) == n else [SEAT_BASE[side] + i for i in range(n)]

    if not anchors:
        return positional()
    seats = []
    for i in range(n):
        votes = Counter(a_seat + int(round((ys[i] - a_y) / pitch)) for a_y, a_seat in anchors)
        seats.append(votes.most_common(1)[0][0])
    if len(set(seats)) != n or min(seats) < 1 or max(seats) > 20:
        return positional()
    return seats


def build_role_map(all_items, all_regions):
    """Map each player row to its seat number, role, and reveal y-band.

    Used by the viewer's role-reveal panel. Only the seat ID identifies a
    player: names are not extracted (OCR of the stylized name tags was
    unreliable). The role string is only a menu label — the viewer reveals
    the real pixels — so OCR noise in it is harmless.
    """
    role_map = {}
    for side in ("left", "right"):
        regs = [r for r in all_regions if r["side"] == side]
        if not regs:
            continue
        rows = _cluster_rows(regs)
        if not rows:
            continue
        rows.sort(key=lambda r: r["yc"])
        bands = _bands_from_centers([r["yc"] for r in rows])
        sit = [it for it in all_items if it["side"] == side]
        rx0 = float(np.percentile([r["x"] for r in regs], 10))
        rx1 = float(np.percentile([r["x"] + r["w"] for r in regs], 90))

        # Seat badges OCR'd per row: 1-2 digit numbers outward of the role column
        nums = [[] for _ in rows]
        for it in sit:
            t = it["text"]
            if not re.fullmatch(r"\d{1,2}", t):
                continue
            v = int(t)
            if not 1 <= v <= 20:
                continue
            xc = (it["x0"] + it["x1"]) / 2
            outward = xc < rx0 if side == "left" else xc > rx1
            if not outward:
                continue
            yc = (it["y0"] + it["y1"]) / 2
            bi = next((i for i, (a, b) in enumerate(bands) if a <= yc < b), None)
            if bi is not None:
                nums[bi].append(v)
        seats = _infer_seats(rows, nums, side)

        players = []
        for i, row in enumerate(rows):
            y0, y1 = bands[i]
            players.append({"number": seats[i], "role": row["role"],
                            "y0": round(y0, 4), "y1": round(y1, 4)})
        players.sort(key=lambda p: p["number"])
        role_map[side] = players
    return role_map


# Fraction of frame width the mask extends inward past the role column, to
# cover the director's running description/opinion next to each role
# ("验9查杀", "觉得1不是狼"…) — those give the role away as much as the name.
# Fixed (not measured): the note column is a fixed-width UI element, and
# measuring it tripped over centered banners (title, config line, ticker).
NOTE_EXTEND = 0.12


def build_masks(all_regions):
    """Mask each side's role column plus the adjacent note column.

    Outer edge = role column edge (10th/90th percentile, so a stray box can't
    widen it); inner edge = role edge + NOTE_EXTEND toward center, clamped so
    the mask can never reach the central stage.
    """
    masks = []
    pad = 0.015
    for side in ("left", "right"):
        regs = [r for r in all_regions if r["side"] == side]
        if not regs:
            continue
        rx0 = float(np.percentile([r["x"] for r in regs], 10))
        rx1 = float(np.percentile([r["x"] + r["w"] for r in regs], 90))
        if side == "left":
            x_min = max(0.0, rx0 - pad)
            x_max = min(0.32, rx1 + NOTE_EXTEND)
        else:
            x_min = max(0.68, rx0 - NOTE_EXTEND)
            x_max = min(1.0, rx1 + pad)
        masks.append({"x": round(x_min, 4), "y": 0,
                      "w": round(x_max - x_min, 4), "h": 1.0})
    return masks


def _analyze(ocr, video_path):
    """Core analysis logic shared by public entry points.

    Returns (masks, role_map, unique_texts, hidden_roles).

    Scans 1100s-1400s first. If both sides aren't found, extends the scan
    to 1400s-2000s with a coarser interval to find late-appearing names.
    """
    DEFAULT_MASKS = [
        {"x": 0.05, "y": 0, "w": 0.10, "h": 1.0},
        {"x": 0.85, "y": 0, "w": 0.10, "h": 1.0},
    ]

    # Hidden-roles broadcast? Decide from probes spread over the whole video,
    # not from one window: the sidebar can be absent for minutes and the
    # non-revealed seats can briefly show a placeholder before 未知.
    probes = probe_sidebar(ocr, video_path)
    print("  Sidebar probes: " + ", ".join(
        f"{p['t']}s {p['roles']} roles/{p['unknown']} unknown" for p in probes))
    unknown_probes = sum(1 for p in probes if p["unknown"] >= 2)
    if unknown_probes >= 2:
        print(f"  Hidden-roles broadcast detected ({UNKNOWN_LABEL} in {unknown_probes} probes); "
              "masks and role map are not applicable")
        return DEFAULT_MASKS, {}, set(), True

    # Role-scan window: start a minute before the first probe that shows
    # role labels (games don't all reach the sidebar by the same time)
    first = next((p["t"] for p in probes if p["roles"] >= 4), None)
    scan_start = max(0, first - 60) if first is not None else 1100
    scan_end = scan_start + 300
    print(f"Sampling frames ({scan_start}s-{scan_end}s at 10s intervals)...")
    all_regions, all_items, num_sampled, unknown_frames = _scan_range(
        ocr, video_path, scan_start, scan_end, interval=10)
    print(f"Processed {num_sampled} frames")

    sides_found = set(r["side"] for r in all_regions)
    missing_sides = {"left", "right"} - sides_found
    ext_start, ext_end = scan_end, scan_end + 600

    if missing_sides and all_regions:
        print(f"  Missing {', '.join(missing_sides)} side. "
              f"Extending scan ({ext_start}s-{ext_end}s at 30s intervals)...")
        er, ei, es, eu = _scan_range(
            ocr, video_path, ext_start, ext_end, interval=30, min_named_frames=4)
        num_sampled += es
        unknown_frames += eu
        all_regions.extend(r for r in er if r["side"] in missing_sides)
        all_items.extend(it for it in ei if it["side"] in missing_sides)
        print(f"  Extended scan: {es} more frames")

    if not all_regions:
        print("  No names in primary range. Trying extended scan "
              f"({ext_start}s-{ext_end}s at 30s intervals)...")
        all_regions, all_items, es, eu = _scan_range(
            ocr, video_path, ext_start, ext_end, interval=30, min_named_frames=4)
        num_sampled += es
        unknown_frames += eu
        print(f"  Extended scan: {es} frames")

    # Secondary check from the scans themselves
    if unknown_frames >= 2:
        print(f"  Hidden-roles broadcast detected ({UNKNOWN_LABEL} in {unknown_frames} scanned frames)")
        return DEFAULT_MASKS, {}, set(), True

    if not all_regions:
        print("No role names detected. Using default mask positions.")
        return DEFAULT_MASKS, {}, set(), False

    # Recover rows whose role label the OCR misread (械狼, 狼人学, 自神)
    before = len(all_regions)
    all_regions = _recover_misread_roles(all_regions, all_items)
    if len(all_regions) > before:
        print(f"  Recovered {len(all_regions) - before} misread role label(s)")

    unique_texts = set(r["text"] for r in all_regions)
    print(f"Detected texts: {', '.join(sorted(unique_texts))}")

    masks = build_masks(all_regions)
    role_map = build_role_map(all_items, all_regions)
    print(f"Merged into {len(masks)} mask region(s)")
    for m in masks:
        print(f"  x={m['x']:.3f} y={m['y']:.3f} w={m['w']:.3f} h={m['h']:.3f}")
    for sd, players in role_map.items():
        print(f"  role_map[{sd}]: " + ", ".join(
            f"{p['number']}={p['role']}" for p in players))
    return masks, role_map, unique_texts, False


def sidebar_visible(ocr, frame):
    """True if the player sidebar (role / 未知 labels) is on screen.

    The sidebar is shown throughout the day and never during a night (nights
    cut between the red-lit table, the night graphic and masked close-ups),
    so a sidebar sighting is the day evidence used to decide whether two red
    bursts belong to the same night. Only the narrow role-column strips are
    OCR'd, so this is cheap.
    """
    h, w = frame.shape[:2]
    strips = [frame[:, int(0.06 * w):int(0.18 * w)], frame[:, int(0.82 * w):int(0.94 * w)]]
    n = 0
    for r in ocr.predict(strips):
        for text, score in zip(r.get("rec_texts", []), r.get("rec_scores", [])):
            t = text.strip()
            if score >= 0.5 and (t == UNKNOWN_LABEL or _snap_role(t) is not None):
                n += 1
    return n >= 3


def day_evidence_in(ocr, cap, fps, t0, t1, step=10.0):
    """Any sidebar sighting in (t0, t1)? Samples every `step` seconds."""
    t = t0 + step / 2
    while t < t1:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * fps)))
        ok, frame = cap.read()
        if ok and sidebar_visible(ocr, frame):
            return True
        t += step
    return False


def _ensure_models():
    """Local copies of the OCR models, downloaded through PaddleOCR's hub
    resolution on first use and copied into processing/models/ so the
    pipeline has no dependency on the global cache afterwards.

    Returns (det_dir, rec_dir), or (None, None) if the local copy failed
    (then the models are used straight from PaddleOCR's cache).
    """
    dirs = {n: os.path.join(_MODELS_DIR, n) for n in (OCR_DET_MODEL, OCR_REC_MODEL)}

    def ok(d):
        return os.path.isdir(d) and os.path.exists(os.path.join(d, "inference.pdiparams"))

    if all(ok(d) for d in dirs.values()):
        return dirs[OCR_DET_MODEL], dirs[OCR_REC_MODEL]

    print(f"  OCR models {OCR_DET_MODEL} / {OCR_REC_MODEL} not found locally. Downloading...")
    os.makedirs(_MODELS_DIR, exist_ok=True)
    import shutil
    tmp_ocr = PaddleOCR(
        lang="ch",
        text_detection_model_name=OCR_DET_MODEL,
        text_recognition_model_name=OCR_REC_MODEL,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    del tmp_ocr

    cache_base = os.path.expanduser("~/.paddlex/official_models")
    for name, dst in dirs.items():
        src = os.path.join(cache_base, name)
        if ok(src):
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            print(f"  Copied {name} to local models/")
    if not all(ok(d) for d in dirs.values()):
        print("  Could not copy the models locally; using PaddleOCR's cache directly")
        return None, None
    return dirs[OCR_DET_MODEL], dirs[OCR_REC_MODEL]


def _init_ocr():
    """Initialize PaddleOCR with the local models and the best device."""
    det_dir, rec_dir = _ensure_models()

    # CUDA only; PaddlePaddle has no Apple MPS support
    device = "cpu"
    try:
        import paddle
        if paddle.device.is_compiled_with_cuda():
            device = "gpu:0"
            print("  Using GPU (CUDA)")
    except Exception:
        pass
    if device == "cpu":
        print("  Using CPU")

    kw = dict(use_doc_orientation_classify=False, use_doc_unwarping=False,
              use_textline_orientation=False, device=device)
    if det_dir and rec_dir:
        return PaddleOCR(text_detection_model_dir=det_dir,
                         text_recognition_model_dir=rec_dir, **kw)
    return PaddleOCR(text_detection_model_name=OCR_DET_MODEL,
                     text_recognition_model_name=OCR_REC_MODEL, **kw)


def analyze_name_regions(video_path):
    """Main entry point: masks only (backward-compatible)."""
    return analyze_name_regions_full(video_path)["name_masks"]


def analyze_name_regions_full(video_path):
    """Full name-detection result: {name_masks, role_map, hidden_roles}."""
    print("Initializing PaddleOCR...")
    ocr = _init_ocr()
    masks, role_map, _texts, hidden_roles = _analyze(ocr, video_path)
    return {"name_masks": masks, "role_map": role_map, "hidden_roles": hidden_roles}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Detect character name regions")
    parser.add_argument("video_path", help="Path to video file")
    args = parser.parse_args()

    result = analyze_name_regions_full(args.video_path)
    print(json.dumps(result, indent=2, ensure_ascii=False))
