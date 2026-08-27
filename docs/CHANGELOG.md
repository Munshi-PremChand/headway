# Changelog

Every entry records what was **measured**, not what was intended.

## 2026-08-27 — ADK pipeline and a publish gate that fails closed

**Added.** ADK 2.8 pipeline in `headway/pipeline/agents.py`:

```
ParallelAgent(reader_primary, reader_second) -> DisagreementGate -> Composer -> Validator
        LlmAgent x2                              BaseAgent          BaseAgent    BaseAgent
```

Only the first stage contains a model. `DisagreementGate`, `Composer` and `Validator` are `BaseAgent`
subclasses with no `model` field at all.

Two readers is **not a vote**. `gemini-3.7-flash` and `gemini-3.5-flash-lite` read the same crop without
seeing each other's answer. Agreement is never treated as proof — two models can be wrong the same way.
Disagreement *is* treated as proof of doubt, and a disagreed claim is withheld from the Composer rather
than resolved by preferring the stronger model. Preferring a model would reintroduce exactly the failure
the gate exists to catch: a confident single reading that nothing contradicts.

### Three bugs found by running it

**1. The publish gate opened on a validator that never ran.** The most dangerous defect in the project.

*Measured 2026-08-27:* 29 bytes of garbage (`b"this is not a zip file at all"`) fed to
`gtfs-validator 8.0.1` produced a report containing **zero notices**, which read as `ERROR=0` and returned
`PUBLISH GATE: OPEN`. The validator writes a report even when it cannot load the feed at all. Every
"ERROR=0" claim in the demo and write-up would have been false, and a judge dropping in a bad file would
have exposed it live.

Discriminator, measured on both paths:

| | exit | `summary.counts` | `summary.files` | notices |
|---|---:|---|---|---:|
| good feed | 0 | `{Stops:4, Routes:2, Trips:3, Agencies:1}` | 8 files | 2 |
| garbage | 255 | **absent** | **absent** | 0 |

*Fixed* with two independent guards — the exit code must be 0, **and** the report must carry
parsed-feed evidence. Neither is trusted alone. The parsed counts are carried into the result dict so
`ERROR=0` cannot be asserted without the proof that the feed was actually read.

**2. macOS `/usr/bin/java` is a stub.** It exists with no JRE behind it, so `shutil.which("java")` was
truthy and the validator silently never executed. Now probes `java -version` for a zero exit before
trusting it, and falls back to the container.

**3. colima does not mount `/var/folders`.** A system tempdir was invisible inside the container, which
reported `FileNotFoundException` for a file that plainly existed on the host. Staging moved to `.tmp/`
inside the repo, which is under `$HOME` and therefore shared.

**Tests:** 79 passing, including `test_corrupt_zip_fails_closed_rather_than_opening_the_gate`,
`test_report_carries_proof_the_feed_was_parsed`, `test_tampered_jar_fails_closed` and
`test_java_stub_on_macos_is_not_mistaken_for_a_runtime`.

## 2026-08-27 — viability gate verified live

- Created GCP project `headway-atah-2026` under organisation `anshulmalik3024-org`, linked billing
  account `01CE9A-4C8786-A3E22E` → `billingEnabled: true`. Enabled 12 APIs.
- **Live call:** `gemini-3.7-flash` on Vertex at `locations/global` returned HTTP 200, `modelVersion:
  gemini-3.7-flash`, `thinkingLevel: "low"` accepted. The location is `global`, not `us-central1`.
- Installed `google-genai` 2.20.0 and `google-adk` 2.8.0.
- Corrected the model constants: **`gemini-3.7-pro` and `gemini-3.7-flash-lite` do not exist.** Neither
  appears in the official "All Gemini 3 models" table. A generated plan had proposed building the
  multi-model bonus on both.

## 2026-08-26 — deterministic spine

- Model-free `Composer`: claims in, 8 GTFS files out, byte-identical rebuilds.
- `gtfs-validator` v8.0.1 returns `ERROR=0` on the fixture feed.
- Midnight crossing normalised `23:45 → 24:15`; rolls forward, never reorders, because silently fixing an
  out-of-order sequence would hide the reading error the fidelity oracle exists to catch.
- Outcome differ over rider events, O(n) not O(n²): **suppresses** an ambiguous smudged digit at a
  non-boardable garage (confidence 0.68) and **escalates** an equally-confident one at a dialysis centre
  (0.71) that retimes 21 journeys. A confidence threshold cannot separate those two cases.
- Five earlier bugs fixed with regression tests: ungeocoded stops failing the gate silently; a holiday
  closure **inverting** into extra service on a near-miss field name (`removes` vs `removed`); a
  service-key typo orphaning a closure; unbounded hours accepting `99:30`; the O(n²) journey explosion.
