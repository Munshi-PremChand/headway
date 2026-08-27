"""Typed source claims — the ONLY thing a model is ever allowed to emit.

Design contract (load-bearing, do not weaken):

* A model NEVER writes a CSV byte. It emits `SourceClaim` objects only.
* Every claim carries provenance: which file, which page, which pixel box.
* A claim may carry bounded `alternatives` — competing readings of the same
  source region. The Composer compiles each branch independently and the
  outcome differ decides whether the ambiguity is worth a human question.
* A claim may abstain via `ILLEGIBLE`. Abstention is rewarded, not penalised;
  the abstention rate is reported on screen.

The repair loop mutates CLAIMS, never generated output. That is what makes
the conservation invariant meaningful.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Iterable

ILLEGIBLE = "__ILLEGIBLE__"


class ClaimKind(str, Enum):
    AGENCY = "agency"           # agency name, url, timezone, lang, phone
    ROUTE = "route"             # a named route / line
    STOP = "stop"               # a boardable place, with optional coordinates
    TRIP = "trip"               # one run of a route on a service pattern
    STOP_TIME = "stop_time"     # a cell in the timetable grid
    SERVICE = "service"         # which days a pattern operates
    EXCEPTION = "exception"     # a specific date added/removed (holiday, school)
    EFFECTIVE = "effective"     # when a change takes effect (drives the 7-day rule)


@dataclass(frozen=True)
class Provenance:
    """Where in the source this claim came from. Rendered as a box on the scan."""
    source_file: str
    page: int = 1
    # normalised 0..1 box so it overlays any render size
    bbox: tuple[float, float, float, float] | None = None

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.bbox is not None:
            d["bbox"] = list(self.bbox)
        return d


@dataclass(frozen=True)
class Alternative:
    """A competing reading of the same source region."""
    value: Any
    confidence: float
    rationale: str = ""


@dataclass
class SourceClaim:
    claim_id: str
    kind: ClaimKind
    field: str
    value: Any
    confidence: float
    provenance: Provenance
    alternatives: list[Alternative] = field(default_factory=list)
    # free-form scope keys that bind this claim to an entity, e.g.
    # {"route": "BLU", "trip": "BLU-3", "stop": "clinic", "seq": 4}
    scope: dict[str, Any] = field(default_factory=dict)
    retracted: bool = False
    retraction_reason: str = ""

    @property
    def is_illegible(self) -> bool:
        return self.value == ILLEGIBLE

    @property
    def is_ambiguous(self) -> bool:
        return len(self.alternatives) > 0

    def branch(self, alt: Alternative) -> "SourceClaim":
        """Return this claim as if the alternative reading were the truth."""
        return SourceClaim(
            claim_id=self.claim_id,
            kind=self.kind,
            field=self.field,
            value=alt.value,
            confidence=alt.confidence,
            provenance=self.provenance,
            alternatives=[],
            scope=dict(self.scope),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "kind": self.kind.value,
            "field": self.field,
            "value": self.value,
            "confidence": self.confidence,
            "provenance": self.provenance.as_dict(),
            "alternatives": [asdict(a) for a in self.alternatives],
            "scope": self.scope,
            "retracted": self.retracted,
            "retraction_reason": self.retraction_reason,
        }


@dataclass
class ClaimSet:
    agency_id: str
    claims: list[SourceClaim]

    def active(self) -> list[SourceClaim]:
        return [c for c in self.claims if not c.retracted]

    def of_kind(self, kind: ClaimKind) -> list[SourceClaim]:
        return [c for c in self.active() if c.kind == kind]

    def ambiguous(self) -> list[SourceClaim]:
        return [c for c in self.active() if c.is_ambiguous]

    def illegible(self) -> list[SourceClaim]:
        return [c for c in self.active() if c.is_illegible]

    def abstention_rate(self) -> float:
        act = self.active()
        return (len(self.illegible()) / len(act)) if act else 0.0

    def branch_on(self, claim_id: str, alt: Alternative) -> "ClaimSet":
        """Fork the claim set, resolving one ambiguity to a specific reading."""
        out = []
        for c in self.claims:
            out.append(c.branch(alt) if c.claim_id == claim_id else c)
        return ClaimSet(agency_id=self.agency_id, claims=out)

    def resolve(self, claim_id: str, value: Any, source: str) -> "ClaimSet":
        """Permanently resolve an ambiguity (e.g. after a dispatcher answers)."""
        out = []
        for c in self.claims:
            if c.claim_id == claim_id:
                out.append(SourceClaim(
                    claim_id=c.claim_id, kind=c.kind, field=c.field, value=value,
                    confidence=1.0, provenance=c.provenance, alternatives=[],
                    scope=dict(c.scope) | {"resolved_by": source},
                ))
            else:
                out.append(c)
        return ClaimSet(agency_id=self.agency_id, claims=out)

    # -- provenance / sealing -------------------------------------------------

    def canonical_json(self) -> str:
        payload = {
            "agency_id": self.agency_id,
            "claims": sorted((c.as_dict() for c in self.claims),
                             key=lambda d: d["claim_id"]),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()

    @staticmethod
    def from_dicts(agency_id: str, rows: Iterable[dict[str, Any]]) -> "ClaimSet":
        claims = []
        for r in rows:
            p = r.get("provenance", {}) or {}
            bbox = p.get("bbox")
            claims.append(SourceClaim(
                claim_id=r["claim_id"],
                kind=ClaimKind(r["kind"]),
                field=r["field"],
                value=r["value"],
                confidence=float(r.get("confidence", 1.0)),
                provenance=Provenance(
                    source_file=p.get("source_file", "unknown"),
                    page=int(p.get("page", 1)),
                    bbox=tuple(bbox) if bbox else None,
                ),
                alternatives=[Alternative(**a) for a in r.get("alternatives", [])],
                scope=r.get("scope", {}) or {},
                # MEASURED 2026-08-27, first end-to-end run: `as_dict` wrote
                # these two fields and `from_dicts` silently dropped them, so
                # EVERY retraction was lost the moment a ClaimSet crossed a
                # pipeline stage through its canonical JSON. A service block
                # withheld for running off the bottom of the page came back
                # from the round trip fully active and was composed into the
                # feed — the truncated stump of a 409 km coach service,
                # published as if the bus terminated halfway along. Withholding
                # that does not survive serialisation is not withholding.
                retracted=bool(r.get("retracted", False)),
                retraction_reason=str(r.get("retraction_reason", "")),
            ))
        return ClaimSet(agency_id=agency_id, claims=claims)
