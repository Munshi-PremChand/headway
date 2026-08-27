"""The ADK pipeline. The centrepiece is an agent with NO MODEL IN IT.

    ParallelReaders  ->  DisagreementGate  ->  Composer  ->  Validator  ->  Publisher
    (LlmAgent x2)        (BaseAgent)           (BaseAgent)   (BaseAgent)    (BaseAgent)

Only the first stage contains a model. Everything downstream of `DisagreementGate`
is deterministic Python, which is the architectural claim this project makes and
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

`_run_async_impl(ctx) -> AsyncGenerator[Event, None]` is the ADK 2.8 override
point for a custom agent; state travels on `ctx.session.state`.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, AsyncGenerator

from google.adk.agents import BaseAgent, LlmAgent, ParallelAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types

from headway.composer.compose import UngeocodedStops, compose
from headway.composer.outcomes import diff_events, enumerate_events
from headway.reader.gemini_reader import (
    CLAIM_RESPONSE_SCHEMA, DEFAULT_MODEL, SECOND_OPINION_MODEL, SYSTEM_PROMPT,
    assert_compliant, parse_claims,
)
from headway.schema.claims import ClaimSet

# session.state keys
K_PRIMARY = "claims_primary"
K_SECOND = "claims_second"
K_RESOLVED = "claims_resolved"
K_ESCALATIONS = "escalations"
K_FEED = "feed_bytes_hex"
K_STATS = "feed_stats"
K_VALIDATION = "validation"
K_AGENCY = "agency_id"
K_FEED_START = "feed_start"


def _say(author: str, text: str) -> Event:
    """A plain narration event, so the run is watchable in `adk web`."""
    return Event(author=author,
                 content=types.Content(role="model",
                                       parts=[types.Part(text=text)]))


# --------------------------------------------------------------- reading stage

def build_reader(name: str, model: str, output_key: str) -> LlmAgent:
    """One independent read of the source artifacts. Holds NO tools."""
    assert_compliant(model)
    return LlmAgent(
        name=name,
        model=model,
        description=f"Transcribes transit artifacts into typed claims using {model}.",
        instruction=SYSTEM_PROMPT,
        tools=[],                       # structural: a reader can take no action
        output_key=output_key,
        generate_content_config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=CLAIM_RESPONSE_SCHEMA,
        ),
    )


# ------------------------------------------------------- deterministic stages

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
        primary = _load(st.get(K_PRIMARY), st.get(K_AGENCY, "agency"))
        second = _load(st.get(K_SECOND), st.get(K_AGENCY, "agency"))

        if primary is None:
            yield _say(self.name, "No primary read available; nothing to gate.")
            return

        escalations: list[dict[str, Any]] = []
        if second is not None:
            by_id = {c.claim_id: c for c in second.active()}
            for c in primary.active():
                other = by_id.get(c.claim_id)
                if other is not None and str(other.value) != str(c.value):
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
        kept = [c for c in primary.claims if c.claim_id not in blocked]
        resolved = ClaimSet(agency_id=primary.agency_id, claims=kept)

        st[K_RESOLVED] = resolved.canonical_json()
        st[K_ESCALATIONS] = escalations
        yield _say(
            self.name,
            f"{len(primary.active())} claims read · {len(escalations)} escalated "
            f"on reader disagreement · {len(resolved.active())} admitted to the "
            f"Composer. Nothing was guessed.")


class Composer(BaseAgent):
    """Claims -> GTFS. NO MODEL. Schedule arithmetic is not a language task."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        st = ctx.session.state
        cs = _load(st.get(K_RESOLVED), st.get(K_AGENCY, "agency"))
        if cs is None:
            yield _say(self.name, "No admitted claims; refusing to compose.")
            return

        start = date.fromisoformat(str(st.get(K_FEED_START, "2026-08-24")))
        try:
            feed = compose(cs, feed_start=start, horizon_days=120)
        except UngeocodedStops as exc:
            # gtfs-validator emits stop_without_location at ERROR severity, so
            # this feed could never publish. Fail loudly and name the stops.
            st["ungeocoded"] = exc.stops
            yield _say(self.name,
                       f"REFUSED: {len(exc.stops)} stop(s) have names but no "
                       f"coordinates: {exc.stops}. Geocoding must run first.")
            return
        except Exception as exc:                                # noqa: BLE001
            yield _say(self.name, f"REFUSED: {exc}")
            return

        data = feed.to_zip_bytes()
        st[K_FEED] = data.hex()
        st[K_STATS] = feed.stats.as_dict()
        yield _say(self.name,
                   f"Composed {len(data)} bytes of GTFS, model-free. "
                   f"{feed.stats.as_dict()}")


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
                   f"PUBLISH GATE {verdict}")


def build_pipeline(
    *, primary_model: str = DEFAULT_MODEL,
    second_model: str = SECOND_OPINION_MODEL,
) -> SequentialAgent:
    """The whole run. One model stage, four deterministic stages."""
    readers = ParallelAgent(
        name="independent_readers",
        description="Two models read the same artifacts without seeing each "
                    "other's answer.",
        sub_agents=[
            build_reader("reader_primary", primary_model, K_PRIMARY),
            build_reader("reader_second", second_model, K_SECOND),
        ],
    )
    return SequentialAgent(
        name="headway",
        description="Messy transit artifacts to a validated GTFS feed.",
        sub_agents=[
            readers,
            DisagreementGate(name="disagreement_gate"),
            Composer(name="composer"),
            Validator(name="validator"),
        ],
    )


def _load(raw: Any, agency_id: str) -> ClaimSet | None:
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
    if "claims" in data and data.get("agency_id"):
        return ClaimSet.from_dicts(data["agency_id"], data["claims"])
    if "claims" in data:
        return parse_claims(json.dumps(data), agency_id=agency_id,
                            source_file="model_response")
    return None
