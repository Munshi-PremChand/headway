"""Joining a service across a page break, and refusing to when it is not one.

A refused join costs one service. A wrong join invents a bus route that nobody
operates and that no validator would question, so every refusal path here is
driven explicitly.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from headway.geo.plausibility import MAX_PLAUSIBLE_KPH, implied_speed  # noqa: E402
from headway.reader.stitch import (  # noqa: E402
    CONTINUATION, check_join, merge_pages, stitch,
)
from headway.schema.claims import (  # noqa: E402
    ClaimKind, ClaimSet, Provenance, SourceClaim,
)


def cell(cid, kind, field, value, *, trip, seq, y=0.5, x=0.5):
    return SourceClaim(
        claim_id=cid, kind=ClaimKind(kind), field=field, value=value,
        confidence=1.0,
        provenance=Provenance(source_file="p.pdf", page=1,
                              bbox=(x - .04, y - .006, x + .04, y + .006)),
        scope={"trip": trip, "seq": seq})


def rows_to_claims(rows, trip, start_id=0):
    out = []
    for i, r in enumerate(rows, start=1):
        n = start_id + i
        out.append(cell(f"s{n}", "stop", "stop_name", r["stop"], trip=trip, seq=i))
        out.append(cell(f"n{n}", "stop", "sl_no", str(r["sl_no"]), trip=trip, seq=i))
        out.append(cell(f"k{n}", "stop", "km", str(r["km"]), trip=trip, seq=i))
        if r.get("arrival"):
            out.append(cell(f"a{n}", "stop_time", "arrival", r["arrival"],
                            trip=trip, seq=i))
        if r.get("departure"):
            out.append(cell(f"d{n}", "stop_time", "departure", r["departure"],
                            trip=trip, seq=i))
    return out


TAIL = [{"sl_no": 5, "stop": "Balipara", "km": 213, "arrival": "12.35 PM",
         "departure": "12.40 PM"},
        {"sl_no": 6, "stop": "Jamugurihat", "km": 225, "arrival": "1.00 PM",
         "departure": "1.05 PM"}]
HEAD = [{"sl_no": 7, "stop": "Biswanath Chariali", "km": 248,
         "arrival": "1.35 PM", "departure": "1.40 PM"},
        {"sl_no": 8, "stop": "Bihpuria", "km": 369, "arrival": "4.40 PM"}]


def pages(tail=TAIL, head=HEAD, tail_trip="3"):
    p1 = ClaimSet(agency_id="X", claims=rows_to_claims(tail, tail_trip))
    p2 = ClaimSet(agency_id="X",
                  claims=rows_to_claims(head, CONTINUATION, start_id=100))
    return [(1, p1), (2, p2)]


def as_rows(rows):
    return {i + 1: r for i, r in enumerate(rows)}


# --------------------------------------------------------------- accepting

def test_a_real_continuation_is_joined():
    _out, joins = stitch(pages())
    assert len(joins) == 1
    assert joins[0].accepted is True
    assert joins[0].rows_added == 2
    assert joins[0].trip == "3"


def test_the_joined_rows_continue_the_sequence():
    out, _ = stitch(pages())
    merged = merge_pages(out, "X")
    seqs = sorted(int(c.scope["seq"]) for c in merged.claims
                  if c.kind is ClaimKind.STOP and c.field == "stop_name")
    assert seqs == [1, 2, 3, 4]


def test_the_joined_rows_take_the_tail_trip():
    out, _ = stitch(pages())
    merged = merge_pages(out, "X")
    assert {str(c.scope["trip"]) for c in merged.claims} == {"3"}


def test_the_join_records_which_page_each_row_came_from():
    out, _ = stitch(pages())
    merged = merge_pages(out, "X")
    joined = [c for c in merged.claims if c.scope.get("joined_from_page")]
    assert joined and all(c.scope["joined_from_page"] == 2 for c in joined)


# ---------------------------------------------------------------- refusing

def test_a_broken_row_number_refuses_the_join():
    """The decisive check: page ends at 6, next page must start at 7."""
    bad = [dict(HEAD[0], sl_no=9), HEAD[1]]
    ok, _checks, why = check_join(as_rows(TAIL), as_rows(bad))
    assert not ok
    assert "row numbers do not continue" in why


def test_a_distance_that_restarts_refuses_the_join():
    """A continuation that begins at km 0 is a different service."""
    bad = [dict(HEAD[0], km=0), HEAD[1]]
    ok, _c, why = check_join(as_rows(TAIL), as_rows(bad))
    assert not ok
    assert "distance does not increase" in why


def test_time_running_backwards_refuses_the_join():
    bad = [dict(HEAD[0], arrival="9.00 AM"), HEAD[1]]
    ok, _c, why = check_join(as_rows(TAIL), as_rows(bad))
    assert not ok
    assert "time runs backwards" in why


def test_a_continuation_that_does_not_terminate_refuses_the_join():
    """If the next page also runs out, the run is still unfinished."""
    bad = [HEAD[0], dict(HEAD[1], departure="4.45 PM")]
    ok, _c, why = check_join(as_rows(TAIL), as_rows(bad))
    assert not ok
    assert "does not terminate" in why


def test_a_refused_join_leaves_the_orphan_rows_unattached():
    bad_head = [dict(HEAD[0], sl_no=9), HEAD[1]]
    out, joins = stitch(pages(head=bad_head))
    assert joins[0].accepted is False
    merged = merge_pages(out, "X")
    assert any(str(c.scope.get("trip")) == CONTINUATION for c in merged.claims)


def test_no_continuation_means_no_join_attempt():
    p1 = ClaimSet(agency_id="X", claims=rows_to_claims(TAIL, "3"))
    p2 = ClaimSet(agency_id="X", claims=rows_to_claims(HEAD, "4", start_id=100))
    _out, joins = stitch([(1, p1), (2, p2)])
    assert joins == []


def test_an_unreadable_row_number_refuses_rather_than_assumes():
    bad = [dict(HEAD[0], sl_no="?"), HEAD[1]]
    ok, _c, why = check_join(as_rows(TAIL), as_rows(bad))
    assert not ok
    assert "not both readable" in why


# ------------------------------------------------- the page checked against itself

def _speed_rows(pairs):
    """pairs: (stop, km, arrival_s, departure_s)"""
    return [{"stop": s, "km": k, "arrival_s": a, "departure_s": d}
            for s, k, a, d in pairs]


def test_an_impossible_printed_speed_is_reported():
    """ASTC page 2, service 6: 18 km in 5 minutes, by the page's own numbers."""
    rows = _speed_rows([("Balipara", 36, None, 7 * 3600 + 20 * 60),
                        ("Tezpur", 54, 7 * 3600 + 25 * 60, None)])
    out = implied_speed(rows)
    assert len(out) == 1
    assert out[0]["kph"] > 200
    assert out[0]["from"] == "Balipara" and out[0]["to"] == "Tezpur"


def test_times_that_do_not_advance_are_reported():
    """ASTC page 2, service 6: departs 12.40 PM, arrives 12.15 PM."""
    rows = _speed_rows([("Khanapara", 238, None, 12 * 3600 + 40 * 60),
                        ("Paltanbazar", 248, 12 * 3600 + 15 * 60, None)])
    out = implied_speed(rows)
    assert len(out) == 1
    assert out[0]["kph"] is None
    assert "do not advance" in out[0]["why"]


def test_an_ordinary_leg_is_not_reported():
    rows = _speed_rows([("A", 0, None, 7 * 3600),
                        ("B", 40, 8 * 3600, None)])          # 40 km/h
    assert implied_speed(rows) == []


def test_the_speed_bar_is_generous_enough_not_to_flag_a_fast_coach():
    rows = _speed_rows([("A", 0, None, 7 * 3600),
                        ("B", 90, 8 * 3600, None)])          # 90 km/h
    assert implied_speed(rows) == []
    assert MAX_PLAUSIBLE_KPH >= 100


def test_rows_without_a_printed_distance_are_skipped_not_assumed():
    rows = _speed_rows([("A", None, None, 7 * 3600),
                        ("B", 90, 7 * 3600 + 60, None)])
    assert implied_speed(rows) == []
