#!/usr/bin/env python3
"""Assemble everything the demo page draws into one JSON, plus the page image.

The page has to show provenance — a box on the scan for every claim, coloured
by what happened to it — and the two-feed comparison. Both come from a real
run; nothing here is hand-authored.

By default this REUSES the reads saved by `scripts/run_pipeline.py` under
`out/reads/`, so the demo can be rebuilt without spending model calls and
without the run-to-run variation that would make a filmed take unrepeatable.
`--live` re-reads the page with both models instead.

    python3 scripts/build_demo_data.py            # from saved reads
    python3 scripts/build_demo_data.py --live     # call the models again
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from headway.composer.compose import compose                       # noqa: E402
from headway.geo.geocode import Geocoder                           # noqa: E402
from headway.geo.plausibility import check_trip                    # noqa: E402
from headway.geo.plausibility import report as plaus_report        # noqa: E402
from headway.pipeline.render import render_page                    # noqa: E402
from headway.pipeline.validate import run_validator                # noqa: E402
from headway.profiles import load as load_profile, merge           # noqa: E402
from headway.reader.blocks import (                                # noqa: E402
    bind_blocks, rebind_claim_ids, withhold_truncated,
)
from headway.reader.gemini_reader import parse_claims              # noqa: E402
from headway.schema.claims import ClaimKind, ClaimSet, SourceClaim  # noqa: E402
from scripts.baseline_textlayer import parse_text_layer            # noqa: E402

ASTC = ("https://st.redbus.in/Images/WL/ASTC/schedules_new/"
        "Guwahati_division.pdf")
WEB = ROOT / "web"
DATA = WEB / "data"


def geocode_all(cs: ClaimSet, profile, offline: bool):
    geo = Geocoder(region=profile.geocode_region,
                   viewbox=profile.geocode_viewbox,
                   aliases=profile.stop_aliases, offline=offline)
    names = [str(c.value) for c in cs.active()
             if c.kind is ClaimKind.STOP and c.field == "stop_name"]
    return geo.resolve_all(names)


def place(cs: ClaimSet, fixes) -> ClaimSet:
    out = []
    for c in cs.claims:
        if c.kind is ClaimKind.STOP and c.field == "stop_name" and not c.retracted:
            f = fixes.get(str(c.value))
            scope = dict(c.scope)
            if f:
                scope.update({"lat": f.lat, "lon": f.lon,
                              "geocode_precision": f.precision,
                              "geocode_osm": f"{f.osm_type}/{f.osm_id}"})
            c = SourceClaim(claim_id=c.claim_id, kind=c.kind, field=c.field,
                            value=c.value, confidence=c.confidence,
                            provenance=c.provenance, scope=scope,
                            retracted=c.retracted,
                            retraction_reason=c.retraction_reason)
        out.append(c)
    return ClaimSet(agency_id=cs.agency_id, claims=out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", default=ASTC)
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--profile", default="astc_guwahati")
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    profile = load_profile(args.profile)
    page = render_page(args.pdf, page=args.page)
    (DATA / "page.png").write_bytes(page.png_bytes)

    if args.live:
        subprocess.run([sys.executable, "scripts/run_pipeline.py",
                        "--pdf", args.pdf, "--page", str(args.page),
                        "--profile", args.profile], cwd=ROOT, check=False)
    raw_path = ROOT / "out" / "reads" / "reader_primary.json"
    if not raw_path.exists():
        print("no saved read; run scripts/run_pipeline.py first, or pass --live")
        return 1
    raw = raw_path.read_text()

    # ---------------------------------------------------------- HEADWAY path
    cs = parse_claims(raw, agency_id=profile.agency_id,
                      source_file=f"{Path(args.pdf).name}#p{args.page}")
    bound, binding = bind_blocks(cs)
    bound, _withheld = withhold_truncated(bound, binding)
    bound = rebind_claim_ids(bound)
    bound = merge(bound, profile)

    fixes, refusals = geocode_all(bound, profile, offline=not args.live)
    located = place(bound, fixes)
    feed = compose(located, feed_start=date(2026, 8, 24), horizon_days=120,
                   on_ungeocoded="omit")
    hw_bytes = feed.to_zip_bytes()
    hw_report = run_validator(hw_bytes)
    (DATA / "headway.zip").write_bytes(hw_bytes)

    # ---------------------------------------------------------- baseline path
    b_cs, b_stats = parse_text_layer(page.text_layer, profile.agency_id)
    b_fixes, _b_ref = geocode_all(b_cs, profile, offline=True)
    b_cs = merge(place(b_cs, b_fixes), profile)
    b_feed = compose(b_cs, feed_start=date(2026, 8, 24), horizon_days=120,
                     on_ungeocoded="omit")
    b_bytes = b_feed.to_zip_bytes()
    b_report = run_validator(b_bytes)
    (DATA / "baseline.zip").write_bytes(b_bytes)

    # ------------------------------------------------------------- the claims
    truncated = set(binding.get("truncated_trips") or [])
    unplaced = set(refusals)
    claims = []
    for c in located.claims:
        bb = c.provenance.bbox
        if not bb:
            continue
        if c.retracted:
            status = "withheld"
        elif (c.kind is ClaimKind.STOP and c.field == "stop_name"
              and str(c.value) in unplaced):
            status = "unplaced"
        else:
            status = "composed"
        claims.append({
            "id": c.claim_id,
            "kind": c.kind.value,
            "field": c.field,
            "value": str(c.value),
            "bbox": [round(v, 5) for v in bb],
            "trip": c.scope.get("trip"),
            "seq": c.scope.get("seq"),
            "km": c.scope.get("km"),
            "status": status,
            "reason": c.retraction_reason or (
                refusals[str(c.value)].reason if status == "unplaced" else ""),
        })

    # -------------------------------------------------------- the km geometry
    trips: dict = {}
    for c in located.active():
        if c.kind is not ClaimKind.STOP_TIME:
            continue
        row = trips.setdefault(str(c.scope.get("trip")), {}).setdefault(
            int(c.scope.get("seq") or 0), {})
        row["stop"] = str(c.scope.get("stop") or "")
        row.setdefault("km", c.scope.get("km"))
        f = fixes.get(row["stop"])
        if f:
            row["lat"], row["lon"] = f.lat, f.lon
    segments = []
    for t in sorted(trips):
        segments.extend(check_trip(t, [trips[t][s] for s in sorted(trips[t])]))

    def feed_rows(f):
        return [{"trip": r["trip_id"],
                 "headsign": r["trip_headsign"]} for r in f.tables["trips.txt"]]

    payload = {
        "source": page.as_dict(),
        "profile": profile.as_dict(),
        "blocks": binding["blocks"],
        "columnRoles": binding.get("column_roles", {}),
        "claims": claims,
        "geocode": {
            "resolved": {n: f.as_dict() for n, f in fixes.items()},
            "refused": {n: r.as_dict() for n, r in refusals.items()},
        },
        "plausibility": plaus_report(segments),
        "headway": {
            "stats": feed.stats.as_dict(),
            "trips": feed_rows(feed),
            "warnings": feed.warnings,
            "validation": hw_report,
        },
        "baseline": {
            "approach": "pdftotext -layout + regular expressions",
            "parseStats": b_stats,
            "stats": b_feed.stats.as_dict(),
            "trips": feed_rows(b_feed),
            "warnings": b_feed.warnings,
            "validation": b_report,
        },
    }
    (DATA / "run.json").write_text(json.dumps(payload, indent=2) + "\n")

    print(f"page.png     {len(page.png_bytes):>9,} bytes  "
          f"{page.width}x{page.height}")
    print(f"claims       {len(claims):>9}  "
          f"({sum(1 for c in claims if c['status']=='withheld')} withheld, "
          f"{sum(1 for c in claims if c['status']=='unplaced')} unplaced)")
    print(f"HEADWAY      trips={feed.stats.trips} "
          f"stop_times={feed.stats.stop_times} ERROR={hw_report['errors']}")
    print(f"baseline     trips={b_feed.stats.trips} "
          f"stop_times={b_feed.stats.stop_times} ERROR={b_report['errors']}")
    print(f"written      {(DATA / 'run.json').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
