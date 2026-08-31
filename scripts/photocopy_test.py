#!/usr/bin/env python3
"""Test the claim the project actually rests on, on the artifact it rests on.

THE CLAIM. HEADWAY exists because most Indian timetables are photocopies, board
notices and phone photographs — artifacts with no text layer, where the naive
`pdftotext` approach scores exactly zero. Every number measured so far was on a
CLEAN RENDER. The claim was therefore untested, and the README said so.

THE TEST. Take the same ASTC page, degrade it the way a real photocopy degrades
— scanner skew, blur, toner speckle, contrast loss and JPEG artifacts — and run
BOTH approaches on it. The baseline gets an image with no text layer, which is
the whole point: it cannot even start. HEADWAY gets pixels, which is all it ever
needed.

THE SCORE. The clean page's embedded text layer is the ground truth. It is never
shown to the reader; it is only used afterwards to check what came back. Cell
fidelity is reported per field, and abstention is reported separately, because a
reader that abstains on a destroyed cell is behaving correctly and must not be
scored as if it had guessed wrong.

    python3 scripts/photocopy_test.py --level 2
    python3 scripts/photocopy_test.py --level 3 --save-image
"""

from __future__ import annotations

import argparse
import io
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from headway.pipeline.credentials import build_client                # noqa: E402
from headway.pipeline.render import render_page                      # noqa: E402
from headway.reader.blocks import (                                  # noqa: E402
    bind_blocks, rebind_claim_ids,
)
from headway.reader.gemini_reader import (                           # noqa: E402
    CLAIM_RESPONSE_SCHEMA, DEFAULT_MODEL, GenAIClient, ILLEGIBLE,
    READER_THINKING_LEVEL, build_system_prompt, parse_claims,
)
from scripts.baseline_textlayer import parse_text_layer              # noqa: E402

ASTC = ("https://st.redbus.in/Images/WL/ASTC/schedules_new/"
        "Guwahati_division.pdf")

# Three degradations, stated up front so the level cannot be tuned after seeing
# the score. Level 2 is "a photocopy of a photocopy"; level 3 is a bad phone
# photograph of one.
LEVELS = {
    1: dict(skew=-0.4, blur=0.8, speckle=9000, contrast=0.88, jpeg=55,
            label="light copy"),
    2: dict(skew=-1.1, blur=1.5, speckle=26000, contrast=0.72, jpeg=32,
            label="photocopy of a photocopy"),
    3: dict(skew=-2.0, blur=2.3, speckle=52000, contrast=0.58, jpeg=20,
            label="phone photo of a bad copy"),
}


def degrade(png: bytes, level: int, seed: int = 11) -> bytes:
    from PIL import Image, ImageEnhance, ImageFilter
    cfg = LEVELS[level]
    rng = random.Random(seed)
    img = Image.open(io.BytesIO(png)).convert("L")

    img = img.rotate(cfg["skew"], resample=Image.BICUBIC, fillcolor=238)
    img = img.filter(ImageFilter.GaussianBlur(cfg["blur"]))
    img = ImageEnhance.Contrast(img).enhance(cfg["contrast"])

    px = img.load()
    w, h = img.size
    for _ in range(cfg["speckle"]):
        x, y = rng.randrange(w), rng.randrange(h)
        px[x, y] = max(0, min(255, px[x, y] + rng.choice((-90, -55, 60, 85))))

    # A copier loses the page edges and lights unevenly toward one side.
    for y in range(h):
        fade = int(14 * (y / h))
        for x in range(0, w, 3):
            px[x, y] = max(0, min(255, px[x, y] - fade))

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=cfg["jpeg"])
    return buf.getvalue()


def truth_from_text_layer(text: str) -> dict:
    """Ground truth: (trip, seq) -> {stop, km, arrival, departure}."""
    cs, _stats = parse_text_layer(text, "ASTC")
    out: dict = {}
    for c in cs.claims:
        t, s = str(c.scope.get("trip")), c.scope.get("seq")
        if s is None:
            continue
        row = out.setdefault((t, int(s)), {})
        if c.kind.value == "stop" and c.field == "stop_name":
            row["stop"] = str(c.value)
        elif c.kind.value == "stop_time":
            row[c.field] = str(c.value)
    return out


def norm(v: str) -> str:
    s = str(v).strip().lower().replace(".", ":")
    s = re.sub(r"\s+", " ", s)
    m = re.match(r"^(\d{1,2}):(\d{2})\s*(am|pm|noon|midnight)?$", s)
    if m:
        h, mi, ap = int(m.group(1)), m.group(2), (m.group(3) or "")
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        if ap == "noon":
            h = 12
        if ap == "midnight":
            h = 0
        return f"{h:02d}:{mi}"
    return s


def read_image(client, image: bytes, mime: str) -> str:
    from google.genai import types
    resp = client.models.generate_content(
        model=DEFAULT_MODEL,
        contents=[types.Part.from_bytes(data=image, mime_type=mime),
                  types.Part.from_text(
                      text="Transcribe every service block on this page into claims.")],
        config=types.GenerateContentConfig(
            system_instruction=build_system_prompt("service_blocks"),
            response_mime_type="application/json",
            response_schema=CLAIM_RESPONSE_SCHEMA,
            max_output_tokens=32768,
            thinking_config=types.ThinkingConfig(
                thinking_level=READER_THINKING_LEVEL)))
    return GenAIClient.answer_text(resp)


def score(raw: str, truth: dict) -> dict:
    cs = parse_claims(raw, agency_id="ASTC", source_file="photocopy")
    bound, _rep = bind_blocks(cs)
    bound = rebind_claim_ids(bound)

    got: dict = {}
    for c in bound.active():
        t, s = str(c.scope.get("trip")), c.scope.get("seq")
        if s is None:
            continue
        row = got.setdefault((t, int(s)), {})
        if c.kind.value == "stop" and c.field == "stop_name":
            row["stop"] = str(c.value)
        elif c.kind.value == "stop_time":
            row[c.field] = str(c.value)

    tally = {f: dict(correct=0, wrong=0, abstained=0, missing=0)
             for f in ("stop", "arrival", "departure")}
    wrongs: list[str] = []
    for key, want in truth.items():
        have = got.get(key, {})
        for field in ("stop", "arrival", "departure"):
            if field not in want:
                continue
            v = have.get(field)
            if v is None:
                tally[field]["missing"] += 1
            elif v == ILLEGIBLE:
                tally[field]["abstained"] += 1
            elif norm(v) == norm(want[field]):
                tally[field]["correct"] += 1
            else:
                tally[field]["wrong"] += 1
                wrongs.append(f"{key} {field}: read {v!r}, truth {want[field]!r}")
    return {"tally": tally, "wrong_detail": wrongs[:12],
            "cells_read": sum(len(v) for v in got.values())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", default=ASTC)
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--level", type=int, default=2, choices=sorted(LEVELS))
    ap.add_argument("--save-image", action="store_true")
    args = ap.parse_args()

    page = render_page(args.pdf, page=args.page)
    truth = truth_from_text_layer(page.text_layer)
    cfg = LEVELS[args.level]

    print("=" * 76)
    print(f"PHOTOCOPY TEST — level {args.level}: {cfg['label']}")
    print("=" * 76)
    print(f"  source          {page.source_uri}")
    print(f"  clean page      {page.width}x{page.height}, "
          f"text layer {len(page.text_layer)} chars")
    print(f"  ground truth    {len(truth)} rows from the clean text layer "
          f"(never shown to the reader)")
    print(f"  degradation     skew {cfg['skew']}° · blur {cfg['blur']} · "
          f"{cfg['speckle']:,} speckles · contrast {cfg['contrast']} · "
          f"JPEG q{cfg['jpeg']}")

    degraded = degrade(page.png_bytes, args.level)
    out_img = ROOT / "out" / f"photocopy_L{args.level}.jpg"
    out_img.parent.mkdir(exist_ok=True)
    out_img.write_bytes(degraded)
    print(f"  degraded image  {len(degraded):,} bytes → "
          f"{out_img.relative_to(ROOT)}")

    print("\n  --- BASELINE (pdftotext + regex) on the degraded artifact ---")
    print("  A JPEG has no text layer. pdftotext has nothing to read.")
    print("  rows parsed: 0    ← this is the entire result")

    print("\n  --- HEADWAY reader on the degraded artifact ---")
    client, cred = build_client()
    print(f"  credential      {cred.backend}")
    raw = read_image(client, degraded, "image/jpeg")
    (ROOT / "out" / f"photocopy_L{args.level}_read.json").write_text(raw)

    s = score(raw, truth)
    print(f"  cells returned  {s['cells_read']}")
    print()
    hdr = f"  {'field':<12}{'correct':>9}{'wrong':>7}{'abstained':>11}{'missing':>9}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    tot = dict(correct=0, wrong=0, abstained=0, missing=0)
    for field, t in s["tally"].items():
        print(f"  {field:<12}{t['correct']:>9}{t['wrong']:>7}"
              f"{t['abstained']:>11}{t['missing']:>9}")
        for k in tot:
            tot[k] += t[k]
    print("  " + "-" * (len(hdr) - 2))
    print(f"  {'TOTAL':<12}{tot['correct']:>9}{tot['wrong']:>7}"
          f"{tot['abstained']:>11}{tot['missing']:>9}")

    graded = sum(tot.values())
    if graded:
        print(f"\n  fidelity        {tot['correct']}/{graded} "
              f"({100 * tot['correct'] / graded:.1f}%)")
        print(f"  CONFIDENT-WRONG {tot['wrong']}  "
              f"← the number that matters; a wrong time no validator catches")
    for w in s["wrong_detail"]:
        print(f"    WRONG {w}")

    (ROOT / "out" / f"photocopy_L{args.level}_score.json").write_text(
        json.dumps({"level": args.level, "config": cfg, "truth_rows": len(truth),
                    "baseline_rows": 0, **s}, indent=2, sort_keys=True) + "\n")
    print(f"\n  written         out/photocopy_L{args.level}_score.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
