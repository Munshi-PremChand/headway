"""Bind a service-block timetable from bounding-box geometry. NO MODEL.

`grid.py` handles the MATRIX layout — stops down the rows, trips across the
columns. Real Indian intercity timetables mostly are not that shape. An ASTC
division page is a stack of numbered blocks:

    3. Service : Guwahati to Bihpuria (Day Super)
    ┌───────┬────────────────┬─────┬──────────────┬────────────────┐
    │ Sl.No │ Station        │ km  │ Arrival time │ Departure time │
    ├───────┼────────────────┼─────┼──────────────┼────────────────┤
    │   1   │ Paltanbazar    │  0  │              │    8.15 AM     │
    │   2   │ Khanapara      │ 10  │   8.30 AM    │    8.35 AM     │
    └───────┴────────────────┴─────┴──────────────┴────────────────┘

Each block is ONE trip laid out vertically, with a genuine arrival/departure
pair per stop. Three things have to be recovered, and the division of labour
between the model and the geometry is not the same for all three:

  * **Which block a cell belongs to** — the block NUMBER IS PRINTED on the
    page, so reading it is transcription and the model does it. Geometry is
    only the fallback for a claim that arrives without a label. Deriving this
    from heading positions instead was tried and measured: one malformed
    heading box was enough to put a whole block inside its neighbour.
  * **Which row it is on** — the stop names down the block ARE the rows, in
    rank order. Not a coordinate band: the two readers disagree about absolute
    coordinates by up to two row heights on the same page, and matching by
    nearest band turned that drift into a dozen phantom disagreements per run.
    Rank order is immune to drift; cells are then matched to the nearest stop
    row within the SAME read, so each reader's drift cancels against itself.
  * **Whether it is an arrival or a departure** — the two time columns occupy
    different x bands. The model also labels each cell, and where the label
    and the geometry disagree the cell is ESCALATED rather than resolved.
    Two independent derivations of the same fact are worth having precisely
    because they can disagree.

The truncation rule is the part that matters most on real pages. In this
format a completed run ends with a terminus row: an arrival and NO departure,
because the bus stops there. A block whose last row has BOTH times did not
end — it ran off the bottom of the page and continues on the next one. That is
a structural fact with one correct answer, and it is the difference between
publishing a 409 km coach service and publishing a truncated stump of it that
claims the bus terminates at Jamugurihat. Truncated blocks are withheld and
named.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from headway.schema.claims import ClaimKind, ClaimSet, SourceClaim

# A row band. Text in one printed table row varies by a couple of percent of
# page height; consecutive rows on an A4 page are roughly 1.6% apart, so this
# tolerance groups a row without swallowing its neighbour.
ROW_TOLERANCE = 0.008
COL_TOLERANCE = 0.06

# How close to the bottom edge counts as "ran off the page". A block whose last
# row sits above this and still has no terminus row is malformed rather than
# truncated, and is reported differently.
PAGE_BOTTOM = 0.93

ARRIVAL = "arrival"
DEPARTURE = "departure"


@dataclass
class Block:
    """One service block: a heading, its rows, and whether it is complete."""
    key: str
    heading: str
    top: float
    bottom: float
    rows: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    truncation_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "trip": self.key,
            "heading": self.heading,
            "rows": len(self.rows),
            "truncated": self.truncated,
            "reason": self.truncation_reason,
        }


def _centre_y(c: SourceClaim) -> float | None:
    bb = c.provenance.bbox
    return None if not bb else (bb[1] + bb[3]) / 2.0


def _top_y(c: SourceClaim) -> float | None:
    """The TOP edge of a claim's box.

    Block boundaries use this rather than the centre, and the difference is
    load-bearing. MEASURED 2026-08-27: gemini-3.5-flash-lite returned a heading
    box spanning y 0.200 to 0.617 — a text heading reported as taller than a
    third of the page. Its CENTRE lands at 0.409, two thirds of the way down a
    block whose stops start at 0.244, so the first eight stops of the block
    fell above their own heading and were dropped from the binding entirely.
    They came back as eight silent non-claims, and the four that survived were
    renumbered seq 1-4 — which the disagreement gate then reported as the two
    models disagreeing about whether stop 1 is Paltanbazar or Narayanpur.

    A heading's top edge is a sound lower bound for its block even when the
    box's height is nonsense, because a block cannot begin above the first
    pixel of its own title.
    """
    bb = c.provenance.bbox
    return None if not bb else min(bb[1], bb[3])


def _centre_x(c: SourceClaim) -> float | None:
    bb = c.provenance.bbox
    return None if not bb else (bb[0] + bb[2]) / 2.0


def _cluster(values: list[float], tolerance: float) -> list[float]:
    """One-dimensional clustering: values within `tolerance` share a band."""
    if not values:
        return []
    ordered = sorted(values)
    bands: list[list[float]] = [[ordered[0]]]
    for v in ordered[1:]:
        if v - bands[-1][-1] <= tolerance:
            bands[-1].append(v)
        else:
            bands.append([v])
    return [sum(b) / len(b) for b in bands]


def _nearest(centres: list[float], value: float) -> int:
    return min(range(len(centres)), key=lambda i: abs(centres[i] - value))


def _trip_key(c: SourceClaim) -> str:
    return str(c.scope.get("trip") or "").strip()


def _assign_columns(
    cells: list[SourceClaim],
) -> tuple[dict[int, str], list[float], list[dict[str, Any]]]:
    """Decide which x band is arrivals and which is departures.

    Geometry votes, the model's own `field` labels are the ballots, and a cell
    that dissents from its own column is reported so the gate can withhold it.
    """
    xs = [x for x in (_centre_x(c) for c in cells) if x is not None]
    centres = _cluster(xs, COL_TOLERANCE)
    if not centres:
        return {}, [], []

    votes: dict[int, dict[str, int]] = {}
    for c in cells:
        x = _centre_x(c)
        if x is None:
            continue
        fld = c.field.strip().lower()
        if fld in (ARRIVAL, DEPARTURE):
            ci = _nearest(centres, x)
            votes.setdefault(ci, {}).setdefault(fld, 0)
            votes[ci][fld] += 1

    col_field = {ci: max(v, key=lambda k: v[k]) for ci, v in votes.items()}

    dissent: list[dict[str, Any]] = []
    for c in cells:
        x = _centre_x(c)
        if x is None:
            continue
        ci = _nearest(centres, x)
        want = col_field.get(ci)
        got = c.field.strip().lower()
        if want and got in (ARRIVAL, DEPARTURE) and got != want:
            dissent.append({
                "claim_id": c.claim_id,
                "reason": "the reader labelled this cell "
                          f"{got!r} but it sits in the {want!r} column",
                "value": str(c.value),
                "bbox": list(c.provenance.bbox or ()),
            })
    return col_field, centres, dissent


def bind_blocks(cs: ClaimSet) -> tuple[ClaimSet, dict[str, Any]]:
    """Bind stop/stop_time claims to a block, a row and a time column.

    Returns the bound ClaimSet and a report of what geometry decided, so a run
    ledger can show the binding instead of asserting it.
    """
    routes = [c for c in cs.active()
              if c.kind is ClaimKind.ROUTE and _top_y(c) is not None]
    routes.sort(key=lambda c: _top_y(c) or 0.0)

    blocks: list[Block] = []
    for i, r in enumerate(routes):
        top = _top_y(r) or 0.0
        bottom = (_top_y(routes[i + 1]) or 1.0) if i + 1 < len(routes) else 1.0
        blocks.append(Block(key=_trip_key(r) or str(i + 1),
                            heading=str(r.value), top=top, bottom=bottom))

    by_key = {b.key: b for b in blocks}

    def block_for(claim: SourceClaim, y: float) -> Block | None:
        """Which block a claim belongs to.

        The block NUMBER is printed on the page — "3. Service : Guwahati to
        Bihpuria" — so reading it is transcription, which is what the model is
        for, and it is labelled on every claim. Geometry owns row and column
        because those are *not* printed; it does not own this.

        MEASURED 2026-08-27: deriving block membership from heading geometry
        instead put the second reader's block 2 inside block 3, because one
        malformed heading box reordered the blocks when they were sorted by
        position. Both readers had labelled every one of those claims "2".
        Geometry stays as the fallback for a claim that carries no label.
        """
        key = _trip_key(claim)
        if key and key in by_key:
            return by_key[key]
        chosen = None
        for b in blocks:
            if b.top <= y < b.bottom:
                chosen = b
        return chosen

    stops = [c for c in cs.active()
             if c.kind is ClaimKind.STOP and c.field == "stop_name"]
    kms = [c for c in cs.active()
           if c.kind is ClaimKind.STOP and c.field == "km"]
    cells = [c for c in cs.active() if c.kind is ClaimKind.STOP_TIME]

    col_field, _centres, dissent = _assign_columns(cells)
    col_centres = _centres

    # Row bands are computed PER BLOCK. Clustering the whole page at once
    # merges the last row of one block with the header of the next whenever
    # two tables happen to sit close together.
    per_block: dict[str, dict[str, Any]] = {}
    for b in blocks:
        b_stops = [c for c in stops
                   if (y := _centre_y(c)) is not None and block_for(c, y) is b]
        b_kms = [c for c in kms
                 if (y := _centre_y(c)) is not None and block_for(c, y) is b]
        b_cells = [c for c in cells
                   if (y := _centre_y(c)) is not None and block_for(c, y) is b]
        # THE ROW AXIS IS THE STOP COLUMN, IN RANK ORDER.
        #
        # Clustering y into bands and taking the nearest band was the obvious
        # thing and it is wrong here. MEASURED 2026-08-27: the two readers do
        # not agree on absolute coordinates. Reading the same block,
        # gemini-3.7-flash put Paltanbazar at y=0.2615 and North Lakhimpur at
        # 0.4635; gemini-3.5-flash-lite put them at 0.2445 and 0.4800 — a
        # progressive stretch of nearly two row heights down the block. Both
        # readings are internally ordered correctly and both name the same
        # twelve stops in the same sequence.
        #
        # Under nearest-band matching that drift silently reindexed the second
        # read, and the disagreement gate then reported that one model had read
        # "Paltanbazar" where the other read "Narayanpur" — eight to twelve
        # escalations per run, every one of them manufactured by the binder
        # rather than found in the page. A gate that invents disagreements is
        # worse than no gate: it withholds correct claims and buries any real
        # disagreement in noise.
        #
        # Rank order is immune to it. A service block is a vertical list, so
        # the nth stop name down the block IS stop n, whatever coordinate the
        # model assigned it. Timetable cells are then matched to the NEAREST
        # STOP ROW WITHIN THE SAME READ, so each reader's drift cancels against
        # itself instead of being compared across readers.
        ordered_stops = sorted(
            ((y, c) for c in b_stops if (y := _centre_y(c)) is not None),
            key=lambda pair: pair[0])
        per_block[b.key] = {
            "block": b,
            "stops": b_stops,
            "kms": b_kms,
            "cells": b_cells,
            "row_stops": [c for _y, c in ordered_stops],
            "rows": [y for y, _c in ordered_stops],
        }

    bound: list[SourceClaim] = []
    unplaced: list[str] = []
    filled = {"trip": 0, "stop": 0, "seq": 0, "field": 0, "km": 0}

    def rebuild(c: SourceClaim, scope: dict[str, Any],
                fld: str | None = None) -> SourceClaim:
        return SourceClaim(
            claim_id=c.claim_id, kind=c.kind, field=fld or c.field,
            value=c.value, confidence=c.confidence, provenance=c.provenance,
            alternatives=list(c.alternatives), scope=scope,
            retracted=c.retracted, retraction_reason=c.retraction_reason)

    for c in cs.claims:
        if c.kind is ClaimKind.ROUTE and not c.retracted:
            # The Composer keys routes by `scope.route`. Without this the route
            # is registered under its heading text while every cell in the
            # block points at the block number, and composition dies with
            # "trip '1' references unknown route '1'" — one identifier, two
            # namespaces. The block number IS the route key.
            y = _centre_y(c)
            b = block_for(c, y) if y is not None else None
            scope = dict(c.scope)
            scope.setdefault("route", (b.key if b else _trip_key(c)) or c.claim_id)
            bound.append(rebuild(c, scope))
            continue
        if c.kind not in (ClaimKind.STOP, ClaimKind.STOP_TIME) or c.retracted:
            bound.append(c)
            continue
        y = _centre_y(c)
        if y is None:
            unplaced.append(c.claim_id)
            bound.append(c)
            continue
        b = block_for(c, y)
        if b is None:
            unplaced.append(c.claim_id)
            bound.append(c)
            continue

        info = per_block[b.key]
        rows: list[float] = info["rows"]
        row_stops: list[SourceClaim] = info["row_stops"]
        scope = dict(c.scope)
        if not scope.get("trip"):
            scope["trip"] = b.key
            filled["trip"] += 1
        scope.setdefault("route", b.key)

        if c.kind is ClaimKind.STOP and c.field == "stop_name":
            # Rank order within the block, not a coordinate band.
            ri = next((i for i, s in enumerate(row_stops)
                       if s.claim_id == c.claim_id), 0)
            scope.setdefault("_row", ri)
            scope.setdefault("seq", ri + 1)
            bound.append(rebuild(c, scope))
            continue

        # Everything else on the row — a km cell or a timetable cell — is
        # matched to the nearest stop row IN THIS SAME READ, so the reader's
        # own coordinate drift cancels instead of being compared across models.
        ri = _nearest(rows, y) if rows else 0
        scope.setdefault("_row", ri)

        if c.kind is ClaimKind.STOP:                       # a km cell
            scope.setdefault("seq", ri + 1)
            bound.append(rebuild(c, scope))
            continue

        if row_stops and not scope.get("stop"):
            scope["stop"] = str(row_stops[ri].value)
            filled["stop"] += 1
        if scope.get("seq") is None:
            scope["seq"] = ri + 1
            filled["seq"] += 1

        row_km = None
        for k in info["kms"]:
            ky = _centre_y(k)
            if ky is not None and rows and _nearest(rows, ky) == ri:
                row_km = k
                break
        if row_km is not None and scope.get("km") is None:
            scope["km"] = str(row_km.value)
            filled["km"] += 1

        fld = c.field.strip().lower()
        x = _centre_x(c)
        if x is not None and col_centres:
            geometric = col_field.get(_nearest(col_centres, x))
            if geometric and fld not in (ARRIVAL, DEPARTURE):
                fld = geometric
                filled["field"] += 1
        bound.append(rebuild(c, scope, fld))

    result = ClaimSet(agency_id=cs.agency_id, claims=bound)
    _mark_truncation(result, blocks, per_block)

    report = {
        "blocks": [b.as_dict() for b in blocks],
        "columns_detected": len(col_centres),
        "column_roles": {str(k): v for k, v in sorted(col_field.items())},
        "column_dissent": dissent,
        "filled": filled,
        "claims_without_geometry": unplaced,
        "truncated_trips": [b.key for b in blocks if b.truncated],
    }
    return result, report


def _mark_truncation(cs: ClaimSet, blocks: list[Block],
                     per_block: dict[str, dict[str, Any]]) -> None:
    """Decide, per block, whether the run actually ended on this page.

    A complete run ends at a terminus: the last row has an arrival and no
    departure. Anything else means the table continued past the page edge.
    """
    by_trip: dict[str, list[SourceClaim]] = {}
    for c in cs.active():
        if c.kind is ClaimKind.STOP_TIME:
            by_trip.setdefault(str(c.scope.get("trip") or ""), []).append(c)

    for b in blocks:
        cells = by_trip.get(b.key, [])
        b.rows = [{"seq": c.scope.get("seq"), "field": c.field,
                   "value": str(c.value)} for c in cells]
        if not cells:
            b.truncated = True
            b.truncation_reason = "no timetable cells were bound to this block"
            continue

        last_seq = max(int(c.scope.get("seq") or 0) for c in cells)
        last_row = [c for c in cells if int(c.scope.get("seq") or 0) == last_seq]
        fields = {c.field.strip().lower() for c in last_row}
        last_y = max((_centre_y(c) or 0.0) for c in last_row)

        if fields == {ARRIVAL}:
            continue                                   # a proper terminus row

        if last_y >= PAGE_BOTTOM or DEPARTURE in fields:
            b.truncated = True
            b.truncation_reason = (
                f"the last bound row (seq {last_seq}) has a departure time, so "
                f"the bus does not terminate there — this service continues "
                f"past the bottom of the page and was NOT composed")
        else:
            b.truncated = True
            b.truncation_reason = (
                f"the last bound row (seq {last_seq}) carries neither a clean "
                f"arrival-only terminus nor a departure; the block could not "
                f"be shown to be complete")


def withhold_truncated(cs: ClaimSet, report: dict[str, Any]) -> tuple[ClaimSet,
                                                                     list[str]]:
    """Retract every claim belonging to a block that ran off the page.

    Retraction, not deletion: the claims stay in the set carrying the reason,
    so the ledger can show exactly what was withheld and why.
    """
    truncated = {str(k) for k in report.get("truncated_trips", [])}
    if not truncated:
        return cs, []

    reasons = {str(b["trip"]): str(b.get("reason", ""))
               for b in report.get("blocks", [])}
    out: list[SourceClaim] = []
    withheld: list[str] = []
    for c in cs.claims:
        tkey = str(c.scope.get("trip") or "")
        if tkey in truncated and c.kind in (ClaimKind.STOP_TIME, ClaimKind.ROUTE,
                                            ClaimKind.TRIP):
            withheld.append(c.claim_id)
            out.append(SourceClaim(
                claim_id=c.claim_id, kind=c.kind, field=c.field, value=c.value,
                confidence=c.confidence, provenance=c.provenance,
                alternatives=list(c.alternatives), scope=dict(c.scope),
                retracted=True,
                retraction_reason=reasons.get(tkey, "block truncated by the "
                                                    "page boundary")))
        else:
            out.append(c)
    return ClaimSet(agency_id=cs.agency_id, claims=out), withheld


def rebind_claim_ids(cs: ClaimSet) -> ClaimSet:
    """Re-mint ids from the recovered binding so two readers can be compared.

    This is load-bearing for the disagreement gate. Ids minted before binding
    fall back on ENUMERATION ORDER to break ties, so the same cell read by two
    models can end up with different ids and the gate compares nothing at all.
    After binding, an id is a pure function of (kind, trip, stop, seq, field) —
    order-independent, and therefore actually comparable.
    """
    def slug(text: Any) -> str:
        return "".join(ch if ch.isalnum() else "-"
                       for ch in str(text)).strip("-").lower()

    out: list[SourceClaim] = []
    seen: dict[str, int] = {}
    for c in cs.claims:
        parts = [c.kind.value]
        for key in ("route", "trip", "stop", "service"):
            v = c.scope.get(key)
            if v:
                parts.append(slug(v))
        if c.scope.get("seq") is not None:
            parts.append(f"s{c.scope['seq']}")
        if c.field:
            parts.append(slug(c.field))
        base = "_".join(p for p in parts if p)
        seen[base] = seen.get(base, 0) + 1
        cid = base if seen[base] == 1 else f"{base}_{seen[base]}"
        out.append(SourceClaim(
            claim_id=cid, kind=c.kind, field=c.field, value=c.value,
            confidence=c.confidence, provenance=c.provenance,
            alternatives=list(c.alternatives), scope=dict(c.scope),
            retracted=c.retracted, retraction_reason=c.retraction_reason))
    return ClaimSet(agency_id=cs.agency_id, claims=out)
