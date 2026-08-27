"""Stop names to coordinates. NO MODEL, and it abstains.

Geocoding is on the critical path, not an enrichment: `gtfs-validator` 8.0.1
emits `stop_without_location` at ERROR severity, so a feed whose stops have
names but no coordinates can never publish. A paper timetable carries names
only. Something has to supply the rest.

The dangerous way to supply it is to ask a model for a latitude. It will answer
with six decimal places and no way for anyone to tell a recalled coordinate
from an invented one, and a stop placed in the wrong town produces a feed that
passes every conformance check while routing a rider to a bus stop that is 200
kilometres away. That failure is invisible to the validator, which is exactly
the class of error this project exists to refuse.

So this module resolves names against OpenStreetMap's Nominatim — a public
gazetteer whose answer for a given query can be looked up by anyone — and it
declines in four situations rather than returning a best effort:

  * nothing matched;
  * the match falls outside the operator's declared bounding box;
  * the match is a category Nominatim ranks as low-importance noise;
  * two results of the same rank are equally good, so there is no single
    answer to give.

A declined stop is left without coordinates, the Composer refuses the feed by
name, and the run ledger prints which stops need a human. That is the intended
outcome. A wrong coordinate is worse than a missing one, because a missing one
is visible.

Results are cached to a JSON file that is COMMITTED to the repository. Two
reasons: a demo must not depend on a third-party service being up, and a
reviewer can diff the exact coordinates that produced a feed instead of taking
the run's word for it.

Usage policy: Nominatim asks for a descriptive User-Agent and at most one
request per second. Both are honoured here; cached lookups make no request at
all.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "headway-gtfs/0.1 (open transit feed builder; contact via repository)"
MIN_INTERVAL_SECONDS = 1.1          # Nominatim usage policy: max 1 req/sec

# Ranking by Nominatim's own `importance` alone is WRONG here, and measurably
# so. MEASURED 2026-08-27 against the live gazetteer:
#
#   "Jagiroad, Assam, India"  -> top hit  shop=hardware  "Jagiroad Hardware
#                                Stores, Pan Bazar, Guwahati" — 60 km away
#   "Paltan Bazar, Assam"     -> the suburb (imp 0.147) outranked by nothing,
#                                but a post_office and a bus_stop of the same
#                                name sit in the same result set
#   "Kaliabor, Assam, India"  -> boundary/administrative (imp 0.240) outranks
#                                the actual village node (imp 0.147)
#
# A shop that shares a town's name will always beat that town on a fuzzy string
# match, and an administrative area's centroid is not where the bus stops. So
# the WHAT is ranked before the HOW-FAMOUS: a result is placed in a tier by its
# OSM category, and importance only breaks ties inside a tier.
TIER_TRANSPORT = 1      # an actual transport node — the most specific answer
TIER_SETTLEMENT = 2     # the town/village node — where the place itself is
TIER_ADMIN = 3          # an administrative area centroid — approximate
TIER_REJECT = 99        # a hospital, a hardware store, a road — not a place

_TRANSPORT = {
    ("highway", "bus_stop"), ("amenity", "bus_station"),
    ("public_transport", "station"), ("public_transport", "stop_position"),
    ("public_transport", "platform"), ("railway", "station"),
    ("railway", "halt"), ("aeroway", "aerodrome"),
}
_SETTLEMENT_TYPES = {
    "city", "town", "village", "suburb", "hamlet", "municipality",
    "neighbourhood", "quarter", "borough",
}


def _tier(row: dict) -> int:
    """Which tier a Nominatim row belongs to. Pure function of its category."""
    # jsonv2 names the field `category`; the older `json` format calls it
    # `class`. Reading only one silently rejected EVERY result (measured).
    cat = str(row.get("category") or row.get("class") or "")
    typ = str(row.get("type") or "")
    if (cat, typ) in _TRANSPORT:
        return TIER_TRANSPORT
    if cat == "place" and typ in _SETTLEMENT_TYPES:
        return TIER_SETTLEMENT
    if cat == "boundary" and typ == "administrative":
        return TIER_ADMIN
    return TIER_REJECT


PRECISION = {
    TIER_TRANSPORT: "transport-node",
    TIER_SETTLEMENT: "settlement-node",
    # Named, not hidden: this is a district or circle centroid, which can sit
    # kilometres from the stand the coach actually uses. Good enough to pass
    # the publish gate, NOT good enough to call a surveyed stop location.
    TIER_ADMIN: "administrative-area-centroid",
}


@dataclass(frozen=True)
class Fix:
    """One resolved coordinate, with enough provenance to audit it."""
    name: str
    lat: float
    lon: float
    display_name: str
    osm_type: str
    osm_id: int
    importance: float
    query: str
    precision: str = "settlement-node"

    def as_dict(self) -> dict[str, Any]:
        return {
            "lat": self.lat, "lon": self.lon,
            "display_name": self.display_name,
            "osm_type": self.osm_type, "osm_id": self.osm_id,
            "importance": round(self.importance, 6),
            "precision": self.precision,
            "query": self.query,
        }


@dataclass(frozen=True)
class Refusal:
    """A name that was NOT resolved, and the reason. Never a silent gap."""
    name: str
    reason: str
    query: str

    def as_dict(self) -> dict[str, Any]:
        return {"reason": self.reason, "query": self.query}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _slug(text: str) -> str:
    raw = "".join(ch if ch.isalnum() else "-" for ch in text.lower())
    return "-".join(part for part in raw.split("-") if part)


def _far_apart(a: dict, b: dict, *, degrees: float = 0.05) -> bool:
    """Roughly 5 km apart or more. Two rows for one place are not ambiguity."""
    try:
        return (abs(float(a["lat"]) - float(b["lat"])) > degrees
                or abs(float(a["lon"]) - float(b["lon"])) > degrees)
    except (KeyError, TypeError, ValueError):
        return True


def cache_path(region: str) -> Path:
    d = _repo_root() / "fixtures" / "geocode"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{_slug(region) or 'global'}.json"


def _nominatim(query: str, viewbox: list[float] | None, timeout: int) -> list[dict]:
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": "5",
        "addressdetails": "1",
    }
    if viewbox:
        # Nominatim wants left,top,right,bottom.
        west, south, east, north = viewbox
        params["viewbox"] = f"{west},{north},{east},{south}"
        params["bounded"] = "1"
    url = f"{NOMINATIM_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


class Geocoder:
    """Name to coordinate, cached on disk, abstaining by default.

    `fetch` is injectable so the tests exercise every refusal path without a
    network — a geocoder that has only ever been tested on its happy path is
    not evidence that it refuses.
    """

    def __init__(
        self,
        *,
        region: str,
        viewbox: list[float] | None = None,
        aliases: dict[str, str] | None = None,
        fetch: Callable[[str, list[float] | None, int], list[dict]] | None = None,
        timeout: int = 30,
        offline: bool = False,
    ) -> None:
        self.region = region
        self.viewbox = viewbox
        # An alias maps a PRINTED name to a gazetteer QUERY — never to a
        # coordinate. That distinction is the whole point. "Bandordowa means
        # Banderdewa" is a claim any Assamese reader can check in a second;
        # "Bandordowa is at 27.0514 N" is a claim nobody can check without
        # doing the lookup themselves, and is exactly the kind of confident
        # unverifiable number this project refuses to emit.
        self.aliases = {k.strip(): v for k, v in (aliases or {}).items()}
        self._fetch = fetch or _nominatim
        self._timeout = timeout
        self._offline = offline
        self._path = cache_path(region)
        self._cache: dict[str, Any] = (
            json.loads(self._path.read_text()) if self._path.exists() else {})
        self._last_call = 0.0
        self.requests_made = 0

    # ------------------------------------------------------------------ cache
    def _save(self) -> None:
        self._path.write_text(
            json.dumps(self._cache, indent=2, sort_keys=True) + "\n")

    def _throttle(self) -> None:
        wait = MIN_INTERVAL_SECONDS - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    # ----------------------------------------------------------------- lookup
    def _query_for(self, name: str) -> str:
        alias = self.aliases.get(name)
        if alias:
            return alias
        return f"{name}, {self.region}" if self.region else name

    def _judge(self, name: str, results: list[dict], query: str) -> Fix | Refusal:
        """Decide whether a result set contains exactly one defensible answer."""
        if not results:
            return Refusal(name, "no Nominatim match", query)

        tiered = [(_tier(r), r) for r in results]
        usable = [(t, r) for t, r in tiered if t != TIER_REJECT]
        if not usable:
            best = results[0]
            cat = best.get("category") or best.get("class")
            return Refusal(
                name,
                f"no result is a place or a transport node; the best match is "
                f"{cat!r}/{best.get('type')!r} "
                f"({str(best.get('display_name',''))[:60]})", query)

        # Tier first, importance only within a tier.
        usable.sort(key=lambda tr: (tr[0], -float(tr[1].get("importance") or 0.0)))
        tier, top = usable[0]
        top_imp = float(top.get("importance") or 0.0)

        # Two candidates of the SAME tier and near-identical rank, in different
        # places, mean the name is genuinely ambiguous. Picking one is the
        # failure this module exists to avoid. Same-tier duplicates at the same
        # spot are not ambiguity, just OSM holding the place twice.
        for other_tier, other in usable[1:]:
            if other_tier != tier:
                break
            if top_imp - float(other.get("importance") or 0.0) >= 0.02:
                break
            if _far_apart(top, other):
                return Refusal(
                    name,
                    f"ambiguous: {str(top.get('display_name','?'))[:50]!r} and "
                    f"{str(other.get('display_name','?'))[:50]!r} rank equally "
                    f"in different places", query)

        lat, lon = float(top["lat"]), float(top["lon"])
        if self.viewbox:
            west, south, east, north = self.viewbox
            if not (west <= lon <= east and south <= lat <= north):
                return Refusal(
                    name,
                    f"match at ({lat:.4f}, {lon:.4f}) falls outside the "
                    f"operator's declared region", query)

        return Fix(name=name, lat=lat, lon=lon,
                   display_name=str(top.get("display_name", "")),
                   osm_type=str(top.get("osm_type", "")),
                   osm_id=int(top.get("osm_id") or 0),
                   importance=top_imp, query=query,
                   precision=PRECISION.get(tier, "unknown"))

    def resolve(self, name: str) -> Fix | Refusal:
        """Resolve one stop name. Cached answers, including refusals, are reused."""
        key = name.strip()
        query = self._query_for(key)

        hit = self._cache.get(key)
        if hit is not None:
            if hit.get("reason"):
                return Refusal(key, hit["reason"], hit.get("query", query))
            return Fix(name=key, lat=float(hit["lat"]), lon=float(hit["lon"]),
                       display_name=hit.get("display_name", ""),
                       osm_type=hit.get("osm_type", ""),
                       osm_id=int(hit.get("osm_id") or 0),
                       importance=float(hit.get("importance") or 0.0),
                       query=hit.get("query", query),
                       # Carrying this through the cache is not a detail. It is
                       # the field that says "this is a district centroid, not
                       # a surveyed stop", and letting it fall back to the
                       # dataclass default on every cached lookup would make
                       # the whole feed silently claim better precision than it
                       # has — after the first run, which is every run.
                       precision=hit.get("precision", "unknown"))

        if self._offline:
            return Refusal(key, "not in the committed geocode cache and this "
                                "run is offline", query)

        self._throttle()
        try:
            results = self._fetch(query, self.viewbox, self._timeout)
            self.requests_made += 1
        except Exception as exc:                                # noqa: BLE001
            # A lookup failure is NOT a refusal to cache — the answer is
            # unknown, not "no such place", and caching it would poison every
            # later run.
            return Refusal(key, f"geocoder unreachable: {type(exc).__name__}",
                           query)

        verdict = self._judge(key, results, query)
        self._cache[key] = verdict.as_dict()
        self._save()
        return verdict

    def resolve_all(self, names: list[str]) -> tuple[dict[str, Fix],
                                                     dict[str, Refusal]]:
        """Resolve many names, preserving both outcomes separately."""
        fixes: dict[str, Fix] = {}
        refusals: dict[str, Refusal] = {}
        for n in sorted({x.strip() for x in names if x and x.strip()}):
            verdict = self.resolve(n)
            if isinstance(verdict, Fix):
                fixes[n] = verdict
            else:
                refusals[n] = verdict
        return fixes, refusals
