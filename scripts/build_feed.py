#!/usr/bin/env python3
"""Compose a GTFS feed from a claim-set JSON file. No model, no network.

  python3 scripts/build_feed.py fixtures/claims/sample_agency.json out/gtfs.zip
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from headway.composer.compose import compose  # noqa: E402
from headway.schema.claims import ClaimSet  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    src, dst = Path(argv[1]), Path(argv[2])
    raw = json.loads(src.read_text())
    cs = ClaimSet.from_dicts(raw["agency_id"], raw["claims"])

    # feed_start is passed in, never read from the clock -> reproducible bytes.
    start = date.fromisoformat(raw.get("feed_start", "2026-08-24"))
    feed = compose(cs, feed_start=start, horizon_days=120)

    dst.parent.mkdir(parents=True, exist_ok=True)
    data = feed.to_zip_bytes()
    dst.write_bytes(data)

    print(f"claim_set_sha256 : {cs.sha256()}")
    print(f"feed_sha256      : {hashlib.sha256(data).hexdigest()}")
    print(f"bytes            : {len(data)}")
    print(f"stats            : {feed.stats.as_dict()}")
    print(f"ambiguous claims : {[c.claim_id for c in cs.ambiguous()]}")
    print(f"illegible claims : {[c.claim_id for c in cs.illegible()]}")
    print(f"abstention rate  : {cs.abstention_rate():.1%}")
    for w in feed.warnings:
        print(f"  warning: {w}")

    print("\n--- stop_times.txt ---")
    print(feed.to_csv_bytes()["stop_times.txt"].decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
