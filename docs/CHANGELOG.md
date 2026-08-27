# Changelog

Every entry records what was **measured**, not what was intended.

## 2026-08-27 — RESOLVED: thinking level, and the abstention claim verified

### The claim that had never been tested

HEADWAY's central promise is *"it refuses rather than guesses."* Nothing in this repo had ever
demonstrated that the model abstains at all. Two earlier calibration rounds were void because the
"illegible" fixture cell **was not illegible**.

Proof it was legible, discovered by accident: when the ground truth was moved from `10:30` to `10:37`,
**the model's answer moved with it**. An interpolating model would have kept saying `10:30`. Visual
inspection of a 6× crop confirmed the digits were plainly readable through `GaussianBlur(2.1)` plus
speckle. `gemini-3.7-flash` had been reading correctly on 8 of 9 runs while the scorer labelled those
reads `LUCKY-GUESS`.

### The valid test

Fixture rebuilt with a genuinely destroyed cell — `GaussianBlur(9.0)`, 1,400 toner points, a blot ring,
no recoverable digits. Same 20-cell grid, same pre-committed read, n=3 per level.

| level | correct | confident-wrong | abstained | handled illegible honestly | secs | thoughts |
|---|---:|---:|---:|---:|---:|---:|
| low | 19.0 | 0.0 | 1.0 | **3/3** | 14.6 | 424 |
| medium | 19.0 | 0.0 | 1.0 | **3/3** | 23.7 | 1,876 |
| high | 19.0 | 0.0 | 1.0 | **3/3** | 43.2 | 5,160 |

**9 of 9 runs abstained.** Zero confident-wrong. Zero guesses at a cell that could not be read. The
central claim holds, and it is now demonstrable on camera against a fixture whose ground truth is frozen
in the repo.

### DECISION: `thinkingLevel = "low"` for the Reader

The pre-committed read is met legitimately this time — on a fixture where the metric *could* have
discriminated, because a guess would have been detectably wrong. It didn't discriminate, and that null
result is itself the answer:

* Behaviour is **identical** across all three levels — same accuracy, same abstention, same honesty.
* `high` costs **3× the latency** and **12× the thinking tokens** for no measured benefit.
* Spend that budget on the second-opinion reader instead, where a genuinely independent read buys
  something a longer single read does not.

### Honest limits on this result

* A **rendered** fixture is easier than a real Indian photocopy. These numbers choose between settings;
  they are not a claim about field accuracy.
* n=3 per level, one destroyed cell, one grid layout.
* The decision must be revalidated on real scans once operator artifacts are in hand. If abstention
  degrades there, thinking level is the first thing to re-test.

## 2026-08-27 — thinking-level calibration, and a degenerate metric

**The question:** the reader's `thinkingLevel` was set to `low` because that was the parameter on a
connectivity smoke test. It was never justified. Rather than argue for a value, it was measured.

**Pre-stated hypothesis:** thinking level affects *abstention calibration* — how often the model asserts a
value it cannot actually read — more than it affects raw accuracy.
**Pre-committed read:** use `high` if it yields ≥2 fewer confident-wrong cells than `low`.

**Result on fixture v1 (n=3 per level, 20 cells, one illegible):**

| level | correct | confident-wrong | handled illegible honestly | secs | thoughts |
|---|---:|---:|---:|---:|---:|
| low | 20.0 | 0.0 | **0/3** | 11.1 | 0 |
| medium | 20.0 | 0.0 | 2/3 | 24.7 | 2,032 |
| high | 19.3 | 0.0 | 2/3 | 52.4 | 7,369 |

**The pre-committed read was NOT met**, and the metric is the reason. The illegible cell's true value was
`10:30`, sitting on a regular interval between the legible `10:12` and `10:45`. A model that *interpolates
instead of reading* lands on the right answer, so `confident-wrong` saturated at **0 across all three
levels** and had no dynamic range. It could not discriminate.

The discriminating signal was visible in a different column: `low` guessed the unreadable cell **3/3 times**
(`LUCKY-GUESS`, confidence 0.65–0.75) while `medium` and `high` abstained or hedged 2/3.

**Note the trap:** `low` scores *better* on naive accuracy (20.0 vs 19.3) while being *worse* at the thing
that matters. Selecting on "correct cells" would have chosen the setting that guesses.

**Correction, not a metric swap.** Changing the metric after seeing the data is exactly the sin this
project exists to avoid. Instead the *fixture* was fixed so the original metric can work: the smudged
cell's true value moved to **`10:37`**, deliberately off the interval its neighbours imply. A model that
interpolates now lands on `10:30` and is detectably **wrong**, not luckily right. Re-running the same
pre-committed read against that fixture is the honest test.

## 2026-08-27 — the reader schema was breaking the reader

Three defects in `CLAIM_RESPONSE_SCHEMA`, all found by trying to measure something else. None would have
been visible without a live call.

**1. `scope` came back empty on every claim.** Declared as a bare `{"type": "object"}` with no properties,
Vertex structured output returned `scope: {}` for all 20 cells. The model *knew* the binding — its own
generated ids read `claim_st_t1_s1` — but the schema gave it nowhere to write it. In production the
Composer, which requires `scope.trip`, would have refused every claim. Fixed by declaring the properties
explicitly.

**2. An unbounded `claim_id` sent the model into a repetition loop.** With `claim_id` as a free string
inside a grammar-constrained schema:

```
finishReason: MAX_TOKENS
candidatesTokenCount: 32754
text tail: "_t1_t1_t1_t1_t1_t1_t1_t1_t1_t1_t1_t1_t1_t1_t1..."
```

32,754 output tokens spent repeating one id fragment, never producing parseable JSON. *Fixed by removing
`claim_id` from the schema entirely* — an identifier is a deterministic function of the binding, so
`_mint_claim_id` derives it in code. String fields also got `maxLength` bounds. Result on the same fixture:
`finishReason: STOP`, **1,320 output tokens (a 25× reduction), 9.3s**.

**3. Row/column bookkeeping was being asked of the model.** Added `headway/reader/grid.py`, which
reconstructs the timetable grid by **clustering bounding-box coordinates**. A printed timetable is a
matrix; which row and column a cell occupies is geometry with one correct answer, not judgement. The model
reads a cell and locates it; deterministic code decides what that location *means*.

```
grid report: rows_detected=5 cols_detected=4 stops_labelled=5 trips_labelled=4
SCORED against frozen ground truth: correct=20 wrong=0 abstained=0 unmatched=0
```

Clustering also degrades gracefully on a skewed scan, where exact-coordinate matching would not.

### A near-miss worth recording

The calibration run that found defect 1 printed a clean summary table and the verdict
**"TIE → USE LOW"**. It looked like a measurement. It was `0/0/0` across all three thinking levels, which
is impossible if anything were being scored — a broken harness producing a confident, quotable, entirely
false conclusion. It was caught only because all-zeros was too implausible to believe. This is precisely
the failure class in `_shared/OPERATING_DOCTRINE.md`: *fluency is not evidence.*

### Scoring correction

The scorer counted a correct reading of the **deliberately illegible** cell as a success. It is not — the
model had no way to read it, so a right answer there is an unearned guess. Now scored as
`ABSTAINED` / `HEDGED` (both honest) versus `LUCKY-GUESS` / `WRONG-GUESS` (both failures).

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
