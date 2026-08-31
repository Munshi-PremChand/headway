# Changelog

Every entry records what was **measured**, not what was intended.

## 2026-08-31 — THE CLAIM THE PROJECT RESTS ON, FINALLY TESTED

HEADWAY exists because most Indian timetables are photocopies and phone
photographs, where the naive `pdftotext` approach scores exactly zero. Every
number measured until now was on a **clean render**, so that claim was untested
and the README said so. `scripts/photocopy_test.py` tests it: degrade the same
ASTC page the way a copier does — skew, blur, toner speckle, contrast loss,
JPEG artifacts — and run both approaches on the result. The clean page's text
layer is the ground truth and is never shown to the reader.

### Result

| level | artifact | baseline rows | HEADWAY fidelity | confident-wrong | published |
|---|---|---:|---|---:|---|
| 2 | photocopy of a photocopy | **0** | **70/70 (100%)** | **0** | 2 services |
| 3 | phone photo of a bad copy | **0** | 65/70 (93%) | 4 → **withheld** | 1 service |

The baseline scores zero at every level for a structural reason: a JPEG has no
text layer, so `pdftotext` has nothing to read. That is the situation the
project was built for, and it is now measured rather than asserted.

### The defect this found, which is the important part

At level 3 the run produced **18 confidently wrong departure times with zero
abstentions** — the exact failure class this project claims to prevent, and a
feed that would have validated clean.

Every value had been read **correctly**. The binder put them on the wrong rows.
Page skew displaces a column vertically in proportion to how far across the page
it sits, so at 2° the departure column — furthest from the centre of rotation —
was displaced by nearly a full row height. Matching each cell to its nearest row
shifted the entire column up by one. The arrival column, nearer the centre, was
untouched, which is why the corruption was invisible in aggregate: stop names
100%, arrivals 100%, departures wrong at almost every row.

Three fixes, in the order they were tried, because the first two were not enough:

1. **Monotonic alignment** (18 → 15 wrong). Nearest-match has no memory and will
   map two cells to one row while skipping another. A column of times is ordered
   and so are the rows, so the assignment must be order-preserving — a small
   dynamic program over `|cell y − row y|`. This removed crossings and
   duplicates but **not** the off-by-one: shifting a whole column down by one row
   is *also* monotonic, and under skew it is cheaper.
2. **Skew calibration from the km column** (15 → 4). Removing a systematic
   offset needs something with a known row correspondence. The km column has
   exactly one cell per row and no gaps, so its kth cell *is* row k with no
   inference. The vertical gap between it and the stop column, over the
   horizontal distance between them, measures the page skew — which then
   predicts every other column's offset from its x position.
3. **Clustering columns over every cell, not just the time cells** (4 → 0 on the
   saved read). The calibration silently did nothing at first: column centres
   were computed from time cells only, so the km column (x≈0.39) was bucketed
   into the nearest time column (arrival, x≈0.53). The calibrator saw a mixed
   bucket, never matched the row count, and the skew stayed 0.00.

Measured skew now tracks the applied skew: 0.004–0.011 at level 2, 0.018–0.023
at level 3.

### What happens at the point it still fails

A **fresh** level-3 run — different model output, different boxes — still
mis-binds 4 departures. It does not publish them.

The mis-binding puts a departure on the terminus row, and a completed run ends
with an arrival and **no** departure. The truncation rule sees a last row that
still departs, concludes the service did not end on this page, and withholds the
entire block. Verified: `truncated_trips: ['1', '3']`, and the composed feed
contains only service 2 — the one that was bound correctly.

**So at the point where the geometry fails, the system loses coverage, not
correctness.** A structural invariant caught a geometric failure that no
conformance validator could see. That is the behaviour the architecture was
built for, and this is the first time it has been demonstrated on a failure that
was not planted.

### Honest limits on this result

* The degradation is **synthetic**. It is a fair test of the no-text-layer claim
  and of skew robustness, and it is *not* a real photocopy or a real phone
  photograph. Those remain untested.
* Level 3 loses a service it should have kept. Withholding a correct service is
  a real cost, not a free win — it is simply a much smaller cost than publishing
  wrong departure times.
* One page, one operator, one layout.

Tests: **170 → 175**, including a synthetic-skew regression that fails against
the old binder.

## 2026-08-27 (later) — FIRST END-TO-END RUN ON A REAL INDIAN ARTIFACT

Everything upstream had been verified in isolation. The pipeline had never executed as a whole against a
real page. Running it found **nine defects**, five of which were invisible without the run, and two of
which were silently corrupting the output.

### The result

One page of ASTC's Guwahati division timetable
(`st.redbus.in/Images/WL/ASTC/schedules_new/Guwahati_division.pdf`, page 1, source sha256 `ce513365…`,
rendered at 200 dpi to a PNG with sha256 `1f9d10b4…`):

```
98 claims read by each of two models, independently
 → 91 bound by geometry · 2 complete service blocks · 1 withheld for running off the page edge
 → 0 escalated on reader disagreement
 → 12 of 14 stop names located · 2 REFUSED rather than guessed
 → 15 segments audited against the printed km column: PASS, tightest margin 6.5 km
 → 2 trips · 12 stops · 17 stop_times · 2,114 bytes
 → gtfs-validator 8.0.1: ERROR=0 WARNING=0 · gate open
```

**Transcription fidelity: 25 of 25 rows exact**, scored against the PDF's embedded text layer — which is
extracted but never shown to the reader, so it is an independent oracle rather than a hint. Every stop
name, every km value, every arrival and every departure matched, including `12.00 Noon`.

**Reproducible:** three consecutive live runs produced the byte-identical feed `70224a64…`.

### What the run refused to do, and why that is the result

* **Service 3 was withheld.** "Guwahati to Bihpuria" runs off the bottom of page 1. Its last visible row
  still has a departure time, so the bus does not terminate there. Composing it would have published a
  409 km coach service as though it ended at Jamugurihat. The rule is structural, not statistical: a
  completed run ends with an arrival and no departure.
* **Laluk and Jagiroad got no coordinates.** OpenStreetMap's gazetteer has no place node for either. The
  best match for "Jagiroad" is *Jagiroad Hardware Stores* in Guwahati, 60 km away; for "Laluk" it is a
  road named after the village. Both were refused, both stops were omitted from their trips, and both
  are named in the ledger. A missing stop is visible; a stop in the wrong town is not.

### The nine defects

1. **The pipeline could not be constructed at all.** ADK 2.8 rejects a schema passed as
   `generate_content_config.response_schema` and requires `LlmAgent(output_schema=...)`. The unit tests
   built the pieces but never the `SequentialAgent`, so this had never fired.
2. **Retractions did not survive serialisation.** `SourceClaim.as_dict` wrote `retracted` and
   `ClaimSet.from_dicts` dropped it. Every claim a stage withheld came back active at the next stage —
   the truncated service block was composed into the feed despite being withheld. Withholding that does
   not survive serialisation is not withholding.
3. **State never reached the session service.** Custom `BaseAgent`s wrote to `ctx.session.state`
   directly, which updates the live object but persists nothing. The final report read an empty session
   and printed `CLOSED` seconds after the validator had printed `ERROR=0` and `OPEN`. Fixed by carrying
   an `EventActions(state_delta=…)` on each event, which also puts every value on the replayable event
   stream.
4. **The two readers use different bounding-box conventions, and neither is stable.**
   `gemini-3.7-flash` emitted `[x0, y0, x1, y1]` normalised 0..1; `gemini-3.5-flash-lite` emitted
   `[ymin, xmin, ymax, xmax]` scaled 0..1000 — and both flipped between runs. Read with the wrong
   convention the second reader's boxes land on nothing, and because the binder recovers row and column
   FROM the box, the whole read binds to the wrong cells while the gate reports zero disagreements.
   Detection now uses two independent signals that must agree: printed text is wider than it is tall,
   and a timetable has more rows than columns.
5. **Nearest-band row matching manufactured disagreements.** The readers disagree about absolute
   coordinates by up to two row heights on the same page — one put Paltanbazar at y=0.2615 and the
   other at 0.2445, drifting to 0.4635 versus 0.4800 by the bottom of the block. Matching cells to
   coordinate bands turned that drift into 8–12 phantom escalations per run, each claiming the two
   models had read different stop names. Rows are now the stop column in **rank order**, and cells are
   matched to the nearest stop row *within the same read*, so each reader's drift cancels against itself.
6. **One malformed heading box swallowed its own block.** flash-lite returned a heading box spanning
   y 0.200 to 0.617. Its centre landed below eight of its own stops, dropping them from the binding
   entirely. Block boundaries now use the heading's top edge, and block membership follows the printed
   block number — which is transcription, not bookkeeping — with geometry only as the fallback.
7. **A thin second read manufactured escalations.** On one run in five flash-lite returned 10 claims for
   a page it had transcribed fully in the other four. Comparing 98 claims against a 10-claim stub is not
   a second opinion. A second read covering under 60% of the primary's claims is now reported as a
   FAILED read — "no corroboration was available" — rather than as a disagreement count.
8. **A misread departure became a 24-hour dwell.** `normalise_trip_times` rolls a backwards time forward
   a day, which is right for a run crossing midnight and catastrophic inside a single stop. A departure
   of 07:00 against an 07:30 arrival produced a valid, validator-clean stop_time saying the bus parks at
   Beta overnight. Dwells over six hours are now refused; genuine midnight rollovers still compose.
9. **The feed version moved when the timetable had not.** It was hashed from the claim set, which
   carries reader confidences that vary between runs (`1.0` on one, `0.99` on the next), so identical
   transcriptions produced different zips. It is now hashed from the seven other GTFS files, so the
   version changes exactly when the published service changes.

### Also fixed by the run

* `parse_hhmm` raised on `12.00 Noon`, losing a legitimate midday departure.
* `feed_contact_url` was absent, producing the run's only WARNING.
* `trip_headsign` was empty; it is now the last stop the trip actually serves — read from the stops that
  survived composition, so an omitted terminus cannot put a place the feed never mentions on the bus.

### New in this build

* `pipeline/credentials.py` — three ways to reach Gemini, in preference order. **The ADC blocker was not
  real**: `google-genai` accepts an explicit `credentials=` object, so a bearer token from
  `gcloud auth print-access-token` authenticates Vertex without `application-default login`. Verified
  live, and again through an ADK `LlmAgent` under `InMemoryRunner`.
* `pipeline/render.py` — PDF to PNG at a fixed dpi, with the source and page hashed into the ledger. The
  embedded text layer is extracted and **never** sent to the model; it exists only to score the read.
* `profiles/` — the facts a sheet of paper does not carry (timezone, calendar, publisher), declared by
  hand and tagged `origin: operator-profile` so *read* and *declared* stay distinguishable. ASTC's
  operating days are marked an **assumption** and printed as one on every run.
* `geo/geocode.py` — OpenStreetMap lookups ranked by category tier rather than by Nominatim's own
  `importance`, which ranks a hardware store above the town it is named after. Refuses on no match, on a
  non-place, on ambiguity, and outside the operator's declared region. Cached to a committed file so a
  demo does not depend on a third-party service being up. Aliases map a printed name to a gazetteer
  QUERY, never to a coordinate — a spelling claim can be checked by eye, a latitude cannot.
* `geo/plausibility.py` — **the timetable audits the geocoder.** Road distance is never shorter than a
  straight line, so a straight line longer than the printed km between two stops proves a coordinate is
  wrong. This is the only check in the stack that catches a stop placed in the wrong town, which no
  conformance validator can see.
* `reader/blocks.py` — binding for the service-block layout, including the page-truncation rule.
* `scripts/run_pipeline.py` — the whole run, with a ledger where every number is printed by the code
  that computed it.

Tests: **82 → 167**.

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

- Created GCP project `headway-atah-2026` under organisation `<organisation>`, linked billing
  account `<billing-account-id>` → `billingEnabled: true`. Enabled 12 APIs.
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
