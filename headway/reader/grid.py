"""Reconstruct the timetable grid from bounding-box geometry. NO MODEL.

A printed timetable is a matrix: stops down the rows, trips across the
columns. The Reader is good at reading a cell and locating it on the page; it
is unreliable at bookkeeping which row-and-column index that cell occupies,
and asking it to do so measurably degrades the response (see CHANGELOG
2026-08-27).

So the division of labour is:

    model  ->  "this cell says 06:47, and it sits at this box"
    code   ->  "that box is row 3, column 1, therefore City Hospital on T1"

Row and column assignment is CLUSTERING OVER COORDINATES, which is arithmetic
with a single correct answer. Handing it to a model would be handing away
determinism for nothing. This also means a skewed scan degrades gracefully:
clustering tolerates the drift that exact-coordinate matching would not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from headway.schema.claims import ClaimKind, ClaimSet, SourceClaim


@dataclass(frozen=True)
class Axis:
    """One clustered axis of the grid (rows or columns)."""
    centres: tuple[float, ...]

    def index_of(self, value: float) -> int:
        return min(range(len(self.centres)),
                   key=lambda i: abs(self.centres[i] - value))


def _cluster(values: Sequence[float], tolerance: float) -> Axis:
    """One-dimensional clustering. Values within `tolerance` share a band."""
    if not values:
        return Axis(centres=())
    ordered = sorted(values)
    bands: list[list[float]] = [[ordered[0]]]
    for v in ordered[1:]:
        if v - bands[-1][-1] <= tolerance:
            bands[-1].append(v)
        else:
            bands.append([v])
    return Axis(centres=tuple(sum(b) / len(b) for b in bands))


def _centre(claim: SourceClaim) -> tuple[float, float] | None:
    bb = claim.provenance.bbox
    if not bb:
        return None
    x0, y0, x1, y1 = bb
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


def bind_grid(
    cs: ClaimSet, *, row_tolerance: float = 0.025, col_tolerance: float = 0.04,
) -> tuple[ClaimSet, dict[str, object]]:
    """Fill in scope.stop / scope.seq / scope.trip from geometry.

    Anything already asserted by the model is preserved — this only fills gaps.
    Returns the bound ClaimSet and a report describing what geometry decided,
    so the run ledger can show it rather than hiding it.
    """
    stops = [c for c in cs.active() if c.kind is ClaimKind.STOP]
    cells = [c for c in cs.active() if c.kind is ClaimKind.STOP_TIME]

    stop_rows = [(_centre(c), c) for c in stops]
    stop_rows = [(p[1], c) for p, c in stop_rows if p is not None]
    cell_pts = [(_centre(c), c) for c in cells]
    cell_pts = [(p, c) for p, c in cell_pts if p is not None]

    ungeometried = [c.claim_id for c in cells if _centre(c) is None]

    rows = _cluster([y for y, _ in stop_rows] or [y for (_, y), _ in cell_pts],
                    row_tolerance)
    cols = _cluster([x for (x, _), _ in cell_pts], col_tolerance)

    # Row index -> stop name, from the stop-label column.
    row_to_stop: dict[int, str] = {}
    for y, c in stop_rows:
        row_to_stop[rows.index_of(y)] = str(c.value)

    # Column index -> trip id, taken from whatever the model did assert.
    col_votes: dict[int, dict[str, int]] = {}
    for (x, _y), c in cell_pts:
        trip = c.scope.get("trip")
        if trip:
            col_votes.setdefault(cols.index_of(x), {}).setdefault(str(trip), 0)
            col_votes[cols.index_of(x)][str(trip)] += 1
    col_to_trip = {ci: max(v, key=v.get) for ci, v in col_votes.items()}

    bound: list[SourceClaim] = []
    filled_stop = filled_seq = filled_trip = 0
    for c in cs.claims:
        if c.kind is not ClaimKind.STOP_TIME:
            bound.append(c)
            continue
        pt = _centre(c)
        if pt is None:
            bound.append(c)
            continue
        x, y = pt
        ri, ci = rows.index_of(y), cols.index_of(x)
        scope = dict(c.scope)
        if not scope.get("trip") and ci in col_to_trip:
            scope["trip"] = col_to_trip[ci]
            filled_trip += 1
        if not scope.get("stop") and ri in row_to_stop:
            scope["stop"] = row_to_stop[ri]
            filled_stop += 1
        if scope.get("seq") is None:
            scope["seq"] = ri + 1
            filled_seq += 1
        scope.setdefault("_row", ri)
        scope.setdefault("_col", ci)
        bound.append(SourceClaim(
            claim_id=c.claim_id, kind=c.kind, field=c.field, value=c.value,
            confidence=c.confidence, provenance=c.provenance,
            alternatives=list(c.alternatives), scope=scope,
            retracted=c.retracted, retraction_reason=c.retraction_reason))

    report = {
        "rows_detected": len(rows.centres),
        "cols_detected": len(cols.centres),
        "stops_labelled": len(row_to_stop),
        "trips_labelled": len(col_to_trip),
        "filled_trip": filled_trip,
        "filled_stop": filled_stop,
        "filled_seq": filled_seq,
        "cells_without_geometry": ungeometried,
    }
    return ClaimSet(agency_id=cs.agency_id, claims=bound), report


def rebind_claim_ids(cs: ClaimSet) -> ClaimSet:
    """Re-mint ids now that the binding is known, so they are stable and unique."""
    out: list[SourceClaim] = []
    seen: dict[str, int] = {}
    for c in cs.claims:
        base = c.kind.value
        for key in ("route", "trip", "stop", "service"):
            v = c.scope.get(key)
            if v:
                base += "_" + "".join(
                    ch if ch.isalnum() else "-" for ch in str(v)).strip("-").lower()
        if c.scope.get("seq") is not None:
            base += f"_s{c.scope['seq']}"
        seen[base] = seen.get(base, 0) + 1
        cid = base if seen[base] == 1 else f"{base}_{seen[base]}"
        out.append(SourceClaim(
            claim_id=cid, kind=c.kind, field=c.field, value=c.value,
            confidence=c.confidence, provenance=c.provenance,
            alternatives=list(c.alternatives), scope=dict(c.scope),
            retracted=c.retracted, retraction_reason=c.retraction_reason))
    return ClaimSet(agency_id=cs.agency_id, claims=out)
