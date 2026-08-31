"""The ADK pipeline. The centrepiece is an agent with NO MODEL IN IT.

    ParallelReaders -> GridBinder -> DisagreementGate -> Geocoder -> Composer -> Validator
    (LlmAgent x2)      (BaseAgent)   (BaseAgent)         (BaseAgent) (BaseAgent) (BaseAgent)

Only the first stage contains a model. Everything downstream of the readers is
deterministic Python, which is the architectural claim this project makes and
the reason its output can be gated on a third-party binary:

  * **Two independent reads, not one.** `gemini-3.7-flash` and
    `gemini-3.5-flash-lite` read the same crop without seeing each other's
    answer. Agreement is NOT treated as proof — two models can be wrong the same
    way. Disagreement IS treated as proof of doubt, and doubt escalates.
    The signal is trusted in one direction only.
  * **No model writes a CSV byte.** `Composer` is a `BaseAgent` subclass with no
    `model` field at all. Schedule arithmetic is not a language task.
  * **The publish gate is somebody else's binary.** `Validator` shells out to
    MobilityData's `gtfs-validator`. Zero ERROR notices or nothing ships.

`GridBinder` runs BEFORE the gate, and the order is load-bearing rather than
cosmetic. A claim id minted before binding falls back on ENUMERATION ORDER to
break ties between two cells of the same trip, so the same cell read by two
models can end up with two different ids and the gate silently compares nothing
at all. After binding, an id is a pure function of (kind, trip, stop, sequence,
field) and the two reads line up cell for cell.

`_run_async_impl(ctx) -> AsyncGenerator[Event, None]` is the ADK 2.8 override
point for a custom agent; state travels on `ctx.session.state`.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, AsyncGenerator

from google.adk.agents import BaseAgent, LlmAgent, ParallelAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types

from headway.composer.compose import UngeocodedStops, compose
from headway.composer.outcomes import diff_events, enumerate_events
from headway.geo.geocode import Fix, Geocoder
from headway.geo.plausibility import (
    check_trip, implied_speed, report as plausibility_report,
)
from headway.profiles import Profile, load as load_profile, merge as merge_profile
from headway.reader.blocks import (
    bind_blocks, rebind_claim_ids as rebind_block_ids, withhold_truncated,
)
from headway.reader.gemini_reader import (
    CLAIM_RESPONSE_SCHEMA, DEFAULT_MODEL, READER_THINKING_LEVEL,
    SECOND_OPINION_MODEL, SYSTEM_PROMPT, assert_compliant, build_system_prompt,
    parse_claims,
)
from headway.reader.grid import bind_grid, rebind_claim_ids as rebind_grid_ids
from headway.schema.claims import ClaimKind, ClaimSet, SourceClaim

# session.state keys
K_PRIMARY = "claims_primary"
K_SECOND = "claims_second"
K_BOUND_PRIMARY = "claims_primary_bound"
K_BOUND_SECOND = "claims_second_bound"
K_BINDING = "binding_report"
K_RESOLVED = "claims_resolved"
K_ESCALATIONS = "escalations"
K_UNCONFIRMED = "unconfirmed"
K_WITHHELD = "withheld"
K_GEOCODE = "geocode_report"
K_PLAUSIBILITY = "plausibility"
K_FEED = "feed_bytes_hex"
K_STATS = "feed_stats"
K_VALIDATION = "validation"
K_AGENCY = "agency_id"
K_FEED_START = "feed_start"
K_SOURCE = "source_file"
K_COVERAGE = "second_read_coverage"

# A second read covering less than this fraction of the primary's claims is a
# failed read, not a second opinion. Comparing against it manufactures
# escalations that describe the reader rather than the page.
MIN_SECOND_READ_COVERAGE = 0.60


def _say(author: str, text: str, state: dict[str, Any] | None = None) -> Event:
    """A narration event, so the run is watchable in `adk web`.

    `state` carries a state delta. MEASURED 2026-08-27, first end-to-end run:
    writing to `ctx.session.state` alone updates the in-memory object a stage
    is holding but never reaches the session service, so `get_session()` after
    the run returned a session with none of it. Every downstream stage read the
    values fine and the final report read nothing at all — the run printed
    "PUBLISH GATE — CLOSED" moments after the validator had printed
    ERROR=0 and OPEN.

    A state delta on the event is how ADK persists state, and it has the
    further merit of putting every value on the event stream where it can be
    replayed and audited rather than only in a live object.
    """
    event = Event(author=author,
                  content=types.Content(role="model",
                                        parts=[types.Part(text=text)]))
    if state:
        event.actions = EventActions(state_delta=dict(state))
    return event


# --------------------------------------------------------------- reading stage

def build_reader(name: str, model: str, output_key: str, *,
                 layout: str = "matrix", client: Any = None,
                 max_output_tokens: int = 32768) -> LlmAgent:
    """One independent read of the source artifacts. Holds NO tools.

    `client` accepts a pre-configured `google.genai.Client`, which is how the
    pipeline runs without an Application Default Credentials file — see
    `headway.pipeline.credentials`. Passing None keeps ADK's own environment
    based construction.
    """
    assert_compliant(model)
    model_arg: Any = model
    if client is not None:
        from google.adk.models import Gemini
        model_arg = Gemini(model=model, client=client)
    return LlmAgent(
        name=name,
        model=model_arg,
        description=f"Transcribes transit artifacts into typed claims using {model}.",
        instruction=build_system_prompt(layout),
        tools=[],                       # structural: a reader can take no action
        output_key=output_key,
        # MEASURED 2026-08-27, the first time this pipeline was ever run end to
        # end: ADK 2.8 REJECTS a schema passed as
        # `generate_content_config.response_schema` and requires
        # `LlmAgent(output_schema=...)`. Constructing the agent raised
        # ValidationError, so the pipeline as previously written could not have
        # executed at all — the unit tests built the pieces but never the
        # SequentialAgent. A raw JSON-Schema dict is accepted here, and ADK
        # already drops thought parts before applying it.
        output_schema=CLAIM_RESPONSE_SCHEMA,
        generate_content_config=types.GenerateContentConfig(
            response_mime_type="application/json",
            # A full A4 page of service blocks runs to roughly 100 claims and
            # 7k output tokens. The default ceiling truncates it, and a
            # truncated structured response is unparseable rather than short —
            # `answer_text` refuses a MAX_TOKENS candidate outright.
            max_output_tokens=max_output_tokens,
            thinking_config=types.ThinkingConfig(
                thinking_level=READER_THINKING_LEVEL),
        ),
    )


# ------------------------------------------------------- deterministic stages

class GridBinder(BaseAgent):
    """Recover row, column and block from bounding-box geometry. NO MODEL.

    Runs on BOTH reads independently, before they are compared. Binding first
    is what makes the comparison meaningful: after it, a claim's id is a pure
    function of where the cell sits on the page, so the two readers' claims can
    be matched cell for cell instead of by the order they happened to enumerate
    in.

    It also decides which service blocks actually ended on this page. A block
    whose final row still has a departure time did not terminate there — it ran
    off the bottom edge — and publishing it would assert that a 409 km coach
    service ends at a village halfway along.
    """

    layout: str = "matrix"
    profile_id: str = ""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        st = ctx.session.state
        agency = st.get(K_AGENCY, "agency")
        source = st.get(K_SOURCE, "source")
        lines: list[str] = []
        report: dict[str, Any] = {}

        for raw_key, out_key, label in (
            (K_PRIMARY, K_BOUND_PRIMARY, "primary"),
            (K_SECOND, K_BOUND_SECOND, "second"),
        ):
            cs = _load(st.get(raw_key), agency, source)
            if cs is None:
                lines.append(f"{label}: no read to bind")
                continue

            if self.layout == "service_blocks":
                bound, rep = bind_blocks(cs)
                bound, withheld = withhold_truncated(bound, rep)
                bound = rebind_block_ids(bound)
                rep["withheld_claims"] = len(withheld)
            else:
                bound, rep = bind_grid(cs)
                bound = rebind_grid_ids(bound)

            if self.profile_id:
                bound = merge_profile(bound, load_profile(self.profile_id))

            st[out_key] = bound.canonical_json()
            if label == "primary":
                report = rep
                st[K_WITHHELD] = rep.get("truncated_trips", [])
            lines.append(
                f"{label}: {len(cs.active())} claims read, "
                f"{len(bound.active())} bound")

        st[K_BINDING] = report
        delta: dict[str, Any] = {
            K_BINDING: report,
            K_WITHHELD: report.get("truncated_trips", []),
        }
        for k in (K_BOUND_PRIMARY, K_BOUND_SECOND):
            if st.get(k) is not None:
                delta[k] = st[k]
        detail = ""
        if report.get("blocks"):
            done = [b for b in report["blocks"] if not b["truncated"]]
            cut = [b for b in report["blocks"] if b["truncated"]]
            detail = (f" · {len(done)} complete service block(s), "
                      f"{len(cut)} withheld for running past the page edge")
            for b in cut:
                detail += f"\n    WITHHELD trip {b['trip']}: {b['reason']}"
        elif report.get("rows_detected"):
            detail = (f" · {report['rows_detected']} rows x "
                      f"{report['cols_detected']} columns recovered by clustering")
        yield _say(self.name, "; ".join(lines) + detail +
                   "\nRow, column and block came from geometry. No model was "
                   "asked where a cell sits.", delta)


class Geocoder(BaseAgent):
    """Stop names to coordinates, then audit them against the printed km. NO MODEL.

    Two stages, and the second is the interesting one. Resolving a name against
    OpenStreetMap can go wrong quietly. Checking the result against the
    timetable's own distance column cannot: road distance is never shorter than
    a straight line, so a straight line longer than the printed road distance
    proves a coordinate is wrong.
    """

    profile_id: str = ""
    offline: bool = False

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        st = ctx.session.state
        cs = _load(st.get(K_RESOLVED), st.get(K_AGENCY, "agency"),
                   st.get(K_SOURCE, "source"))
        if cs is None:
            yield _say(self.name, "No admitted claims; nothing to locate.")
            return

        profile = load_profile(self.profile_id) if self.profile_id else None
        geo = Geocoder_for(profile, offline=self.offline)
        if geo is None:
            yield _say(self.name, "No operator profile; geocoding skipped.")
            return

        names = [str(c.value) for c in cs.active()
                 if c.kind is ClaimKind.STOP and c.field == "stop_name"]
        fixes, refusals = geo.resolve_all(names)

        placed: list[SourceClaim] = []
        for c in cs.claims:
            if (c.kind is not ClaimKind.STOP or c.field != "stop_name"
                    or c.retracted):
                placed.append(c)
                continue
            fix = fixes.get(str(c.value))
            scope = dict(c.scope)
            if fix is not None:
                scope.update({"lat": fix.lat, "lon": fix.lon,
                              "geocode_precision": fix.precision,
                              "geocode_osm": f"{fix.osm_type}/{fix.osm_id}"})
            placed.append(SourceClaim(
                claim_id=c.claim_id, kind=c.kind, field=c.field, value=c.value,
                confidence=c.confidence, provenance=c.provenance,
                alternatives=list(c.alternatives), scope=scope,
                retracted=c.retracted, retraction_reason=c.retraction_reason))

        located = ClaimSet(agency_id=cs.agency_id, claims=placed)
        st[K_RESOLVED] = located.canonical_json()
        st[K_GEOCODE] = {
            "resolved": {n: f.as_dict() for n, f in fixes.items()},
            "refused": {n: r.as_dict() for n, r in refusals.items()},
            "requests_made": geo.requests_made,
        }

        checks = _plausibility(located, fixes)
        st[K_PLAUSIBILITY] = checks

        by_precision: dict[str, int] = {}
        for f in fixes.values():
            by_precision[f.precision] = by_precision.get(f.precision, 0) + 1
        text = (f"{len(fixes)}/{len(set(names))} stop names located "
                f"({by_precision}); {len(refusals)} refused rather than guessed")
        for n, r in sorted(refusals.items()):
            text += f"\n    NO COORDINATE {n}: {r.reason}"
        text += (f"\n    geometry audit: {checks['segments_checked']} segments "
                 f"checked against the printed km column — {checks['verdict']}")
        if checks["offenders"]:
            for o in checks["offenders"]:
                text += (f"\n    IMPLAUSIBLE {o['from']} -> {o['to']}: printed "
                         f"{o['printed_km']} km, straight line "
                         f"{o['straight_km']} km")
        elif checks["tightest_margin_km"] is not None:
            text += (f"\n    tightest margin {checks['tightest_margin_km']} km "
                     f"— every straight line fits inside its road distance")
        for d in checks.get("source_defects", []):
            text += (f"\n    SOURCE DEFECT trip {d['trip']} {d['from']} -> "
                     f"{d['to']}: {d['why']}"
                     + (f" ({d['kph']} km/h)" if d.get("kph") else ""))
        yield _say(self.name, text, {K_RESOLVED: st[K_RESOLVED],
                                     K_GEOCODE: st[K_GEOCODE],
                                     K_PLAUSIBILITY: checks})


def Geocoder_for(profile: Profile | None, *, offline: bool = False):
    """Build a geocoder from an operator profile, or None if there is none."""
    if profile is None:
        return None
    from headway.geo.geocode import Geocoder as _G
    return _G(region=profile.geocode_region, viewbox=profile.geocode_viewbox,
              aliases=profile.stop_aliases, offline=offline)


def _plausibility(cs: ClaimSet, fixes: dict[str, Fix]) -> dict[str, Any]:
    """Run the road-versus-straight-line check over every bound trip."""
    trips: dict[str, dict[int, dict[str, Any]]] = {}
    for c in cs.active():
        if c.kind is not ClaimKind.STOP_TIME:
            continue
        tkey = str(c.scope.get("trip") or "")
        seq = int(c.scope.get("seq") or 0)
        row = trips.setdefault(tkey, {}).setdefault(seq, {})
        name = str(c.scope.get("stop") or "")
        row["stop"] = name
        row.setdefault("km", c.scope.get("km"))
        from headway.composer.compose import ComposeError, parse_hhmm
        try:
            row[f"{c.field}_s"] = parse_hhmm(c.value)
        except ComposeError:
            row[f"{c.field}_s"] = None
        fix = fixes.get(name)
        if fix is not None:
            row["lat"], row["lon"] = fix.lat, fix.lon

    from headway.composer.compose import normalise_trip_times

    segments = []
    source_defects: list[dict[str, Any]] = []
    for tkey in sorted(trips):
        ordered = [trips[tkey][s] for s in sorted(trips[tkey])]
        segments.extend(check_trip(tkey, ordered))

        # Normalise the times the way the COMPOSER does before judging speed.
        # MEASURED 2026-08-31: without this, every overnight service was
        # reported as "the printed times do not advance" — service 17 is
        # Shillong to Siliguri and legitimately runs past midnight, so its
        # arrival clock-time is lower than its departure clock-time and nothing
        # is wrong with it. Judging the published times means judging the
        # normalised ones.
        flat: list[tuple[int, str]] = []
        raw: list[int | None] = []
        for i, r in enumerate(ordered):
            for fld in ("arrival", "departure"):
                if r.get(f"{fld}_s") is not None:
                    flat.append((i, fld))
                    raw.append(r[f"{fld}_s"])
        rolled = normalise_trip_times(raw)
        adjusted = [dict(r) for r in ordered]
        for (i, fld), v in zip(flat, rolled):
            adjusted[i][f"{fld}_s"] = v

        for d in implied_speed(adjusted):
            source_defects.append({"trip": tkey, **d})
    out = plausibility_report(segments)
    # Not our error and not a reason to refuse — the page itself is wrong, and
    # saying so is more useful than publishing it quietly.
    out["source_defects"] = source_defects
    return out


class DisagreementGate(BaseAgent):
    """Compares two independent reads. NO MODEL.

    Escalates on disagreement; never resolves one by preferring the "better"
    model. Preferring a model would reintroduce exactly the failure this gate
    exists to catch — a confident single reading that nothing contradicts.
    """

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        st = ctx.session.state
        agency = st.get(K_AGENCY, "agency")
        source = st.get(K_SOURCE, "source")
        # Prefer the BOUND reads. Comparing unbound claims compares ids that
        # were disambiguated by enumeration order, which is not a comparison.
        primary = _load(st.get(K_BOUND_PRIMARY) or st.get(K_PRIMARY),
                        agency, source)
        second = _load(st.get(K_BOUND_SECOND) or st.get(K_SECOND),
                       agency, source)

        if primary is None:
            yield _say(self.name, "No primary read available; nothing to gate.")
            return

        escalations: list[dict[str, Any]] = []
        unconfirmed: list[str] = []
        coverage = 1.0
        if second is not None:
            shared = ({c.claim_id for c in primary.active()}
                      & {c.claim_id for c in second.active()})
            coverage = len(shared) / max(len(primary.active()), 1)
            if coverage < MIN_SECOND_READ_COVERAGE:
                # MEASURED 2026-08-27: on one run in five,
                # gemini-3.5-flash-lite returned 10 claims for a page it had
                # transcribed fully in the other four. Comparing a 98-claim
                # read against a 10-claim stub does not produce a second
                # opinion; it produces three escalations that say nothing about
                # the page and withhold correct claims.
                #
                # A read that thin is a FAILED read, and the honest report is
                # that no corroboration was available — not a disagreement
                # count computed from a fragment.
                second = None
        if second is not None:
            by_id = {c.claim_id: c for c in second.active()}
            for c in primary.active():
                other = by_id.get(c.claim_id)
                if other is None:
                    # The second reader did not produce this cell at all. That
                    # is NOT disagreement about a value and must not be treated
                    # as one — but it is also not the confirmation the parallel
                    # read was run to obtain, so it is counted and shown.
                    if c.kind is ClaimKind.STOP_TIME:
                        unconfirmed.append(c.claim_id)
                    continue
                if str(other.value) != str(c.value):
                    escalations.append({
                        "claim_id": c.claim_id,
                        "primary": str(c.value),
                        "second": str(other.value),
                        "reason": "independent readers disagreed",
                        "source": c.provenance.source_file,
                        "bbox": list(c.provenance.bbox or ()),
                    })

        # An escalated claim is withheld from composition, not guessed at.
        blocked = {e["claim_id"] for e in escalations}

        # WITHHOLDING CASCADES. MEASURED 2026-08-31 across the full ten-page
        # division: the source itself spells one stop "Kaliabar" once and
        # "Kaliabor" eleven times. The readers disagreed on that single cell and
        # the gate correctly withheld the stop NAME — which left the timetable
        # cells bound to it pointing at a stop that no longer existed, and the
        # composer refused the whole forty-service feed over one ambiguous
        # spelling.
        #
        # A claim whose binding rests on a withheld claim is not supported
        # either. Withholding the dependents costs one trip; leaving them
        # dangling costs the document.
        orphaned = 0
        lost_stops = {(str(c.scope.get("trip") or ""), str(c.value))
                      for c in primary.claims
                      if c.claim_id in blocked and c.kind is ClaimKind.STOP
                      and c.field == "stop_name"}
        if lost_stops:
            for c in primary.claims:
                if c.claim_id in blocked or c.kind is not ClaimKind.STOP_TIME:
                    continue
                key = (str(c.scope.get("trip") or ""), str(c.scope.get("stop") or ""))
                if key in lost_stops:
                    blocked.add(c.claim_id)
                    orphaned += 1

        kept = [c for c in primary.claims if c.claim_id not in blocked]
        resolved = ClaimSet(agency_id=primary.agency_id, claims=kept)

        st[K_RESOLVED] = resolved.canonical_json()
        st[K_ESCALATIONS] = escalations
        st[K_UNCONFIRMED] = unconfirmed
        text = (f"{len(primary.active())} claims read · {len(escalations)} "
                f"escalated on reader disagreement · {len(resolved.active())} "
                f"admitted to the Composer. Nothing was guessed.")
        if second is None:
            text += (f"\n    NOTE: NO USABLE SECOND READ (coverage "
                     f"{coverage:.0%} of the primary's claims, floor "
                     f"{MIN_SECOND_READ_COVERAGE:.0%}). Every value here rests "
                     f"on a single reader and nothing contradicted it.")
        elif unconfirmed:
            text += (f"\n    {len(unconfirmed)} timetable cell(s) appear in the "
                     f"primary read only — not disagreement, but not "
                     f"corroborated either.")
        if orphaned:
            text += (f"\n    {orphaned} timetable cell(s) withheld as well — "
                     f"their stop name was escalated, so their binding is no "
                     f"longer supported.")
        for e in escalations[:10]:
            text += (f"\n    ESCALATED {e['claim_id']}: primary said "
                     f"{e['primary']!r}, second said {e['second']!r}")
        st[K_COVERAGE] = coverage
        yield _say(self.name, text, {K_RESOLVED: st[K_RESOLVED],
                                     K_ESCALATIONS: escalations,
                                     K_UNCONFIRMED: unconfirmed,
                                     K_COVERAGE: coverage})


class Composer(BaseAgent):
    """Claims -> GTFS. NO MODEL. Schedule arithmetic is not a language task."""

    on_ungeocoded: str = "refuse"

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        st = ctx.session.state
        cs = _load(st.get(K_RESOLVED), st.get(K_AGENCY, "agency"),
                   st.get(K_SOURCE, "source"))
        if cs is None:
            yield _say(self.name, "No admitted claims; refusing to compose.")
            return

        start = date.fromisoformat(str(st.get(K_FEED_START, "2026-08-24")))
        try:
            feed = compose(cs, feed_start=start, horizon_days=120,
                           on_ungeocoded=self.on_ungeocoded)
        except UngeocodedStops as exc:
            # gtfs-validator emits stop_without_location at ERROR severity, so
            # this feed could never publish. Fail loudly and name the stops.
            st["ungeocoded"] = exc.stops
            yield _say(self.name,
                       f"REFUSED: {len(exc.stops)} stop(s) have names but no "
                       f"coordinates: {exc.stops}. Geocoding must run first.")
            return
        except Exception as exc:                                # noqa: BLE001
            yield _say(self.name, f"REFUSED: {type(exc).__name__}: {exc}")
            return

        data = feed.to_zip_bytes()
        st[K_FEED] = data.hex()
        st[K_STATS] = feed.stats.as_dict()
        st["compose_warnings"] = list(feed.warnings)
        st["omitted_stops"] = list(feed.omitted_stops)
        st["dropped_trips"] = list(feed.dropped_trips)
        text = (f"Composed {len(data)} bytes of GTFS, model-free. "
                f"{feed.stats.as_dict()}")
        for w in feed.warnings:
            text += f"\n    {w}"
        yield _say(self.name, text, {
            K_FEED: st[K_FEED], K_STATS: st[K_STATS],
            "compose_warnings": list(feed.warnings),
            "omitted_stops": list(feed.omitted_stops),
            "dropped_trips": list(feed.dropped_trips)})


class Validator(BaseAgent):
    """Runs MobilityData's gtfs-validator. The gate is somebody else's binary."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        from headway.pipeline.validate import run_validator

        st = ctx.session.state
        hexed = st.get(K_FEED)
        if not hexed:
            yield _say(self.name, "No feed to validate.")
            return
        report = run_validator(bytes.fromhex(hexed))
        st[K_VALIDATION] = report
        verdict = "OPEN" if report["errors"] == 0 else "CLOSED"
        yield _say(self.name,
                   f"gtfs-validator {report['validator_version']}: "
                   f"ERROR={report['errors']} WARNING={report['warnings']} · "
                   f"PUBLISH GATE {verdict}", {K_VALIDATION: report})


def build_pipeline(
    *, primary_model: str = DEFAULT_MODEL,
    second_model: str | None = SECOND_OPINION_MODEL,
    layout: str = "matrix",
    profile_id: str = "",
    client: Any = None,
    on_ungeocoded: str = "refuse",
    offline_geocoding: bool = False,
) -> SequentialAgent:
    """The whole run. One model stage, five deterministic stages."""
    sub = [build_reader("reader_primary", primary_model, K_PRIMARY,
                        layout=layout, client=client)]
    if second_model:
        sub.append(build_reader("reader_second", second_model, K_SECOND,
                                layout=layout, client=client))
    readers = ParallelAgent(
        name="independent_readers",
        description="Two models read the same artifacts without seeing each "
                    "other's answer.",
        sub_agents=sub,
    )
    return SequentialAgent(
        name="headway",
        description="Messy transit artifacts to a validated GTFS feed.",
        sub_agents=[
            readers,
            GridBinder(name="grid_binder", layout=layout, profile_id=profile_id),
            DisagreementGate(name="disagreement_gate"),
            Geocoder(name="geocoder", profile_id=profile_id,
                     offline=offline_geocoding),
            Composer(name="composer", on_ungeocoded=on_ungeocoded),
            Validator(name="validator"),
        ],
    )


def build_downstream_pipeline(
    *, profile_id: str = "", on_ungeocoded: str = "refuse",
    offline_geocoding: bool = False,
) -> SequentialAgent:
    """Everything after the readers, for input that is already bound.

    A multi-page run reads each page separately and stitches the pages together
    before anything can be composed, so the binding happens outside. The rest of
    the pipeline is unchanged and still runs as ADK agents — the stitch adds a
    stage, it does not replace the architecture.
    """
    return SequentialAgent(
        name="headway_downstream",
        description="Bound claims to a validated GTFS feed.",
        sub_agents=[
            DisagreementGate(name="disagreement_gate"),
            Geocoder(name="geocoder", profile_id=profile_id,
                     offline=offline_geocoding),
            Composer(name="composer", on_ungeocoded=on_ungeocoded),
            Validator(name="validator"),
        ],
    )


def _load(raw: Any, agency_id: str,
          source_file: str = "model_response") -> ClaimSet | None:
    """Accept a ClaimSet, its canonical JSON, or a raw model response."""
    if raw is None:
        return None
    if isinstance(raw, ClaimSet):
        return raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
    elif isinstance(raw, dict):
        data = raw
    else:
        return None
    if not isinstance(data, dict):
        return None
    if "claims" in data and data.get("agency_id"):
        return ClaimSet.from_dicts(data["agency_id"], data["claims"])
    if "claims" in data:
        return parse_claims(json.dumps(data), agency_id=agency_id,
                            source_file=source_file)
    return None
