"""The outcome differ — rider journeys, not CSV legality.

This module answers one question: *would a rider notice the difference?*

It does three jobs, which is why it earns its cost:

  1. **The clarification trigger.** An ambiguous reading is compiled BOTH ways.
     Identical rider outcomes -> resolve silently. Different -> ask exactly one
     question, phrased as a consequence ("does someone reach dialysis at 8:35
     or 8:55?") rather than as a data question.
  2. **The trip planner.** `journeys_between` answers "is there a trip serving
     A then B on date D, and when" directly over the published feed. No routing
     graph, so no OpenTripPlanner (OTP2 removed graph hot-reload; rebuilding a
     graph on camera is a deployment, not a demo).
  3. **The regression check.** Prove unrelated service survived a change.

SCALE NOTE (this was a real bug, fixed):
Enumerating every A->B pair is O(stops^2 x dates) and explodes on a feed of
even 40 stops x 20 trips x 28 days. The comparable object is therefore the
**rider event** — (date, trip, stop, time, boardable, alightable) — which is
O(stops x trips x dates). Two feeds have identical rider journeys if and only
if their rider-event sets match, because journeys are derived from events.
Pairs are expanded lazily and only for the trips that actually differ.

A "journey" here is deliberately narrow and honest: a direct, single-vehicle
ride. No transfers, no walking legs, no fares. Say that on camera.
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# Guard against zip bombs when reading third-party feeds during a national sweep.
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024


class FeedTooLarge(ValueError):
    """A third-party feed exceeded the decompression budget."""


# ------------------------------------------------------------------ feed reader

def read_feed(zip_bytes: bytes) -> dict[str, list[dict[str, str]]]:
    tables: dict[str, list[dict[str, str]]] = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        budget = sum(i.file_size for i in z.infolist())
        if budget > MAX_UNCOMPRESSED_BYTES:
            raise FeedTooLarge(f"{budget} uncompressed bytes exceeds budget")
        for name in z.namelist():
            base = name.split("/")[-1]
            if not base.endswith(".txt"):
                continue
            text = z.read(name).decode("utf-8-sig")
            tables[base] = list(csv.DictReader(io.StringIO(text)))
    return tables


def service_dates(tables: dict[str, list[dict[str, str]]]) -> dict[str, set[date]]:
    """Expand calendar.txt + calendar_dates.txt into concrete operating dates."""
    out: dict[str, set[date]] = {}

    for row in tables.get("calendar.txt", []):
        sid = row["service_id"]
        try:
            start = date(int(row["start_date"][:4]), int(row["start_date"][4:6]),
                         int(row["start_date"][6:8]))
            end = date(int(row["end_date"][:4]), int(row["end_date"][4:6]),
                       int(row["end_date"][6:8]))
        except (ValueError, KeyError):
            continue
        active = {d for d in DAYS if str(row.get(d, "0")).strip() == "1"}
        cur, acc = start, out.setdefault(sid, set())
        while cur <= end:
            if DAYS[cur.weekday()] in active:
                acc.add(cur)
            cur += timedelta(days=1)

    for row in tables.get("calendar_dates.txt", []):
        sid = row["service_id"]
        raw = row["date"]
        try:
            d = date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
        except ValueError:
            continue
        acc = out.setdefault(sid, set())
        if str(row.get("exception_type", "1")).strip() == "1":
            acc.add(d)
        else:
            acc.discard(d)
    return out


def stop_names(tables: dict[str, list[dict[str, str]]]) -> dict[str, str]:
    return {r["stop_id"]: r.get("stop_name", r["stop_id"])
            for r in tables.get("stops.txt", [])}


# ---------------------------------------------------------------- rider events

@dataclass(frozen=True)
class RiderEvent:
    """A moment a rider could actually use: board or alight, here, then.

    A garage or layover point (pickup_type=1 AND drop_off_type=1) is NOT a
    rider event. That is precisely why a smudged digit at the garage can be
    resolved silently while the same smudge at a clinic cannot.
    """
    service_date: date
    trip: str
    route: str
    stop: str
    seq: int
    time: str
    boardable: bool
    alightable: bool


def enumerate_events(
    zip_bytes: bytes, *, window_start: date, window_days: int = 28,
) -> set[RiderEvent]:
    """O(trips x stops x dates). This is the canonical comparable object."""
    tables = read_feed(zip_bytes)
    dates = service_dates(tables)
    trips = {r["trip_id"]: r for r in tables.get("trips.txt", [])}

    by_trip: dict[str, list[dict[str, str]]] = {}
    for r in tables.get("stop_times.txt", []):
        by_trip.setdefault(r["trip_id"], []).append(r)
    for rows in by_trip.values():
        rows.sort(key=lambda r: int(r["stop_sequence"]))

    window_end = window_start + timedelta(days=window_days)
    out: set[RiderEvent] = set()

    for tid, rows in by_trip.items():
        meta = trips.get(tid)
        if not meta:
            continue
        active = {d for d in dates.get(meta["service_id"], set())
                  if window_start <= d <= window_end}
        if not active:
            continue
        usable = []
        for r in rows:
            board = str(r.get("pickup_type", "0") or "0") != "1"
            alight = str(r.get("drop_off_type", "0") or "0") != "1"
            if board or alight:
                usable.append((r, board, alight))
        # A trip with fewer than two usable stops carries no rider anywhere.
        if len(usable) < 2:
            continue
        for r, board, alight in usable:
            t = r.get("departure_time") or r.get("arrival_time", "")
            for d in active:
                out.add(RiderEvent(
                    service_date=d, trip=tid, route=meta.get("route_id", ""),
                    stop=r["stop_id"], seq=int(r["stop_sequence"]), time=t,
                    boardable=board, alightable=alight))
    return out


# --------------------------------------------------------------------- journeys

@dataclass(frozen=True)
class Journey:
    """A direct, single-vehicle ride a rider could take."""
    service_date: date
    from_stop: str
    to_stop: str
    depart: str
    arrive: str
    route: str
    trip: str

    def human(self, names: dict[str, str] | None = None) -> str:
        n = names or {}
        return (f"{self.service_date:%a %d %b}: {n.get(self.from_stop, self.from_stop)} "
                f"{self.depart} -> {n.get(self.to_stop, self.to_stop)} {self.arrive}")


def journeys_from_events(events: Iterable[RiderEvent],
                         *, only_trips: set[str] | None = None) -> set[Journey]:
    """Expand events into rider journeys. Bounded by `only_trips` so this is
    called on the handful of trips that actually differ, never the whole feed."""
    grouped: dict[tuple[date, str], list[RiderEvent]] = {}
    for e in events:
        if only_trips is not None and e.trip not in only_trips:
            continue
        grouped.setdefault((e.service_date, e.trip), []).append(e)

    out: set[Journey] = set()
    for (d, tid), evs in grouped.items():
        evs.sort(key=lambda e: e.seq)
        for i, b in enumerate(evs):
            if not b.boardable:
                continue
            for a in evs[i + 1:]:
                if not a.alightable:
                    continue
                out.add(Journey(service_date=d, from_stop=b.stop, to_stop=a.stop,
                                depart=b.time, arrive=a.time, route=b.route, trip=tid))
    return out


def journeys_between(zip_bytes: bytes, from_stop: str, to_stop: str,
                     on: date) -> list[Journey]:
    """The trip-planner query. One date, one pair — cheap. Direct rides only."""
    evs = enumerate_events(zip_bytes, window_start=on, window_days=0)
    js = journeys_from_events(evs)
    return sorted((j for j in js
                   if j.from_stop == from_stop and j.to_stop == to_stop
                   and j.service_date == on), key=lambda j: j.depart)


# ----------------------------------------------------------------------- diffing

@dataclass
class OutcomeDiff:
    added: set[Journey]
    removed: set[Journey]
    changed: list[tuple[Journey, Journey]]
    affected_trips: set[str]

    @property
    def is_empty(self) -> bool:
        return not self.added and not self.removed and not self.changed

    @property
    def affected_riders(self) -> int:
        return len(self.added) + len(self.removed) + len(self.changed)

    def summary(self, names: dict[str, str] | None = None, limit: int = 5) -> str:
        if self.is_empty:
            return "no rider-visible difference"
        n = names or {}
        parts: list[str] = []
        if self.changed:
            parts.append(f"{len(self.changed)} journeys retimed")
            for a, b in self.changed[:limit]:
                deltas = []
                if a.depart != b.depart:
                    deltas.append(f"departs {a.depart} -> {b.depart}")
                if a.arrive != b.arrive:
                    deltas.append(f"arrives {a.arrive} -> {b.arrive}")
                parts.append(f"    {a.service_date:%a %d %b} "
                             f"{n.get(a.from_stop, a.from_stop)} -> "
                             f"{n.get(a.to_stop, a.to_stop)}: " + "; ".join(deltas))
        if self.removed:
            parts.append(f"{len(self.removed)} journeys REMOVED")
            for j in sorted(self.removed, key=lambda x: (x.service_date, x.depart))[:limit]:
                parts.append(f"    - {j.human(n)}")
        if self.added:
            parts.append(f"{len(self.added)} journeys added")
            for j in sorted(self.added, key=lambda x: (x.service_date, x.depart))[:limit]:
                parts.append(f"    + {j.human(n)}")
        return "\n  ".join(parts)


def diff_events(a: set[RiderEvent], b: set[RiderEvent]) -> OutcomeDiff:
    """Compare two candidate feeds by what a RIDER would experience.

    Cheap path first: if the rider-event sets are equal the journey sets are
    equal, so no pair expansion is needed at all. Only when they differ do we
    expand journeys, and only for the trips implicated.
    """
    if a == b:
        return OutcomeDiff(added=set(), removed=set(), changed=[], affected_trips=set())

    sym = a ^ b
    affected = {e.trip for e in sym}

    ja = journeys_from_events(a, only_trips=affected)
    jb = journeys_from_events(b, only_trips=affected)

    def index(js: Iterable[Journey]) -> dict[tuple, Journey]:
        return {(j.service_date, j.from_stop, j.to_stop, j.trip): j for j in js}

    ia, ib = index(ja), index(jb)
    changed: list[tuple[Journey, Journey]] = []
    added, removed = set(), set()

    for k, x in ia.items():
        y = ib.get(k)
        if y is None:
            removed.add(x)
        elif (x.depart, x.arrive) != (y.depart, y.arrive):
            changed.append((x, y))
    for k, y in ib.items():
        if k not in ia:
            added.add(y)

    changed.sort(key=lambda p: (p[0].service_date, p[0].depart))
    return OutcomeDiff(added=added, removed=removed, changed=changed,
                       affected_trips=affected)


def preserved(before: set[RiderEvent], after: set[RiderEvent],
              touched_routes: set[str]) -> tuple[bool, set[RiderEvent]]:
    """Prove unrelated service survived. Returns (ok, casualties)."""
    idx = {(e.service_date, e.trip, e.stop, e.seq): e for e in after}
    casualties = set()
    for e in before:
        if e.route in touched_routes:
            continue
        other = idx.get((e.service_date, e.trip, e.stop, e.seq))
        if other is None or other.time != e.time:
            casualties.add(e)
    return (not casualties), casualties
