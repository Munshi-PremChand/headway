#!/usr/bin/env python3
"""Render a photocopy-like timetable with a KNOWN ground truth.

This exists so reader accuracy can be MEASURED rather than asserted. The
ground truth is written alongside the image, so a run's output can be scored
cell by cell without a human in the loop.

Honest limitation, and it must be stated wherever this fixture's numbers are
quoted: a rendered image is EASIER than a real photocopy of a real Indian
timetable. Degradations here (skew, blur, speckle, a smudged cell) approximate
photocopy damage; they do not reproduce it. Numbers from this fixture
calibrate a choice between settings — they are not a claim about field
accuracy.

    python3 scripts/make_fixture_timetable.py fixtures/scans/
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1240, 900
MARGIN = 60

# The ground truth. Deliberately includes the hard cases the reader must
# handle: a midnight crossing, an em-dash "no service" cell, a footnote
# dagger, and one cell that will be visually smudged.
STOPS = ["Kempegowda Bus Stn", "Majestic Metro", "City Hospital",
         "Dialysis Centre", "Depot (no boarding)"]
TRIPS = [
    {"trip": "T1", "times": ["06:15", "06:28", "06:47", "07:05", "07:20"]},
    {"trip": "T2", "times": ["09:40", "09:53", "10:12", "10:37", "10:45"]},
    {"trip": "T3", "times": ["14:05", "14:18", "—", "14:55", "15:10"]},
    {"trip": "T4", "times": ["23:30", "23:43", "00:02", "00:20", "00:35"]},
]
# The smudged cell is DELIBERATELY OFF-PATTERN. Its neighbours (10:12, 10:45)
# imply ~10:30, but the truth is 10:37. A model that interpolates rather than
# reads is therefore detectably WRONG, not luckily right. Without this the
# confident-wrong metric saturates at zero and cannot discriminate between
# thinking levels at all — which is exactly what happened on the first fixture.
SMUDGE_CELL = (1, 3)   # trip index 1, stop index 3 -> the 10:37 at Dialysis


def _font(size: int, bold: bool = False):
    for name in (["/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
                  "/System/Library/Fonts/Supplemental/Arial Bold.ttf"] if bold else
                 ["/System/Library/Fonts/Supplemental/Courier New.ttf",
                  "/System/Library/Fonts/Supplemental/Arial.ttf"]):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def render(out_dir: Path, seed: int = 7) -> tuple[Path, Path]:
    random.seed(seed)
    img = Image.new("L", (W, H), 246)
    d = ImageDraw.Draw(img)

    f_title, f_head, f_cell, f_note = (_font(38, True), _font(24, True),
                                       _font(26), _font(18))

    d.text((MARGIN, 40), "CITY BUS SERVICE  —  ROUTE 12A", font=f_title, fill=25)
    d.text((MARGIN, 92), "Kempegowda Bus Station → Dialysis Centre",
           font=f_head, fill=45)
    d.line([(MARGIN, 130), (W - MARGIN, 130)], fill=60, width=2)

    col_x = [MARGIN, 470, 620, 770, 920, 1070]
    y_head = 160
    d.text((col_x[0], y_head), "STOP", font=f_head, fill=25)
    for i, t in enumerate(TRIPS):
        d.text((col_x[i + 1], y_head), t["trip"], font=f_head, fill=25)
    d.line([(MARGIN, y_head + 34), (W - MARGIN, y_head + 34)], fill=90, width=1)

    truth: list[dict] = []
    y = y_head + 58
    for si, stop in enumerate(STOPS):
        label = stop + (" †" if si == 4 else "")
        d.text((col_x[0], y), label, font=f_cell, fill=30)
        for ti, trip in enumerate(TRIPS):
            val = trip["times"][si]
            x = col_x[ti + 1]
            d.text((x, y), val, font=f_cell, fill=30)
            truth.append({
                "trip": trip["trip"], "stop": stop, "seq": si + 1, "value": val,
                "bbox": [x / W, y / H, (x + 90) / W, (y + 32) / H],
                "boardable": si != 4,
                "is_smudged": (ti, si) == SMUDGE_CELL,
                "no_service": val == "—",
            })
        y += 62

    d.text((MARGIN, y + 24),
           "† Depot — alighting only, no boarding at this point.",
           font=f_note, fill=70)
    d.text((MARGIN, y + 52),
           "Times after midnight shown as 00:xx. Sundays: no service.",
           font=f_note, fill=70)

    # --- photocopy-like degradation ------------------------------------
    ti, si = SMUDGE_CELL
    sx, sy = col_x[ti + 1], y_head + 58 + si * 62
    box = (sx - 4, sy - 4, sx + 92, sy + 36)
    # MEASURED 2026-08-27: a GaussianBlur(2.1) + speckle "smudge" is STILL
    # fully legible to gemini-3.7-flash. It read 10:37 correctly on 8 of 9
    # runs. The proof it was reading rather than interpolating: when the truth
    # was changed from 10:30 to 10:37 the model's answer changed with it.
    # Testing abstention therefore requires a cell that is genuinely
    # destroyed, not merely degraded.
    patch = img.crop(box).filter(ImageFilter.GaussianBlur(9.0))
    img.paste(patch, box)
    pd = ImageDraw.Draw(img)
    for _ in range(1400):                    # heavy toner damage
        px, py = random.randint(box[0], box[2]), random.randint(box[1], box[3])
        pd.point((px, py), fill=random.randint(40, 235))
    # a coffee-ring style blot across the cell, as on a real counter copy
    pd.ellipse((box[0] + 6, box[1] + 2, box[2] - 6, box[3] - 2),
               outline=120, width=3)

    img = img.rotate(-0.7, resample=Image.BICUBIC, fillcolor=246)  # scanner skew
    img = img.filter(ImageFilter.GaussianBlur(0.45))               # soft copy
    px = img.load()
    for _ in range(5200):                                          # page noise
        x, y2 = random.randint(0, W - 1), random.randint(0, H - 1)
        px[x, y2] = max(0, min(255, px[x, y2] + random.randint(-46, 26)))

    out_dir.mkdir(parents=True, exist_ok=True)
    img_path = out_dir / "route12a_timetable.png"
    truth_path = out_dir / "route12a_truth.json"
    img.convert("RGB").save(img_path, "PNG")
    truth_path.write_text(json.dumps({
        "note": "Ground truth for a RENDERED timetable. Easier than a real "
                "photocopy; use for setting-vs-setting comparison only.",
        "smudged_cell": {"trip": TRIPS[ti]["trip"], "stop": STOPS[si],
                         "true_value": TRIPS[ti]["times"][si]},
        "cells": truth,
    }, indent=2))
    return img_path, truth_path


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "fixtures/scans")
    i, t = render(out)
    data = json.loads(t.read_text())
    print(f"image : {i}  ({i.stat().st_size:,} bytes)")
    print(f"truth : {t}  ({len(data['cells'])} cells)")
    print(f"smudged cell (true value hidden from the model): "
          f"{data['smudged_cell']['trip']} @ {data['smudged_cell']['stop']} "
          f"= {data['smudged_cell']['true_value']}")
