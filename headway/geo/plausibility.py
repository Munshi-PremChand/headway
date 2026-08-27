"""The timetable audits the geocoder. NO MODEL.

A wrong coordinate is the one error the publish gate cannot see. `gtfs-
validator` checks that a stop HAS a latitude, never that it is the right one, so
a stop placed in the wrong town produces a feed that passes every conformance
check and sends a rider 200 km astray.

The ASTC page happens to print the one thing that makes this checkable: a `km`
column, the distance along the road from the origin. And there is a theorem
sitting in it —

    road distance between two points >= great-circle distance between them

— which holds for every pair of points on Earth, with no exceptions and no
tuning. So if the crow-flies distance between two consecutively geocoded stops
EXCEEDS the road distance the timetable prints between them, at least one of
the two coordinates is wrong. Not "suspicious": wrong, by arithmetic.

The rule is stated before it is run, and the slack is justified rather than
fitted. `slack_km` exists solely to absorb the imprecision of the coordinate
source — an administrative-area centroid can sit some kilometres from the
stand a coach actually uses — and `slack_fraction` absorbs rounding in a km
column printed to the nearest kilometre. Neither is a knob for making a failing
segment pass; a segment that fails by more than a district's width is a real
finding and is meant to be reported as one.

The check runs in both directions of value: it catches a bad geocode, and where
the coordinates are trustworthy it catches a misread km cell instead. Either
way something that would otherwise be invisible becomes a line in the ledger.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

EARTH_RADIUS_KM = 6371.0088

# Justified, not tuned. An administrative-area centroid is the coarsest
# coordinate this pipeline will accept, and a district or circle in Assam is on
# the order of tens of kilometres across, so a displacement of ~15 km from the
# true stand is expected and must not be reported as an error.
DEFAULT_SLACK_KM = 15.0
# The km column is printed to the nearest kilometre and accumulates rounding
# along a 400 km run.
DEFAULT_SLACK_FRACTION = 0.10


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class Segment:
    """One consecutive pair of stops, checked against the printed distance."""
    trip: str
    from_stop: str
    to_stop: str
    printed_km: float
    straight_km: float
    slack_km: float

    @property
    def excess_km(self) -> float:
        """How far the straight line overshoots the road distance plus slack."""
        return self.straight_km - (self.printed_km + self.slack_km)

    @property
    def implausible(self) -> bool:
        return self.excess_km > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "trip": self.trip,
            "from": self.from_stop,
            "to": self.to_stop,
            "printed_km": round(self.printed_km, 1),
            "straight_km": round(self.straight_km, 1),
            "excess_km": round(self.excess_km, 1),
            "implausible": self.implausible,
        }


def _km(value: Any) -> float | None:
    """Parse a printed km cell. Never guesses at a value it cannot read."""
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    text = "".join(ch for ch in text if ch.isdigit() or ch == ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def check_trip(
    trip: str,
    rows: list[dict[str, Any]],
    *,
    slack_km: float = DEFAULT_SLACK_KM,
    slack_fraction: float = DEFAULT_SLACK_FRACTION,
) -> list[Segment]:
    """Check every consecutive pair in one trip.

    `rows` are dicts with `stop`, `km`, `lat`, `lon`, in timetable order. Rows
    missing any of those are skipped rather than assumed — a skipped pair is
    not evidence of anything and must not be reported as a pass.
    """
    usable = []
    for r in rows:
        km = _km(r.get("km"))
        lat, lon = r.get("lat"), r.get("lon")
        if km is None or lat is None or lon is None:
            continue
        usable.append((str(r.get("stop", "")), km, float(lat), float(lon)))

    out: list[Segment] = []
    for (n1, k1, a1, o1), (n2, k2, a2, o2) in zip(usable, usable[1:]):
        printed = abs(k2 - k1)
        out.append(Segment(
            trip=trip, from_stop=n1, to_stop=n2,
            printed_km=printed,
            straight_km=haversine_km(a1, o1, a2, o2),
            slack_km=slack_km + slack_fraction * printed,
        ))
    return out


def report(segments: list[Segment]) -> dict[str, Any]:
    """Summarise, naming the worst offender rather than only a count."""
    bad = [s for s in segments if s.implausible]
    worst = max(segments, key=lambda s: s.excess_km, default=None)
    return {
        "segments_checked": len(segments),
        "implausible": len(bad),
        "offenders": [s.as_dict() for s in
                      sorted(bad, key=lambda s: -s.excess_km)[:10]],
        "tightest_margin_km": (round(-worst.excess_km, 1)
                               if worst is not None else None),
        "verdict": "PASS" if not bad else "GEOCODE OR km COLUMN IS WRONG",
    }
