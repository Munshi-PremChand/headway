"""Operator profiles — the facts a sheet of paper does not carry. NO MODEL.

A printed timetable states stops and times. GTFS additionally requires an IANA
timezone, a publisher URL, and a calendar saying which days the service runs.
None of that is printed on an ASTC division page, and there are only two ways
to obtain it:

  1. Ask a model to supply it. It will, fluently, and a wrong timezone shifts
     every departure in the feed by hours with no validator notice at all.
  2. Declare it once, by hand, in a file that says where each value came from.

This module is option 2. A profile is data, not inference, and every field it
contributes is tagged `origin: "operator-profile"` in the run ledger so the
distinction between *read* and *declared* survives all the way to the output.

`assumed` is the honest part. `service_days` for ASTC is an ASSUMPTION — the
PDF does not state operating days, so the profile says so out loud and the
ledger prints it as an assumption rather than a reading. An assumption that is
labelled can be checked by an operator in one glance; one that is silently
composed cannot.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from headway.schema.claims import ClaimKind, ClaimSet, Provenance, SourceClaim

PROFILE_DIR = Path(__file__).resolve().parent


class UnknownProfile(KeyError):
    """No such operator profile. Never defaulted — a default here is a lie."""


@dataclass(frozen=True)
class Profile:
    """One operator's declared, non-printed facts."""
    profile_id: str
    agency_id: str
    agency_name: str
    agency_url: str
    agency_timezone: str
    agency_lang: str
    agency_phone: str
    service_id: str
    service_days: list[str]
    layout: str
    geocode_region: str
    geocode_viewbox: list[float] | None
    source_note: str
    assumed: list[str] = field(default_factory=list)
    stop_aliases: dict[str, str] = field(default_factory=dict)

    @property
    def provenance_id(self) -> str:
        return f"profile:{self.profile_id}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "agency_id": self.agency_id,
            "agency_timezone": self.agency_timezone,
            "service_id": self.service_id,
            "service_days": list(self.service_days),
            "layout": self.layout,
            "geocode_region": self.geocode_region,
            "assumed": list(self.assumed),
            "stop_aliases": dict(self.stop_aliases),
        }

    def claims(self) -> list[SourceClaim]:
        """The profile as claims, so the Composer has one input type only.

        Confidence is 1.0 because these are declarations, not readings. The
        provenance names the profile, so nothing here can be mistaken later for
        something a model saw on the page.
        """
        prov = Provenance(source_file=self.provenance_id, page=0, bbox=None)

        def agency(fld: str, value: Any) -> SourceClaim:
            return SourceClaim(
                claim_id=f"profile_agency_{fld}", kind=ClaimKind.AGENCY,
                field=fld, value=value, confidence=1.0, provenance=prov,
                scope={"origin": "operator-profile"})

        out = [
            agency("agency_name", self.agency_name),
            agency("agency_url", self.agency_url),
            agency("agency_timezone", self.agency_timezone),
            agency("agency_lang", self.agency_lang),
        ]
        if self.agency_phone:
            out.append(agency("agency_phone", self.agency_phone))
        out.append(SourceClaim(
            claim_id=f"profile_service_{self.service_id}",
            kind=ClaimKind.SERVICE, field="days", value=list(self.service_days),
            confidence=1.0, provenance=prov,
            scope={"service": self.service_id, "origin": "operator-profile",
                   "assumption": "service_days" in self.assumed}))
        return out


def load(profile_id: str) -> Profile:
    """Load one profile by id. Raises rather than inventing a default."""
    path = PROFILE_DIR / f"{profile_id}.json"
    if not path.exists():
        available = sorted(p.stem for p in PROFILE_DIR.glob("*.json"))
        raise UnknownProfile(
            f"no operator profile {profile_id!r}; available: {available}")
    raw = json.loads(path.read_text())
    return Profile(
        profile_id=profile_id,
        agency_id=raw["agency_id"],
        agency_name=raw["agency_name"],
        agency_url=raw["agency_url"],
        agency_timezone=raw["agency_timezone"],
        agency_lang=raw.get("agency_lang", "en"),
        agency_phone=raw.get("agency_phone", ""),
        service_id=raw["service_id"],
        service_days=list(raw["service_days"]),
        layout=raw.get("layout", "matrix"),
        geocode_region=raw.get("geocode_region", ""),
        geocode_viewbox=raw.get("geocode_viewbox"),
        source_note=raw.get("source_note", ""),
        assumed=list(raw.get("assumed", [])),
        stop_aliases=dict(raw.get("stop_aliases", {})),
    )


def merge(read: ClaimSet, profile: Profile) -> ClaimSet:
    """Add the profile's declared claims to what was read off the page.

    The page wins on collisions. A profile fills gaps; it never overwrites a
    transcription, because the whole point of reading the artifact is that the
    artifact is the authority on what it says.

    The profile also stamps its calendar onto every trip that has none. A
    printed ASTC page carries no operating days at all, so without this every
    trip references service `''` and the feed cannot be built. The stamp is
    exactly as strong as the declaration behind it — which is why the profile
    marks `service_days` as an assumption and the ledger prints it as one.
    """
    have = {(c.kind, c.field) for c in read.claims if not c.is_illegible}
    extra = [c for c in profile.claims() if (c.kind, c.field) not in have]

    stamped: list[SourceClaim] = []
    for c in read.claims:
        if (c.kind in (ClaimKind.ROUTE, ClaimKind.TRIP, ClaimKind.STOP_TIME)
                and not c.scope.get("service")):
            scope = dict(c.scope)
            scope["service"] = profile.service_id
            c = SourceClaim(
                claim_id=c.claim_id, kind=c.kind, field=c.field, value=c.value,
                confidence=c.confidence, provenance=c.provenance,
                alternatives=list(c.alternatives), scope=scope,
                retracted=c.retracted, retraction_reason=c.retraction_reason)
        stamped.append(c)

    return ClaimSet(agency_id=read.agency_id or profile.agency_id,
                    claims=stamped + extra)
