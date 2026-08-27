#!/usr/bin/env python3
"""The clarification decision, made on rider outcomes rather than confidence.

For every ambiguous claim, compile BOTH readings and diff the rider journeys.
  * identical journeys  -> resolve silently, log "ambiguity did not matter"
  * different journeys   -> escalate ONE question, phrased as a consequence

This is the number that goes on screen:
  "N ambiguities. N-k resolved autonomously. k escalated, because they change
   when someone gets to dialysis."

  python3 scripts/ambiguity_report.py fixtures/claims/sample_agency.json
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from headway.composer.compose import compose  # noqa: E402
from headway.composer.outcomes import (  # noqa: E402
    diff_events, enumerate_events, read_feed, stop_names,
)
from headway.schema.claims import ClaimSet  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    raw = json.loads(Path(argv[1]).read_text())
    cs = ClaimSet.from_dicts(raw["agency_id"], raw["claims"])
    start = date.fromisoformat(raw.get("feed_start", "2026-08-24"))

    base = compose(cs, feed_start=start, horizon_days=120)
    names = stop_names(read_feed(base.to_zip_bytes()))

    ambiguous = cs.ambiguous()
    print(f"claim set        : {cs.sha256()[:16]}")
    print(f"total claims     : {len(cs.active())}")
    print(f"ambiguous claims : {len(ambiguous)}")
    print(f"illegible claims : {len(cs.illegible())} "
          f"(abstention {cs.abstention_rate():.1%})")
    print()

    suppressed, escalated = 0, []

    for c in ambiguous:
        primary = cs.branch_on(c.claim_id, type(c.alternatives[0])(
            value=c.value, confidence=c.confidence, rationale="primary reading"))
        for alt in c.alternatives:
            other = cs.branch_on(c.claim_id, alt)
            try:
                fa = compose(primary, feed_start=start, horizon_days=120)
                fb = compose(other, feed_start=start, horizon_days=120)
            except Exception as exc:                       # noqa: BLE001
                escalated.append((c, alt, f"one reading does not compile: {exc}"))
                continue

            ja = enumerate_events(fa.to_zip_bytes(), window_start=start, window_days=28)
            jb = enumerate_events(fb.to_zip_bytes(), window_start=start, window_days=28)
            d = diff_events(ja, jb)

            if d.is_empty:
                suppressed += 1
                print(f"[SUPPRESSED] {c.claim_id}: {c.value!r} vs {alt.value!r} "
                      f"-> identical rider journeys; resolved autonomously")
            else:
                escalated.append((c, alt, d.summary(names)))
                print(f"[ESCALATE]   {c.claim_id}: {c.value!r} vs {alt.value!r}")
                print(f"  affects {d.affected_riders} rider journeys")
                print(f"  {d.summary(names)}")

    print()
    print("=" * 68)
    print(f"{len(ambiguous)} ambiguities · {suppressed} resolved autonomously · "
          f"{len(escalated)} escalated")
    print("=" * 68)
    for c, alt, why in escalated:
        src = c.provenance
        box = f" bbox={src.bbox}" if src.bbox else ""
        print(f"\nQUESTION for the dispatcher")
        print(f"  source : {src.source_file} p{src.page}{box}")
        print(f"  reading A: {c.value!r}   (confidence {c.confidence:.2f})")
        print(f"  reading B: {alt.value!r}   (confidence {alt.confidence:.2f})")
        print(f"  why it matters: {why.splitlines()[0]}")
        print(f"  {alt.rationale}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
