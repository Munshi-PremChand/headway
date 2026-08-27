"""Geocoding and the geometry audit. No network — the fetcher is injected.

A geocoder that has only ever been exercised on its happy path is not evidence
that it refuses, and refusing is the whole reason this module exists. Every
refusal branch is driven here with a real Nominatim payload shape.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from headway.geo.geocode import Fix, Geocoder, Refusal  # noqa: E402
from headway.geo.plausibility import (  # noqa: E402
    check_trip, haversine_km, report,
)

ASSAM = [88.5, 22.5, 97.5, 29.0]


def row(**kw):
    base = {"lat": "26.62", "lon": "92.79", "category": "place", "type": "town",
            "importance": 0.44, "display_name": "Tezpur, Sonitpur, Assam",
            "osm_type": "node", "osm_id": 1}
    base.update(kw)
    return base


def geocoder(results, tmp_path, **kw):
    g = Geocoder(region="Testland", viewbox=ASSAM,
                 fetch=lambda q, vb, t: results, **kw)
    g._path = tmp_path / "cache.json"          # keep the repo cache untouched
    g._cache = {}
    return g


# ------------------------------------------------------------------ accepting

def test_a_town_resolves(tmp_path):
    got = geocoder([row()], tmp_path).resolve("Tezpur")
    assert isinstance(got, Fix)
    assert (round(got.lat, 2), round(got.lon, 2)) == (26.62, 92.79)
    assert got.precision == "settlement-node"


def test_a_transport_node_outranks_a_more_important_settlement(tmp_path):
    """A bus stop is a better answer than the suburb containing it."""
    got = geocoder([row(category="place", type="suburb", importance=0.9),
                    row(category="highway", type="bus_stop", importance=0.0001,
                        lat="26.60", lon="92.70")], tmp_path).resolve("X")
    assert isinstance(got, Fix)
    assert got.precision == "transport-node"


def test_an_administrative_centroid_is_accepted_but_labelled(tmp_path):
    got = geocoder([row(category="boundary", type="administrative")],
                   tmp_path).resolve("Gohpur")
    assert isinstance(got, Fix)
    assert got.precision == "administrative-area-centroid"


def test_a_settlement_outranks_the_district_of_the_same_name(tmp_path):
    """Nominatim ranks the district ABOVE the village; the village is right."""
    got = geocoder([row(category="boundary", type="administrative",
                        importance=0.24, lat="26.61", lon="92.76"),
                    row(category="place", type="village", importance=0.14)],
                   tmp_path).resolve("Kaliabor")
    assert isinstance(got, Fix)
    assert got.precision == "settlement-node"


# ------------------------------------------------------------------ refusing

def test_no_match_is_refused(tmp_path):
    assert isinstance(geocoder([], tmp_path).resolve("Nowhere"), Refusal)


def test_a_hardware_store_sharing_the_name_is_refused(tmp_path):
    """MEASURED: 'Jagiroad, Assam' returns Jagiroad Hardware Stores, 60 km away."""
    got = geocoder([row(category="shop", type="hardware", importance=0.0001,
                        display_name="Jagiroad Hardware Stores, Guwahati")],
                   tmp_path).resolve("Jagiroad")
    assert isinstance(got, Refusal)
    assert "is a place or a transport node" in got.reason
    assert "hardware" in got.reason


def test_a_road_named_after_the_village_is_refused(tmp_path):
    got = geocoder([row(category="highway", type="primary", importance=0.05)],
                   tmp_path).resolve("Laluk")
    assert isinstance(got, Refusal)


def test_two_equally_ranked_places_far_apart_are_refused(tmp_path):
    got = geocoder([row(importance=0.30, lat="26.0", lon="92.0"),
                    row(importance=0.295, lat="27.5", lon="94.0")],
                   tmp_path).resolve("Narayanpur")
    assert isinstance(got, Refusal)
    assert "ambiguous" in got.reason


def test_two_entries_for_the_same_place_are_not_ambiguity(tmp_path):
    got = geocoder([row(importance=0.30, lat="26.600", lon="92.790"),
                    row(importance=0.295, lat="26.601", lon="92.791")],
                   tmp_path).resolve("Tezpur")
    assert isinstance(got, Fix)


def test_a_match_outside_the_declared_region_is_refused(tmp_path):
    got = geocoder([row(lat="48.85", lon="2.35",
                        display_name="Paris, France")], tmp_path).resolve("Paris")
    assert isinstance(got, Refusal)
    assert "outside the operator's declared region" in got.reason


def test_an_unreachable_geocoder_is_not_cached_as_a_refusal(tmp_path):
    """Unknown is not the same as 'no such place'. Caching it poisons every run."""
    def boom(q, vb, t):
        raise TimeoutError("network")
    g = Geocoder(region="Testland", viewbox=ASSAM, fetch=boom)
    g._path = tmp_path / "c.json"
    g._cache = {}
    got = g.resolve("Tezpur")
    assert isinstance(got, Refusal)
    assert g._cache == {}, "a transport failure must never be cached"


# --------------------------------------------------------------------- cache

def test_the_cache_preserves_the_precision_label(tmp_path):
    """A cached fix that forgets it was a district centroid overclaims forever."""
    g = geocoder([row(category="boundary", type="administrative")], tmp_path)
    first = g.resolve("Gohpur")
    reread = Geocoder(region="Testland", viewbox=ASSAM,
                      fetch=lambda *a: [], offline=True)
    reread._path = g._path
    reread._cache = json.loads(g._path.read_text())
    second = reread.resolve("Gohpur")
    assert isinstance(second, Fix)
    assert second.precision == first.precision == "administrative-area-centroid"


def test_offline_mode_makes_no_requests(tmp_path):
    def boom(*a):
        raise AssertionError("offline mode must not call out")
    g = Geocoder(region="Testland", viewbox=ASSAM, fetch=boom, offline=True)
    g._path = tmp_path / "c.json"
    g._cache = {}
    assert isinstance(g.resolve("Tezpur"), Refusal)


def test_an_alias_maps_a_printed_name_to_a_query_not_a_coordinate(tmp_path):
    seen = []

    def fetch(q, vb, t):
        seen.append(q)
        return [row()]
    g = Geocoder(region="Assam, India", viewbox=ASSAM, fetch=fetch,
                 aliases={"Bandordowa": "Banderdewa, Arunachal Pradesh, India"})
    g._path = tmp_path / "c.json"
    g._cache = {}
    g.resolve("Bandordowa")
    g.resolve("Tezpur")
    assert seen == ["Banderdewa, Arunachal Pradesh, India", "Tezpur, Assam, India"]


# ---------------------------------------------------------------- plausibility

def test_haversine_matches_a_known_distance():
    # Guwahati to Tezpur, about 116 km as the crow flies.
    d = haversine_km(26.1804, 91.7462, 26.6230, 92.7976)
    assert 110 < d < 122


def test_a_straight_line_inside_the_printed_road_distance_passes():
    rows = [{"stop": "A", "km": 0, "lat": 26.1804, "lon": 91.7462},
            {"stop": "B", "km": 194, "lat": 26.6230, "lon": 92.7976}]
    assert report(check_trip("1", rows))["verdict"] == "PASS"


def test_a_stop_geocoded_into_the_wrong_town_is_caught():
    """The failure no validator can see: right shape, wrong place.

    Nagaon to Jagiroad is 68 printed km. Placing 'Jagiroad' on its namesake
    hardware store in Guwahati puts the two 96 km apart in a straight line —
    which no road between them could be shorter than.
    """
    rows = [{"stop": "Nagaon", "km": 286, "lat": 26.3482, "lon": 92.6858},
            {"stop": "Jagiroad", "km": 354, "lat": 26.1804, "lon": 91.7462}]
    out = report(check_trip("2", rows))
    assert out["implausible"] == 1
    assert out["verdict"] != "PASS"
    assert out["offenders"][0]["to"] == "Jagiroad"


def test_rows_missing_a_coordinate_are_skipped_not_assumed():
    rows = [{"stop": "A", "km": 0, "lat": 26.18, "lon": 91.74},
            {"stop": "B", "km": 100},
            {"stop": "C", "km": 194, "lat": 26.62, "lon": 92.79}]
    out = report(check_trip("1", rows))
    assert out["segments_checked"] == 1


def test_no_checkable_segments_reports_zero_rather_than_a_pass():
    out = report(check_trip("1", [{"stop": "A", "km": 0}]))
    assert out["segments_checked"] == 0
    assert out["tightest_margin_km"] is None


@pytest.mark.parametrize("raw,expect", [
    ("174", 174.0), (" 40 ", 40.0), ("1,024", 1024.0), ("", None), (None, None),
])
def test_km_cells_are_parsed_or_skipped(raw, expect):
    from headway.geo.plausibility import _km
    assert _km(raw) == expect
