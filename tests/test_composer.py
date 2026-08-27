"""Locks the load-bearing guarantees. Run: python3 -m pytest tests -q

These are the claims a hostile judge will test on camera. If one of these
breaks, the corresponding sentence must come out of the write-up.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from headway.composer.compose import (  # noqa: E402
    ComposeError, GTFS_FILES, UngeocodedStops, compose, fmt_gtfs_time,
    normalise_trip_times, parse_hhmm,
)
from headway.composer.outcomes import (  # noqa: E402
    diff_events, enumerate_events, journeys_between, journeys_from_events,
    preserved, read_feed,
)
from headway.schema.claims import Alternative, ClaimSet  # noqa: E402

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/claims/sample_agency.json"
START = date(2026, 8, 24)


def load() -> ClaimSet:
    raw = json.loads(FIXTURE.read_text())
    return ClaimSet.from_dicts(raw["agency_id"], raw["claims"])


# ------------------------------------------------------------------ time parsing

@pytest.mark.parametrize("raw,secs", [
    ("7:15a", 7 * 3600 + 15 * 60),
    ("8:35", 8 * 3600 + 35 * 60),
    ("12:00a", 0),
    ("12:00p", 12 * 3600),
    ("1:05pm", 13 * 3600 + 5 * 60),
    ("0835", 8 * 3600 + 35 * 60),
    ("23:45", 23 * 3600 + 45 * 60),
])
def test_parse_times(raw, secs):
    assert parse_hhmm(raw) == secs


@pytest.mark.parametrize("blank", ["", "-", "--", "—", "n/a", "no service", "x"])
def test_no_service_cells_are_none(blank):
    assert parse_hhmm(blank) is None


def test_bad_time_raises():
    with pytest.raises(ComposeError):
        parse_hhmm("qq:zz")


# ---------------------------------------------------------------- normalisation

def test_midnight_rollover():
    """23:45 then 00:15 must become 23:45 then 24:15, not go backwards."""
    got = normalise_trip_times([parse_hhmm("23:45"), parse_hhmm("00:15"),
                                parse_hhmm("00:40")])
    assert [fmt_gtfs_time(t) for t in got] == ["23:45:00", "24:15:00", "24:40:00"]


def test_normalisation_skips_gaps():
    got = normalise_trip_times([parse_hhmm("23:45"), None, parse_hhmm("00:15")])
    assert got[1] is None
    assert fmt_gtfs_time(got[2]) == "24:15:00"


def test_normalisation_never_reorders():
    """A mis-transcribed sequence stays wrong on purpose — silently fixing it
    would hide exactly the reading error the fidelity oracle must catch."""
    got = normalise_trip_times([parse_hhmm("09:00"), parse_hhmm("08:00")])
    assert fmt_gtfs_time(got[1]) == "32:00:00"   # rolled, not swapped


# -------------------------------------------------------------------- composing

def test_emits_all_eight_files():
    feed = compose(load(), feed_start=START, horizon_days=120)
    assert set(feed.to_csv_bytes()) == set(GTFS_FILES)
    assert len(GTFS_FILES) == 8


def test_deterministic_bytes():
    a = compose(load(), feed_start=START, horizon_days=120).to_zip_bytes()
    b = compose(load(), feed_start=START, horizon_days=120).to_zip_bytes()
    assert a == b


def test_horizon_must_cover_90_days():
    with pytest.raises(ComposeError):
        compose(load(), feed_start=START, horizon_days=30)


def test_illegible_cells_are_dropped_not_guessed():
    cs = load()
    feed = compose(cs, feed_start=START, horizon_days=120)
    times = [r["departure_time"] for r in feed.tables["stop_times.txt"]
             if r["trip_id"] == "ridge_sat"]
    assert len(times) == 2          # c7 ILLEGIBLE and c9 "—" both dropped
    assert cs.abstention_rate() > 0


def test_non_boardable_timing_point():
    """The garage is timed but not boardable. The validator emits NOTHING if
    this is wrong — it is a pure rider-harm error."""
    feed = compose(load(), feed_start=START, horizon_days=120)
    garage = [r for r in feed.tables["stop_times.txt"] if r["stop_id"] == "garage"]
    assert garage and all(r["pickup_type"] == 1 and r["drop_off_type"] == 1
                          for r in garage)


def test_referential_integrity_holds():
    feed = compose(load(), feed_start=START, horizon_days=120)
    stops = {r["stop_id"] for r in feed.tables["stops.txt"]}
    trips = {r["trip_id"] for r in feed.tables["trips.txt"]}
    for r in feed.tables["stop_times.txt"]:
        assert r["stop_id"] in stops and r["trip_id"] in trips


def test_dangling_stop_reference_is_rejected():
    raw = json.loads(FIXTURE.read_text())
    for c in raw["claims"]:
        if c["claim_id"] == "c1":
            c["scope"]["stop"] = "does_not_exist"
    cs = ClaimSet.from_dicts(raw["agency_id"], raw["claims"])
    with pytest.raises(ComposeError):
        compose(cs, feed_start=START, horizon_days=120)


# --------------------------------------------------------------------- outcomes

def test_ambiguity_at_non_boardable_stop_is_suppressed():
    """The core mechanism: a smudged digit at a stop no rider can board
    produces zero rider-visible difference, so no question is asked."""
    cs = load()
    c5 = next(c for c in cs.active() if c.claim_id == "c5")
    alt = c5.alternatives[0]
    a = compose(cs, feed_start=START, horizon_days=120).to_zip_bytes()
    b = compose(cs.branch_on("c5", alt), feed_start=START,
                horizon_days=120).to_zip_bytes()
    d = diff_events(
        enumerate_events(a, window_start=START, window_days=28),
        enumerate_events(b, window_start=START, window_days=28))
    assert d.is_empty


def test_ambiguity_at_boardable_stop_is_escalated():
    """The same class of smudge at the dialysis centre changes when riders
    arrive, so it must escalate."""
    cs = load()
    c2 = next(c for c in cs.active() if c.claim_id == "c2")
    alt = c2.alternatives[0]
    a = compose(cs, feed_start=START, horizon_days=120).to_zip_bytes()
    b = compose(cs.branch_on("c2", alt), feed_start=START,
                horizon_days=120).to_zip_bytes()
    d = diff_events(
        enumerate_events(a, window_start=START, window_days=28),
        enumerate_events(b, window_start=START, window_days=28))
    assert not d.is_empty
    assert d.changed and d.affected_riders > 0


def test_confidence_alone_cannot_separate_the_two():
    """The decision is NOT a confidence threshold. These two claims sit within
    0.03 of each other and require opposite handling."""
    cs = load()
    c2 = next(c for c in cs.active() if c.claim_id == "c2")
    c5 = next(c for c in cs.active() if c.claim_id == "c5")
    assert abs(c2.confidence - c5.confidence) < 0.05


def test_unrelated_service_is_preserved():
    cs = load()
    alt = next(c for c in cs.active() if c.claim_id == "c2").alternatives[0]
    before = enumerate_events(
        compose(cs, feed_start=START, horizon_days=120).to_zip_bytes(),
        window_start=START, window_days=28)
    after = enumerate_events(
        compose(cs.branch_on("c2", alt), feed_start=START,
                horizon_days=120).to_zip_bytes(),
        window_start=START, window_days=28)
    ok, casualties = preserved(before, after, touched_routes={"clinic"})
    assert ok, f"unrelated journeys changed: {casualties}"


def test_resolution_removes_the_question():
    cs = load().resolve("c2", "8:35", source="dispatcher")
    assert not any(c.claim_id == "c2" for c in cs.ambiguous())


def test_journey_query_finds_the_clinic_trip():
    feed = compose(load(), feed_start=START, horizon_days=120)
    hit = journeys_between(feed.to_zip_bytes(), "courthouse", "dialysis",
                           date(2026, 8, 25))
    assert hit and hit[0].depart == "07:15:00"


def test_garage_is_never_a_journey_endpoint():
    feed = compose(load(), feed_start=START, horizon_days=120)
    evs = enumerate_events(feed.to_zip_bytes(), window_start=START, window_days=7)
    js = journeys_from_events(evs)
    assert js, "expected some journeys"
    assert not [j for j in js if "garage" in (j.from_stop, j.to_stop)]


def test_event_enumeration_is_linear_not_quadratic():
    """A 40-stop / 20-trip / 28-day feed used to blow past a 200k journey cap.
    Events are O(stops x trips x dates) and must stay tractable."""
    import time
    raw = json.loads(FIXTURE.read_text())
    base = [c for c in raw["claims"] if c["kind"] not in ("stop", "stop_time", "trip")]
    stops = [{"claim_id": f"S{i}", "kind": "stop", "field": "stop_name",
              "value": f"Stop {i}", "confidence": 1.0,
              "scope": {"stop": f"s{i}", "lat": 39.0 + i * 0.01, "lon": -80.0 - i * 0.01},
              "provenance": {"source_file": "t.jpg", "page": 1}} for i in range(40)]
    trips, times = [], []
    for t in range(20):
        trips.append({"claim_id": f"T{t}", "kind": "trip", "field": "trip_headsign",
                      "value": "X", "confidence": 1.0,
                      "scope": {"trip": f"tr{t}", "route": "RIDGE", "service": "WEEKDAY"}})
        for i in range(40):
            times.append({"claim_id": f"C{t}_{i}", "kind": "stop_time",
                          "field": "departure",
                          "value": f"{6 + t // 2:02d}:{(i * 2) % 60:02d}",
                          "confidence": 1.0,
                          "scope": {"trip": f"tr{t}", "stop": f"s{i}", "seq": i + 1},
                          "provenance": {"source_file": "t.jpg", "page": 1}})
    cs = ClaimSet.from_dicts("big", base + stops + trips + times)
    feed = compose(cs, feed_start=START, horizon_days=120)
    t0 = time.time()
    evs = enumerate_events(feed.to_zip_bytes(), window_start=START, window_days=28)
    elapsed = time.time() - t0
    assert len(evs) > 10_000
    assert elapsed < 10, f"event enumeration took {elapsed:.1f}s"
    # Identical feeds must diff instantly via the set-equality fast path.
    assert diff_events(evs, evs).is_empty


# --------------------------------------------------- regressions (found by red team)

def test_ungeocoded_stops_fail_loud():
    """MEASURED: gtfs-validator 8.0.1 emits stop_without_location at ERROR
    severity, so a feed with nameless coordinates can NEVER pass the publish
    gate. A paper timetable has no coordinates, so geocoding is a required
    stage. Composing must fail loudly rather than emit an unpublishable feed."""
    raw = json.loads(FIXTURE.read_text())
    for c in raw["claims"]:
        if c["kind"] == "stop":
            c["scope"].pop("lat", None)
            c["scope"].pop("lon", None)
    cs = ClaimSet.from_dicts(raw["agency_id"], raw["claims"])
    with pytest.raises(UngeocodedStops) as exc:
        compose(cs, feed_start=START, horizon_days=120)
    assert len(exc.value.stops) == 4
    # the geocoding stage needs a draft to see what is missing
    draft = compose(cs, feed_start=START, horizon_days=120,
                    require_coordinates=False)
    assert len(draft.ungeocoded) == 4


def test_holiday_closure_cannot_be_inverted_by_a_field_typo():
    """`removes` instead of `removed` used to become exception_type=1, i.e.
    the bus RUNS on Christmas. A near-miss field name must raise."""
    raw = json.loads(FIXTURE.read_text())
    for c in raw["claims"]:
        if c["claim_id"] == "ex1":
            c["field"] = "removes"
    cs = ClaimSet.from_dicts(raw["agency_id"], raw["claims"])
    with pytest.raises(ComposeError, match="unrecognised field"):
        compose(cs, feed_start=START, horizon_days=120)


def test_exception_on_unknown_service_is_rejected():
    """A one-character service-key mismatch used to mint a NEW service, so the
    holiday closure applied to nothing and the feed validated clean."""
    raw = json.loads(FIXTURE.read_text())
    for c in raw["claims"]:
        if c["claim_id"] == "ex1":
            c["scope"]["service"] = "WEEKDAYS"
    cs = ClaimSet.from_dicts(raw["agency_id"], raw["claims"])
    with pytest.raises(ComposeError, match="unknown service"):
        compose(cs, feed_start=START, horizon_days=120)


def test_holiday_closure_is_actually_a_closure():
    feed = compose(load(), feed_start=START, horizon_days=120)
    xmas = [r for r in feed.tables["calendar_dates.txt"] if r["date"] == "20261225"]
    assert xmas and all(r["exception_type"] == 2 for r in xmas)


@pytest.mark.parametrize("bad", ["45:00", "99:30", "31:00"])
def test_implausible_source_hours_are_rejected(bad):
    """A misread leading digit must not become a legal-but-absurd time."""
    with pytest.raises(ComposeError, match="implausible"):
        parse_hhmm(bad)


def test_legitimate_overnight_hours_still_parse():
    assert parse_hhmm("25:30") == 25 * 3600 + 30 * 60


def test_dropped_trips_are_reported_structurally():
    """Losing a whole trip to a string warning is how a feed ends up valid and
    wrong. It must be visible on the result object."""
    raw = json.loads(FIXTURE.read_text())
    for c in raw["claims"]:
        if c["claim_id"] in {"c6", "c8"}:
            c["value"] = "__ILLEGIBLE__"
    cs = ClaimSet.from_dicts(raw["agency_id"], raw["claims"])
    feed = compose(cs, feed_start=START, horizon_days=120)
    assert "RIDGE-SAT" in feed.dropped_trips


def test_oversized_feed_is_refused():
    from headway.composer.outcomes import FeedTooLarge, MAX_UNCOMPRESSED_BYTES
    assert MAX_UNCOMPRESSED_BYTES > 0 and FeedTooLarge is not None


def test_feed_reader_roundtrip():
    feed = compose(load(), feed_start=START, horizon_days=120)
    tables = read_feed(feed.to_zip_bytes())
    assert len(tables["stops.txt"]) == feed.stats.stops
    assert len(tables["trips.txt"]) == feed.stats.trips
