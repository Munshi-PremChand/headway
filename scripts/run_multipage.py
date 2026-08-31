#!/usr/bin/env python3
"""Read several pages, join the services that span them, and compose once.

A 369 km coach service does not fit on one sheet of A4. Page 1 of the ASTC
Guwahati timetable ends mid-service and page 2 opens with the rest of it, under
no heading at all. Run per-page, that service is correctly WITHHELD — correct,
but lossy: a real route is dropped because the paper ran out.

This reads each page independently, binds each independently, and then joins
across the seam — but only when the join can be checked. `reader/stitch.py`
holds the four checks and refuses if any fails. A refused join costs one
service; a wrong join invents a bus route.

Both readers run on every page and both are stitched separately, so the
disagreement gate still compares two independent reads of the whole document
rather than of one page.

    python3 scripts/run_multipage.py --pages 1-2
    python3 scripts/run_multipage.py --pages 1-4 --json out/multipage.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from google.genai import types                                     # noqa: E402

from headway.pipeline import agents as A                           # noqa: E402
from headway.pipeline.credentials import NoCredential, build_client  # noqa: E402
from headway.pipeline.render import render_page                    # noqa: E402
from headway.profiles import load as load_profile, merge           # noqa: E402
from headway.reader.blocks import (                                # noqa: E402
    CONTINUATION, bind_blocks, rebind_claim_ids, withhold_truncated,
)
from headway.reader.gemini_reader import (                         # noqa: E402
    CLAIM_RESPONSE_SCHEMA, DEFAULT_MODEL, GenAIClient,
    READER_THINKING_LEVEL, SECOND_OPINION_MODEL, build_system_prompt,
    parse_claims,
)
from headway.reader.stitch import merge_pages, stitch              # noqa: E402
from headway.schema.claims import ClaimSet, SourceClaim            # noqa: E402

ASTC = ("https://st.redbus.in/Images/WL/ASTC/schedules_new/"
        "Guwahati_division.pdf")
APP = "headway-multipage"
RULE = "─" * 78


def hr(t: str) -> None:
    print(f"\n{RULE}\n{t}\n{RULE}")


def pages_arg(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return sorted(set(out))


def read_page(client, png: bytes, model: str, layout: str) -> str:
    resp = client.models.generate_content(
        model=model,
        contents=[types.Part.from_bytes(data=png, mime_type="image/png"),
                  types.Part.from_text(
                      text="Transcribe every service block on this page into "
                           "claims.")],
        config=types.GenerateContentConfig(
            system_instruction=build_system_prompt(layout),
            response_mime_type="application/json",
            response_schema=CLAIM_RESPONSE_SCHEMA,
            max_output_tokens=32768,
            thinking_config=types.ThinkingConfig(
                thinking_level=READER_THINKING_LEVEL)))
    return GenAIClient.answer_text(resp)


def retract_orphans(cs: ClaimSet) -> tuple[ClaimSet, int]:
    """Rows that were never joined to anything must not be composed.

    They have no route and no heading, so they describe a service this document
    never names on this page. Retracted with the reason, not dropped.
    """
    out, n = [], 0
    for c in cs.claims:
        if str(c.scope.get("trip") or "") == CONTINUATION and not c.retracted:
            n += 1
            c = SourceClaim(
                claim_id=c.claim_id, kind=c.kind, field=c.field, value=c.value,
                confidence=c.confidence, provenance=c.provenance,
                alternatives=list(c.alternatives), scope=dict(c.scope),
                retracted=True,
                retraction_reason=("rows continued from a previous page, but no "
                                   "service could be joined to them"))
        out.append(c)
    return ClaimSet(agency_id=cs.agency_id, claims=out), n


async def run() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", default=ASTC)
    ap.add_argument("--pages", default="1-2")
    ap.add_argument("--profile", default="astc_guwahati")
    ap.add_argument("--single-reader", action="store_true")
    ap.add_argument("--concurrency", type=int, default=4,
                    help="model calls in flight at once")
    ap.add_argument("--offline-geocoding", action="store_true")
    ap.add_argument("--feed-start", default="2026-08-24")
    ap.add_argument("--out", default="out/astc_multipage.zip")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    pages = pages_arg(args.pages)
    profile = load_profile(args.profile)
    layout = profile.layout

    try:
        client, cred = build_client()
    except NoCredential as exc:
        print(exc)
        return 2

    hr(f"READING {len(pages)} PAGE(S) — {cred.backend}")
    models = [DEFAULT_MODEL] + ([] if args.single_reader
                                else [SECOND_OPINION_MODEL])
    per_reader: dict[str, list[tuple[int, ClaimSet]]] = {m: [] for m in models}
    sources: list[dict] = []
    t0 = time.time()

    rendered = [(pg, render_page(args.pdf, page=pg)) for pg in pages]
    sources = [p.as_dict() for _pg, p in rendered]

    # Reads are independent, so run them concurrently. A ten-page division is
    # twenty model calls; sequentially that is a quarter of an hour of waiting
    # for something with no data dependency in it at all. The semaphore keeps
    # the burst inside Vertex's per-minute quota — the point is to stop
    # waiting, not to hammer the endpoint.
    sem = asyncio.Semaphore(args.concurrency)

    async def one(pg: int, png: bytes, model: str):
        async with sem:
            raw = await asyncio.to_thread(read_page, client, png, model, layout)
        cs = parse_claims(raw, agency_id=profile.agency_id,
                          source_file=f"{Path(args.pdf).name}#p{pg}")
        bound, rep = bind_blocks(cs)
        return pg, model, rebind_claim_ids(bound), cs, rep

    results = await asyncio.gather(*[
        one(pg, page.png_bytes, m) for pg, page in rendered for m in models],
        return_exceptions=True)

    failures = [r for r in results if isinstance(r, Exception)]
    for f in failures:
        print(f"  READ FAILED: {type(f).__name__}: {str(f)[:150]}")
    ok = [r for r in results if not isinstance(r, Exception)]

    by_page: dict[int, dict[str, Any]] = {}
    for pg, model, bound, cs, rep in ok:
        per_reader[model].append((pg, bound))
        cont = sum(1 for c in bound.active()
                   if str(c.scope.get("trip") or "") == CONTINUATION)
        by_page.setdefault(pg, {})[model] = (len(cs.active()),
                                             len(rep["blocks"]), cont)
    for m in models:
        per_reader[m].sort(key=lambda t: t[0])

    for pg, page in rendered:
        line = f"  page {pg:>2}  {page.page_sha256[:12]}"
        for m in models:
            got = by_page.get(pg, {}).get(m)
            line += (f"   [{m.split('-')[-1]}] "
                     + (f"{got[0]} claims, {got[1]} blocks"
                        + (f", {got[2]} continuation" if got[2] else "")
                        if got else "FAILED"))
        print(line)
    if failures:
        print(f"\n  {len(failures)} read(s) failed — pages with a failed read are "
              f"NOT silently dropped; their claims are simply absent, and any "
              f"service spanning them will fail its join check.")

    hr("STITCHING ACROSS PAGE SEAMS")
    stitched: dict[str, ClaimSet] = {}
    all_joins = []
    for m in models:
        pieces, joins = stitch(per_reader[m])
        merged = merge_pages(pieces, profile.agency_id)
        # Withhold anything that is STILL truncated after the join attempt.
        rebound, rep = bind_blocks(merged)
        merged, _ = withhold_truncated(merged, {
            "truncated_trips": [t for t in rep.get("truncated_trips", [])
                                if t != CONTINUATION],
            "blocks": rep.get("blocks", [])})
        merged, orphans = retract_orphans(merged)
        stitched[m] = merge(merged, profile)
        if m == models[0]:
            all_joins = joins
            for j in joins:
                mark = "JOINED " if j.accepted else "REFUSED"
                print(f"  [{mark}] page {j.from_page} → {j.to_page}, service "
                      f"{j.trip}: +{j.rows_added} rows")
                for name, detail in j.checks.items():
                    print(f"            {name:<12} {detail}")
                if not j.accepted:
                    print(f"            reason: {j.refused_because}")
            if orphans:
                print(f"  {orphans} orphan claim(s) retracted — nothing to join "
                      f"them to")
            if not joins:
                print("  no page seam had a continuation to join")

    hr("RUN")
    pipeline = A.build_downstream_pipeline(
        profile_id=args.profile, on_ungeocoded="omit",
        offline_geocoding=args.offline_geocoding)

    from google.adk.runners import InMemoryRunner
    runner = InMemoryRunner(agent=pipeline, app_name=APP)
    state = {
        A.K_AGENCY: profile.agency_id,
        A.K_FEED_START: args.feed_start,
        A.K_SOURCE: f"{Path(args.pdf).name}#p{args.pages}",
        A.K_BOUND_PRIMARY: stitched[models[0]].canonical_json(),
    }
    if len(models) > 1:
        state[A.K_BOUND_SECOND] = stitched[models[1]].canonical_json()
    session = await runner.session_service.create_session(
        app_name=APP, user_id="operator", state=state)

    async for event in runner.run_async(
            user_id="operator", session_id=session.id,
            new_message=types.Content(role="user", parts=[
                types.Part.from_text(text="compose")])):
        if not (event.content and event.content.parts):
            continue
        for part in event.content.parts:
            txt = getattr(part, "text", None)
            if not txt or getattr(part, "thought", False):
                continue
            head, *rest = txt.strip().splitlines()
            print(f"  [{event.author}] {head}")
            for ln in rest:
                print(f"      {ln.strip()}")

    final = await runner.session_service.get_session(
        app_name=APP, user_id="operator", session_id=session.id)
    st = dict(final.state)
    elapsed = time.time() - t0

    hr("LEDGER")
    validation = st.get(A.K_VALIDATION) or {}
    stats = st.get(A.K_STATS) or {}
    print(f"  {'pages read':>26}: {pages}")
    print(f"  {'wall clock':>26}: {elapsed:.1f}s")
    print(f"  {'joins accepted':>26}: "
          f"{sum(1 for j in all_joins if j.accepted)} of {len(all_joins)}")
    print(f"  {'feed':>26}: {stats}")
    if validation:
        print(f"  {'ERROR':>26}: {validation['errors']}")
        print(f"  {'WARNING':>26}: {validation['warnings']}")
        print(f"  {'feed sha256':>26}: {validation['feed_sha256']}")
        if st.get(A.K_FEED):
            out = ROOT / args.out
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(bytes.fromhex(st[A.K_FEED]))
            print(f"\n  feed written to {out.relative_to(ROOT)}")
    else:
        print("  no feed was composed")

    if args.json:
        p = ROOT / args.json
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "pages": pages, "sources": sources,
            "joins": [j.as_dict() for j in all_joins],
            "stats": stats, "validation": validation,
            "escalations": st.get(A.K_ESCALATIONS) or [],
            "warnings": st.get("compose_warnings") or [],
            "elapsed_seconds": round(elapsed, 2),
        }, indent=2, sort_keys=True) + "\n")
        print(f"  ledger written to {p.relative_to(ROOT)}")

    return 0 if validation.get("errors") == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
