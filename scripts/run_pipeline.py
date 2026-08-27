#!/usr/bin/env python3
"""Run the whole pipeline against one real page and print the run ledger.

    python3 scripts/run_pipeline.py \
        --pdf https://st.redbus.in/Images/WL/ASTC/schedules_new/Guwahati_division.pdf \
        --page 1 --profile astc_guwahati

What it does, in order:

  1. fetches the PDF, renders one page to PNG at a fixed DPI, and hashes both;
  2. runs `build_pipeline()` under an ADK `InMemoryRunner`, streaming each
     agent's narration as it happens;
  3. prints a ledger: what was read, what geometry decided, what was withheld,
     what could not be located, and the validator's verdict on the exact bytes.

The ledger is the point. A run that says "ERROR=0" and nothing else is not
evidence of anything — the interesting numbers are the ones next to it: how
many cells the two readers disagreed on, how many stops had no coordinate, how
many services were withheld for running off the bottom of the page. Every one
of those is printed by the code that computed it. Nothing in this output is
typed by hand.

Exit status is 0 only when the publish gate opened.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from google.genai import types                                     # noqa: E402

from headway.pipeline import agents as A                           # noqa: E402
from headway.pipeline.credentials import NoCredential, build_client  # noqa: E402
from headway.pipeline.render import render_page                    # noqa: E402
from headway.profiles import load as load_profile                  # noqa: E402

APP = "headway"
RULE = "─" * 78


def hr(title: str) -> None:
    print(f"\n{RULE}\n{title}\n{RULE}")


def _summarise_read(raw: str) -> str:
    """One line describing a reader's response, computed from the response."""
    from collections import Counter
    from headway.reader.gemini_reader import detect_bbox_convention
    try:
        rows = json.loads(raw).get("claims", [])
    except json.JSONDecodeError:
        return f"{len(raw)} characters that are not JSON"
    kinds = Counter(f"{r.get('kind')}/{r.get('field')}" for r in rows
                    if isinstance(r, dict))
    convention, geometry = detect_bbox_convention(
        [r.get("bbox") for r in rows if isinstance(r, dict)])
    detail = " ".join(f"{k}={v}" for k, v in sorted(kinds.items()))
    agree = "" if geometry.get("agree") else "  [GEOMETRY SIGNALS DISAGREE]"
    return (f"{len(rows)} claims · bbox convention {convention}{agree} · "
            f"{detail}")


def build_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pdf", required=True,
                   help="URL or local path of the source document")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--dpi", type=int, default=200)
    p.add_argument("--profile", default="astc_guwahati",
                   help="operator profile supplying timezone, calendar, region")
    p.add_argument("--layout", default=None,
                   help="override the profile's page layout")
    p.add_argument("--feed-start", default="2026-08-24",
                   help="first service date; passed in, never read from the clock")
    p.add_argument("--single-reader", action="store_true",
                   help="skip the second opinion (cheaper; no corroboration)")
    p.add_argument("--refuse-ungeocoded", action="store_true",
                   help="publish nothing unless every stop has a coordinate")
    p.add_argument("--offline-geocoding", action="store_true",
                   help="use only the committed geocode cache; make no requests")
    p.add_argument("--out", default="out/astc.zip",
                   help="where to write the feed if the gate opens")
    p.add_argument("--json", default="",
                   help="also write the full ledger as JSON to this path")
    return p.parse_args()


async def run() -> int:
    args = build_args()
    profile = load_profile(args.profile)
    layout = args.layout or profile.layout

    hr("SOURCE")
    page = render_page(args.pdf, page=args.page, dpi=args.dpi)
    for k, v in page.as_dict().items():
        print(f"  {k:>18}: {v}")

    hr("CREDENTIAL")
    try:
        client, cred = build_client()
    except NoCredential as exc:
        print(exc)
        return 2
    print(f"  {'backend':>18}: {cred.backend}")
    print(f"  {'detail':>18}: {cred.detail}")
    if cred.project:
        print(f"  {'project':>18}: {cred.project} @ {cred.location}")

    hr("OPERATOR PROFILE (declared, not read off the page)")
    print(f"  {'agency':>18}: {profile.agency_name} ({profile.agency_id})")
    print(f"  {'timezone':>18}: {profile.agency_timezone}")
    print(f"  {'calendar':>18}: {profile.service_id} = "
          f"{', '.join(profile.service_days)}")
    print(f"  {'layout':>18}: {layout}")
    for a in profile.assumed:
        print(f"  {'ASSUMPTION':>18}: {a} is assumed, not printed on the page")

    pipeline = A.build_pipeline(
        layout=layout,
        profile_id=args.profile,
        client=client,
        second_model=None if args.single_reader else A.SECOND_OPINION_MODEL,
        on_ungeocoded="refuse" if args.refuse_ungeocoded else "omit",
        offline_geocoding=args.offline_geocoding,
    )

    from google.adk.runners import InMemoryRunner
    runner = InMemoryRunner(agent=pipeline, app_name=APP)
    session = await runner.session_service.create_session(
        app_name=APP, user_id="operator",
        state={
            A.K_AGENCY: profile.agency_id,
            A.K_FEED_START: args.feed_start,
            A.K_SOURCE: f"{Path(args.pdf).name}#p{args.page}",
        })

    hr("RUN")
    t0 = time.time()
    message = types.Content(role="user", parts=[
        types.Part.from_bytes(data=page.png_bytes, mime_type="image/png"),
        types.Part.from_text(
            text="Transcribe every service block on this page into claims."),
    ])
    async for event in runner.run_async(user_id="operator",
                                        session_id=session.id,
                                        new_message=message):
        if not (event.content and event.content.parts):
            continue
        for part in event.content.parts:
            text = getattr(part, "text", None)
            if not text or getattr(part, "thought", False):
                continue
            stripped = text.strip()
            if stripped.startswith("{"):
                # A reader's whole structured response. Summarise it; dumping
                # 13k characters of JSON into the run log buries every line
                # that actually says what the pipeline decided. The raw text is
                # kept on disk instead — a run whose reads cannot be re-examined
                # afterwards cannot be debugged, and the reads vary.
                raw_dir = ROOT / "out" / "reads"
                raw_dir.mkdir(parents=True, exist_ok=True)
                (raw_dir / f"{event.author}.json").write_text(stripped)
                print(f"  [{event.author}] {_summarise_read(stripped)}")
                continue
            head, *rest = stripped.splitlines()
            print(f"  [{event.author}] {head}")
            for line in rest:
                print(f"      {line.strip()}")
    elapsed = time.time() - t0

    final = await runner.session_service.get_session(
        app_name=APP, user_id="operator", session_id=session.id)
    st = dict(final.state)
    return report(args, page, st, elapsed)


def report(args, page, st: dict, elapsed: float) -> int:
    binding = st.get(A.K_BINDING) or {}
    geo = st.get(A.K_GEOCODE) or {}
    plaus = st.get(A.K_PLAUSIBILITY) or {}
    validation = st.get(A.K_VALIDATION) or {}
    stats = st.get(A.K_STATS) or {}
    escalations = st.get(A.K_ESCALATIONS) or []
    unconfirmed = st.get(A.K_UNCONFIRMED) or []

    hr("LEDGER")
    print(f"  {'wall clock':>26}: {elapsed:.1f}s")
    print(f"  {'page sha256':>26}: {page.page_sha256}")

    blocks = binding.get("blocks") or []
    if blocks:
        kept = [b for b in blocks if not b["truncated"]]
        print(f"  {'service blocks on page':>26}: {len(blocks)} "
              f"({len(kept)} complete, {len(blocks) - len(kept)} withheld)")
        for b in blocks:
            mark = "withheld" if b["truncated"] else "composed"
            print(f"  {'':>26}  [{mark}] {b['trip']}. {b['heading']}")
            if b["truncated"]:
                print(f"  {'':>26}            {b['reason']}")
    if binding.get("column_roles"):
        print(f"  {'time columns (geometry)':>26}: {binding['column_roles']}")
    dissent = binding.get("column_dissent") or []
    print(f"  {'cells dissenting on col':>26}: {len(dissent)}")

    print(f"  {'reader disagreements':>26}: {len(escalations)} escalated, "
          f"withheld from composition")
    print(f"  {'cells with one read only':>26}: {len(unconfirmed)}")

    resolved = geo.get("resolved") or {}
    refused = geo.get("refused") or {}
    print(f"  {'stops located':>26}: {len(resolved)}")
    print(f"  {'stops refused (no guess)':>26}: {len(refused)}")
    for n, r in sorted(refused.items()):
        print(f"  {'':>26}  {n}: {r['reason']}")
    if plaus:
        print(f"  {'road-vs-straight-line':>26}: {plaus['verdict']} "
              f"({plaus['segments_checked']} segments, tightest margin "
              f"{plaus['tightest_margin_km']} km)")

    for key, label in (("compose_warnings", "composer warnings"),
                       ("omitted_stops", "stops omitted from trips"),
                       ("dropped_trips", "trips dropped")):
        val = st.get(key) or []
        if val:
            print(f"  {label:>26}: {len(val)}")
            for v in val:
                print(f"  {'':>26}  {v}")

    if stats:
        print(f"  {'feed':>26}: {stats}")

    if not validation:
        hr("PUBLISH GATE — CLOSED")
        print("  No validation report. The feed was never composed, so the gate\n"
              "  could not even be attempted. Nothing ships.")
        return 1

    hr(f"PUBLISH GATE — {validation['publish_gate']}")
    print(f"  {'validator':>26}: gtfs-validator {validation['validator_version']}")
    print(f"  {'validator sha256':>26}: {validation['validator_sha256'][:32]}…")
    print(f"  {'feed sha256':>26}: {validation['feed_sha256']}")
    print(f"  {'ERROR':>26}: {validation['errors']}")
    print(f"  {'WARNING':>26}: {validation['warnings']}")
    print(f"  {'INFO':>26}: {validation['infos']}")
    parsed = validation.get("parsed") or {}
    print(f"  {'rows the validator read':>26}: {parsed.get('counts')}")
    print(f"  {'notice codes':>26}:")
    for sev, code in validation.get("codes", []):
        print(f"  {'':>26}  {sev:<8} {code}")

    if st.get(A.K_FEED):
        out = ROOT / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(bytes.fromhex(st[A.K_FEED]))
        print(f"\n  feed written to {out.relative_to(ROOT)}")

    if args.json:
        payload = {
            "source": page.as_dict(), "binding": binding, "geocode": geo,
            "plausibility": plaus, "validation": validation, "stats": stats,
            "escalations": escalations, "unconfirmed": unconfirmed,
            "warnings": st.get("compose_warnings") or [],
            "omitted_stops": st.get("omitted_stops") or [],
            "dropped_trips": st.get("dropped_trips") or [],
            "elapsed_seconds": round(elapsed, 2),
        }
        p = ROOT / args.json
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        print(f"  ledger written to {p.relative_to(ROOT)}")

    return 0 if validation["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
