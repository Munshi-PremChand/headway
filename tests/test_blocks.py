"""Binding a service-block page from geometry. No network, no model.

Every test here encodes a failure that actually happened on the real ASTC page
on 2026-08-27. They are regression tests in the strict sense: each one failed
before the fix it guards.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from headway.reader.blocks import (  # noqa: E402
    bind_blocks, rebind_claim_ids, withhold_truncated,
)
from headway.schema.claims import (  # noqa: E402
    ClaimKind, ClaimSet, Provenance, SourceClaim,
)


def claim(cid, kind, field, value, *, y, x=0.5, h=0.012, w=0.08, trip="1",
          **scope):
    return SourceClaim(
        claim_id=cid, kind=ClaimKind(kind), field=field, value=value,
        confidence=1.0,
        provenance=Provenance(source_file="p.pdf", page=1,
                              bbox=(x - w / 2, y - h / 2, x + w / 2, y + h / 2)),
        scope={"trip": trip, **scope})


def block(trip, heading_y, stops, *, x_stop=0.19, x_arr=0.53, x_dep=0.66,
          pitch=0.019, terminus=True):
    """One synthetic service block: heading, stop names, km, arrivals, departures."""
    out = [claim(f"r{trip}", "route", "route_long_name", f"Service {trip}",
                 y=heading_y, x=0.42, w=0.38, trip=trip)]
    for i, (name, km, arr, dep) in enumerate(stops):
        y = heading_y + 0.06 + i * pitch
        out.append(claim(f"s{trip}_{i}", "stop", "stop_name", name,
                         y=y, x=x_stop, trip=trip))
        out.append(claim(f"k{trip}_{i}", "stop", "km", str(km),
                         y=y, x=0.39, w=0.03, trip=trip))
        if arr is not None:
            out.append(claim(f"a{trip}_{i}", "stop_time", "arrival", arr,
                             y=y, x=x_arr, trip=trip))
        if dep is not None:
            out.append(claim(f"d{trip}_{i}", "stop_time", "departure", dep,
                             y=y, x=x_dep, trip=trip))
    return out


COMPLETE = [("Alpha", 0, None, "7.15 AM"), ("Beta", 10, "7.30 AM", "7.35 AM"),
            ("Gamma", 40, "8.10 AM", "8.15 AM"), ("Delta", 60, "8.45 AM", None)]
CUT_OFF = [("Alpha", 0, None, "9.15 AM"), ("Beta", 10, "9.30 AM", "9.35 AM"),
           ("Gamma", 40, "10.10 AM", "10.15 AM")]


def cs(*groups):
    claims = [c for g in groups for c in g]
    return ClaimSet(agency_id="X", claims=claims)


# ------------------------------------------------------------------- binding

def test_rows_and_columns_are_recovered_from_geometry():
    bound, rep = bind_blocks(cs(block("1", 0.10, COMPLETE)))
    cells = [c for c in bound.active() if c.kind is ClaimKind.STOP_TIME]
    assert {c.scope["stop"] for c in cells} == {"Alpha", "Beta", "Gamma", "Delta"}
    assert rep["column_roles"] == {"0": "arrival", "1": "departure"}
    assert rep["column_dissent"] == []


def test_sequence_follows_the_printed_order():
    bound, _ = bind_blocks(cs(block("1", 0.10, COMPLETE)))
    got = {c.scope["seq"]: c.scope["stop"] for c in bound.active()
           if c.kind is ClaimKind.STOP_TIME}
    assert got[1] == "Alpha" and got[4] == "Delta"


def test_km_column_is_carried_onto_the_cell():
    bound, _ = bind_blocks(cs(block("1", 0.10, COMPLETE)))
    cells = {c.scope["stop"]: c.scope.get("km") for c in bound.active()
             if c.kind is ClaimKind.STOP_TIME}
    assert cells["Gamma"] == "40"


def test_two_blocks_do_not_bleed_into_each_other():
    bound, rep = bind_blocks(cs(block("1", 0.05, COMPLETE),
                                block("2", 0.50, COMPLETE)))
    assert [b["trip"] for b in rep["blocks"]] == ["1", "2"]
    for c in bound.active():
        if c.kind is ClaimKind.STOP_TIME:
            assert c.scope["trip"] in ("1", "2")


# --------------------------------------------------------------- truncation

def test_a_block_ending_in_a_terminus_row_is_complete():
    _bound, rep = bind_blocks(cs(block("1", 0.10, COMPLETE)))
    assert rep["truncated_trips"] == []


def test_a_block_whose_last_row_still_departs_is_withheld():
    """The real defect: page 1's third service runs off the bottom edge."""
    _bound, rep = bind_blocks(cs(block("3", 0.60, CUT_OFF)))
    assert rep["truncated_trips"] == ["3"]
    assert "continues past the bottom of the page" in rep["blocks"][0]["reason"]


def test_withholding_retracts_the_claims_and_keeps_the_reason():
    bound, rep = bind_blocks(cs(block("1", 0.05, COMPLETE),
                                block("3", 0.60, CUT_OFF)))
    bound, withheld = withhold_truncated(bound, rep)
    assert withheld
    live = {c.scope.get("trip") for c in bound.active()
            if c.kind is ClaimKind.STOP_TIME}
    assert live == {"1"}
    dead = [c for c in bound.claims if c.retracted]
    assert dead and all(c.retraction_reason for c in dead)


# ----------------------------------------------- robustness across two reads

def test_absolute_coordinate_drift_does_not_change_the_binding():
    """The two readers disagree about coordinates by up to two row heights.

    Binding by nearest coordinate band turned that into a dozen phantom
    disagreements per run. Rank order must be immune to it.
    """
    tight = cs(block("1", 0.10, COMPLETE, pitch=0.019))
    stretched = cs(block("1", 0.10, COMPLETE, pitch=0.026))

    def fingerprint(claims):
        b, rep = bind_blocks(claims)
        b, _ = withhold_truncated(b, rep)
        return {c.claim_id: str(c.value) for c in rebind_claim_ids(b).active()}

    a, b = fingerprint(tight), fingerprint(stretched)
    assert set(a) == set(b), "claim ids must not depend on absolute coordinates"
    assert a == b


def test_a_malformed_heading_box_does_not_swallow_its_own_block():
    """flash-lite returned a heading box spanning a third of the page.

    Its centre landed below eight of its own stops, which dropped them from
    the binding entirely. Block boundaries use the heading's TOP edge.
    """
    claims = block("1", 0.10, COMPLETE)
    bad = claims[0]
    claims[0] = SourceClaim(
        claim_id=bad.claim_id, kind=bad.kind, field=bad.field, value=bad.value,
        confidence=1.0,
        provenance=Provenance(source_file="p.pdf", page=1,
                              bbox=(0.20, 0.10, 0.24, 0.62)),
        scope=dict(bad.scope))
    bound, _ = bind_blocks(ClaimSet(agency_id="X", claims=claims))
    placed = [c for c in bound.active() if c.kind is ClaimKind.STOP_TIME]
    assert len(placed) == 6
    assert all(c.scope.get("seq") is not None for c in placed)


def test_block_membership_follows_the_printed_number_not_the_heading_order():
    """One misplaced heading must not move a whole block into its neighbour."""
    claims = block("1", 0.05, COMPLETE) + block("2", 0.50, COMPLETE)
    # Put block 2's heading box at the very top of the page, out of order.
    for i, c in enumerate(claims):
        if c.claim_id == "r2":
            claims[i] = SourceClaim(
                claim_id=c.claim_id, kind=c.kind, field=c.field, value=c.value,
                confidence=1.0,
                provenance=Provenance(source_file="p.pdf", page=1,
                                      bbox=(0.2, 0.01, 0.6, 0.02)),
                scope=dict(c.scope))
    bound, _ = bind_blocks(ClaimSet(agency_id="X", claims=claims))
    for c in bound.active():
        if c.kind is ClaimKind.STOP_TIME:
            assert c.scope["route"] == c.scope["trip"]


# --------------------------------------------------------------------- ids

def test_ids_distinguish_arrival_from_departure_at_the_same_stop():
    bound, _ = bind_blocks(cs(block("1", 0.10, COMPLETE)))
    ids = [c.claim_id for c in rebind_claim_ids(bound).active()]
    assert len(ids) == len(set(ids)), "ids must be unique"
    assert any(i.endswith("_arrival") for i in ids)
    assert any(i.endswith("_departure") for i in ids)


def test_a_cell_that_dissents_from_its_column_is_reported():
    claims = block("1", 0.10, COMPLETE)
    for i, c in enumerate(claims):
        if c.claim_id == "a1_2":                 # sits in the arrival column
            claims[i] = SourceClaim(
                claim_id=c.claim_id, kind=c.kind, field="departure",
                value=c.value, confidence=1.0, provenance=c.provenance,
                scope=dict(c.scope))
    _bound, rep = bind_blocks(ClaimSet(agency_id="X", claims=claims))
    assert len(rep["column_dissent"]) == 1
    assert "sits in the 'arrival' column" in rep["column_dissent"][0]["reason"]


@pytest.mark.parametrize("kind", ["stop_time", "stop"])
def test_a_claim_with_no_bbox_is_reported_not_placed(kind):
    claims = block("1", 0.10, COMPLETE)
    claims.append(SourceClaim(
        claim_id="ghost", kind=ClaimKind(kind), field="departure",
        value="9.00 AM", confidence=1.0,
        provenance=Provenance(source_file="p.pdf", page=1, bbox=None),
        scope={"trip": "1"}))
    _bound, rep = bind_blocks(ClaimSet(agency_id="X", claims=claims))
    assert "ghost" in rep["claims_without_geometry"]


# ------------------------------------------------------------ page skew

def skewed(trip, heading_y, stops, slope):
    """A block where each column is displaced vertically by its x position.

    That is what page skew does: rotate a page and a column's apparent row
    height shifts in proportion to how far across the page it sits.
    """
    out = block(trip, heading_y, stops)
    shifted = []
    for c in out:
        bb = c.provenance.bbox
        x = (bb[0] + bb[2]) / 2
        dy = slope * (x - 0.19)          # 0.19 is the stop column
        shifted.append(SourceClaim(
            claim_id=c.claim_id, kind=c.kind, field=c.field, value=c.value,
            confidence=c.confidence,
            provenance=Provenance(source_file="p.pdf", page=1,
                                  bbox=(bb[0], bb[1] + dy, bb[2], bb[3] + dy)),
            scope=dict(c.scope)))
    return shifted


LONG = [(f"Stop{i}", i * 30, None if i == 1 else f"{6+i}.10 AM",
         None if i == 8 else f"{6+i}.15 AM") for i in range(1, 9)]


def test_a_skewed_page_does_not_shift_a_whole_column_by_one_row():
    """The failure this caught on a real degraded scan.

    At 2 degrees of skew the departure column — furthest from the centre of
    rotation — was displaced by nearly a full row height. Nearest-row matching
    put every departure one row too high, producing 18 confidently wrong
    departure times with ZERO abstentions: a feed that validates clean and
    tells riders the wrong time at every stop.
    """
    clean, _ = bind_blocks(cs(block("1", 0.05, LONG)))
    skew, rep = bind_blocks(ClaimSet(agency_id="X",
                                     claims=skewed("1", 0.05, LONG, 0.045)))

    def pairs(b):
        return {(c.scope["seq"], c.field): str(c.value) for c in b.active()
                if c.kind is ClaimKind.STOP_TIME}

    assert pairs(skew) == pairs(clean), "skew must not re-index a column"
    assert rep["skew_per_block"]["1"] > 0, "the skew should be measured, not ignored"


def test_the_measured_skew_grows_with_the_actual_skew():
    _b, mild = bind_blocks(ClaimSet(agency_id="X",
                                    claims=skewed("1", 0.05, LONG, 0.02)))
    _b2, harsh = bind_blocks(ClaimSet(agency_id="X",
                                      claims=skewed("1", 0.05, LONG, 0.06)))
    assert harsh["skew_per_block"]["1"] > mild["skew_per_block"]["1"]


def test_an_unskewed_page_measures_no_meaningful_skew():
    _b, rep = bind_blocks(cs(block("1", 0.05, LONG)))
    assert abs(rep["skew_per_block"]["1"]) < 0.005


def test_monotonic_alignment_never_maps_two_cells_to_one_row():
    from headway.reader.blocks import align_monotonic
    rows = [0.10, 0.12, 0.14, 0.16, 0.18]
    got = align_monotonic([0.101, 0.121, 0.141], rows)
    assert got == [0, 1, 2]
    assert len(set(got)) == len(got)


def test_monotonic_alignment_keeps_order_when_cells_are_offset():
    from headway.reader.blocks import align_monotonic
    rows = [0.10, 0.12, 0.14, 0.16]
    # every cell nudged toward the next row; order must still be preserved
    got = align_monotonic([0.109, 0.129, 0.149], rows)
    assert got == sorted(got) and len(set(got)) == 3
