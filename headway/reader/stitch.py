"""Join a service that runs off one page to its continuation on the next. NO MODEL.

Page 1 of the ASTC Guwahati timetable holds three services and the third does
not finish:

    page 1 ...  6  Jamugurihat          225   1.00 PM   1.05 PM   <- runs off
    page 2      7  Biswanath Chariali   248   1.35 PM   1.40 PM   <- no heading
                8  Gohpur               308   3.10 PM   3.15 PM
                9  Narayanpur           354   4.25 PM   4.30 PM
               10  Bihpuria             369   4.40 PM             <- terminus

Until now that service was withheld, which was correct but lossy: a real 369 km
run was dropped because the paper ran out. Joining it back is the obvious win,
and it is also the obvious place to publish something wrong — a bad join invents
a bus route that nobody operates, and no validator on earth would notice.

So a join is treated as a CLAIM, and this page format happens to make it
checkable four separate ways:

  1. **The printed row numbers continue.** Page 1 ends at Sl.No 6, page 2 opens
     at 7. This is the decisive one, and it is why the reader is asked for the
     Sl.No column even though within a page the sequence is recoverable from
     geometry — ACROSS pages it is not.
  2. **The distance column increases.** 225 km then 248 km. A continuation that
     restarts at 0 is a new service, not a continuation.
  3. **Time does not run backwards.** 1.05 PM then 1.35 PM.
  4. **The joined run terminates properly** — the last row has an arrival and no
     departure, which is what the end of a run looks like.

All four must pass. Any failure and the join is refused, the service stays
withheld, and the ledger names the check that failed. Refusing to join costs one
service; joining wrongly costs a fabricated timetable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from headway.composer.compose import ComposeError, parse_hhmm
from headway.schema.claims import ClaimKind, ClaimSet, SourceClaim

CONTINUATION = "continuation"


@dataclass
class Join:
    """One attempted join between a page's tail and the next page's head."""
    from_page: int
    to_page: int
    trip: str
    accepted: bool = False
    checks: dict[str, Any] = field(default_factory=dict)
    refused_because: str = ""
    rows_added: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "from_page": self.from_page, "to_page": self.to_page,
            "trip": self.trip, "accepted": self.accepted,
            "checks": self.checks, "rows_added": self.rows_added,
            "refused_because": self.refused_because,
        }


def _rows(cs: ClaimSet, trip: str) -> dict[int, dict[str, Any]]:
    """Collapse one trip's claims into {seq: {sl_no, stop, km, arrival, departure}}."""
    out: dict[int, dict[str, Any]] = {}
    for c in cs.claims:
        if str(c.scope.get("trip") or "") != trip:
            continue
        seq = c.scope.get("seq")
        if seq is None:
            continue
        row = out.setdefault(int(seq), {})
        if c.kind is ClaimKind.STOP and c.field == "stop_name":
            row["stop"] = str(c.value)
        elif c.kind is ClaimKind.STOP and c.field == "sl_no":
            row["sl_no"] = str(c.value)
        elif c.kind is ClaimKind.STOP and c.field == "km":
            row["km"] = str(c.value)
        elif c.kind is ClaimKind.STOP_TIME:
            row[c.field] = str(c.value)
    return out


def _int(v: Any) -> int | None:
    try:
        return int("".join(ch for ch in str(v) if ch.isdigit()))
    except (TypeError, ValueError):
        return None


def _secs(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return parse_hhmm(v)
    except ComposeError:
        return None


def check_join(tail: dict[int, dict], head: dict[int, dict]) -> tuple[bool, dict, str]:
    """Decide whether `head` really continues `tail`. All four checks or none."""
    if not tail or not head:
        return False, {}, "one side of the join is empty"

    last = tail[max(tail)]
    first = head[min(head)]
    checks: dict[str, Any] = {}

    # 1. printed row numbers
    a, b = _int(last.get("sl_no")), _int(first.get("sl_no"))
    checks["sl_no"] = {"tail": a, "head": b, "expected": None if a is None else a + 1}
    if a is None or b is None:
        return False, checks, "the printed row numbers were not both readable"
    if b != a + 1:
        return False, checks, (f"the printed row numbers do not continue: page "
                               f"ends at {a}, next page starts at {b}")

    # 2. distance
    ka, kb = _int(last.get("km")), _int(first.get("km"))
    checks["km"] = {"tail": ka, "head": kb}
    if ka is None or kb is None:
        return False, checks, "the km column was not readable on both sides"
    if kb <= ka:
        return False, checks, (f"distance does not increase across the join "
                               f"({ka} km then {kb} km) — this is a new service, "
                               f"not a continuation")

    # 3. time
    ta = _secs(last.get("departure") or last.get("arrival"))
    tb = _secs(first.get("arrival") or first.get("departure"))
    checks["time"] = {"tail": last.get("departure") or last.get("arrival"),
                      "head": first.get("arrival") or first.get("departure")}
    if ta is None or tb is None:
        return False, checks, "the times were not readable on both sides"
    if tb < ta:
        return False, checks, (f"time runs backwards across the join "
                               f"({checks['time']['tail']} then "
                               f"{checks['time']['head']})")

    # 4. the joined run actually ends
    end = head[max(head)]
    checks["terminates"] = {"last_row": end.get("stop"),
                            "has_departure": "departure" in end}
    if "departure" in end:
        return False, checks, ("the continuation does not terminate either — its "
                               "last row still has a departure time, so the run "
                               "carries on past this page too")

    return True, checks, ""


def continuation_trip(cs: ClaimSet) -> str | None:
    """Is there a headless group at the top of this page?"""
    for c in cs.claims:
        if str(c.scope.get("trip") or "") == CONTINUATION:
            return CONTINUATION
    return None


def stitch(pages: list[tuple[int, ClaimSet]]) -> tuple[list[tuple[int, ClaimSet]],
                                                       list[Join]]:
    """Attempt a join at every page seam. Returns the pages and what was decided.

    Accepted joins move the continuation's claims onto the truncated trip, with
    their sequence continued past the tail's last row. Refused joins leave both
    sides exactly as they were, so the truncated service stays withheld and the
    orphan rows stay unattached to anything.
    """
    joins: list[Join] = []
    out = [(n, cs) for n, cs in pages]

    for i in range(len(out) - 1):
        pn, tail_cs = out[i]
        qn, head_cs = out[i + 1]
        if continuation_trip(head_cs) is None:
            continue

        # The tail is the LAST trip on the earlier page, by highest sequence.
        trips = {str(c.scope.get("trip") or "") for c in tail_cs.claims
                 if c.scope.get("trip") not in (None, "", CONTINUATION)}
        if not trips:
            continue
        tail_trip = sorted(trips, key=lambda t: _int(t) or 0)[-1]

        tail_rows = _rows(tail_cs, tail_trip)
        head_rows = _rows(head_cs, CONTINUATION)
        ok, checks, why = check_join(tail_rows, head_rows)
        j = Join(from_page=pn, to_page=qn, trip=tail_trip, accepted=ok,
                 checks=checks, refused_because=why)

        if ok:
            offset = max(tail_rows)
            moved: list[SourceClaim] = []
            for c in head_cs.claims:
                if str(c.scope.get("trip") or "") == CONTINUATION:
                    scope = dict(c.scope)
                    scope["trip"] = tail_trip
                    scope["route"] = tail_trip
                    scope["seq"] = int(scope.get("seq") or 0) + offset
                    scope["joined_from_page"] = qn
                    c = SourceClaim(
                        claim_id=f"p{qn}_{c.claim_id}", kind=c.kind,
                        field=c.field, value=c.value, confidence=c.confidence,
                        provenance=c.provenance,
                        alternatives=list(c.alternatives), scope=scope,
                        retracted=False, retraction_reason="")
                moved.append(c)
            out[i + 1] = (qn, ClaimSet(agency_id=head_cs.agency_id, claims=moved))
            j.rows_added = len(head_rows)
        joins.append(j)

    return out, joins


def merge_pages(pages: list[tuple[int, ClaimSet]], agency_id: str) -> ClaimSet:
    """Flatten stitched pages into one claim set, keeping ids unique per page."""
    claims: list[SourceClaim] = []
    seen: set[str] = set()
    for n, cs in pages:
        for c in cs.claims:
            cid = c.claim_id if c.claim_id not in seen else f"p{n}_{c.claim_id}"
            seen.add(cid)
            scope = dict(c.scope)
            scope.setdefault("page", n)
            claims.append(SourceClaim(
                claim_id=cid, kind=c.kind, field=c.field, value=c.value,
                confidence=c.confidence, provenance=c.provenance,
                alternatives=list(c.alternatives), scope=scope,
                retracted=c.retracted, retraction_reason=c.retraction_reason))
    return ClaimSet(agency_id=agency_id, claims=claims)
