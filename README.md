# HEADWAY

**A bus timetable is not data until someone types it in. This agent does the typing, and refuses when it
cannot read.**

India has **20 transit feeds** in the Mobility Database — the catalogue Google Maps, Transit and
OpenTripPlanner draw from. **Nine of them are still active.** France has 1,127, of which 859 are active.

> **One active catalogued transit feed per 161 million Indians.
> In France, one per 79,359. A 2,031-fold gap.**

The reason is not technology. Indian timetables exist as photocopies, board notices and painted boards,
not CSVs.

Reproduce it in thirty seconds:

```bash
curl -sO https://files.mobilitydatabase.org/feeds_v2.csv
python3 -c "
import csv,collections
r=[x for x in csv.DictReader(open('feeds_v2.csv')) if x['location.country_code']=='IN']
print(len(r), collections.Counter(x['status'] for x in r))"
# 20 Counter({'active': 9, 'inactive': 8, 'deprecated': 3})
```

*(Measured 2026-08-27, 6,496 feeds total. Population: World Bank `SP.POP.TOTL`, 2024.)*

**India's feeds are not merely missing — they are lapsing.** A liveness check of all 20 download URLs on
2026-08-27 found **8 working**. Kochi Metro, India's *first* GTFS agency, is deprecated with a dead DNS
name. Delhi's DTC and Maharashtra's MSRTC both 404. Hyderabad Metro Rail — the only official active metro
feed — returns an HTML interstitial instead of a ZIP. India has **zero** GTFS-Realtime feeds catalogued.

That is the thesis in one sentence: *a feed is not a one-time artifact, it is a build that has to keep
passing.*

HEADWAY reads those artifacts and produces a standards-valid GTFS feed — or refuses, loudly, with the
reason attached.

---

## What it actually does

```
photo / PDF / voice memo
        │
        ▼
┌───────────────────┐   two INDEPENDENT reads, blind to each other
│  Reader (Gemini)  │   gemini-3.7-flash + gemini-3.5-flash-lite
└───────────────────┘   zero tools · zero write permissions
        │  typed SourceClaims: what the cell says, and where it is
        ▼
┌───────────────────┐   NO MODEL. Row/column recovered by clustering
│   Grid binding    │   bounding boxes. Geometry has one correct answer.
└───────────────────┘
        │
        ▼
┌───────────────────┐   NO MODEL. Disagreement between readers WITHHOLDS
│ Disagreement gate │   the claim. Agreement is never treated as proof.
└───────────────────┘
        │
        ▼
┌───────────────────┐   NO MODEL. Schedule arithmetic is not a language task.
│     Composer      │   8 GTFS files, byte-identical rebuilds.
└───────────────────┘
        │
        ▼
┌───────────────────┐   MobilityData gtfs-validator 8.0.1 — a binary we did
│   Publish gate    │   not write. Zero ERROR notices or nothing ships.
└───────────────────┘
```

**One model stage. Four deterministic stages.** That asymmetry is the whole design.

## The three claims, and the evidence for each

### 1. It refuses rather than guesses

A wrong departure time is the one error class **no validator on earth catches** — a plausible time passes
every conformance check and still sends someone to a stop for a bus that is not coming.

Measured on a 20-cell fixture with one genuinely destroyed cell, n=3 per thinking level:

```
9 of 9 runs ABSTAINED on the unreadable cell.
19/20 correct · 0 confident-wrong · 1 abstained · identical at low/medium/high
```

`make calibrate` reproduces it. Ground truth is frozen in `fixtures/scans/route12a_truth.json`.

### 2. No model writes a CSV byte

`Composer` and the gates are ADK `BaseAgent` subclasses with **no `model` field at all**. Referential
integrity and id uniqueness hold by construction. Monotonic times are enforced by *normalisation*
(`23:45 → 24:15`), which is stated honestly because it is not the same guarantee.

### 3. A hallucination cannot reach the outside world

Enforced by IAM, not by a prompt:

| Service account | Can | Cannot |
|---|---|---|
| `sa-reader` | call Gemini | **write any bucket** |
| `sa-publisher` | write the feed bucket | **call Vertex at all** |

Proven, not asserted — `sa-reader` attempting a write returns a real Google 403 and the bucket listing
shows nothing landed. See [`docs/INFRASTRUCTURE.md`](docs/INFRASTRUCTURE.md).

## Quick start

```bash
make setup        # venv, pytest, and the gtfs-validator jar (sha256-pinned)
make test         # 82 tests
make build        # claims -> 8 GTFS files -> zip
make validate     # runs the real validator; exits non-zero on any ERROR
make ambiguity    # shows which ambiguities escalate and which are suppressed
make calibrate    # re-runs the thinking-level measurement against Vertex
```

`make validate` needs Docker (there is no Java runtime on the dev machine; the validator runs in
`eclipse-temurin:21-jre`). `make calibrate` needs `gcloud` auth and a billing-enabled project.

## The demo beat

Two ambiguous cells, near-identical confidence, opposite handling:

| cell | confidence | rider outcome if wrong | decision |
|---|---:|---|---|
| smudged digit at a **depot** (no boarding) | 0.68 | none — nobody boards there | **resolved silently** |
| smudged digit at a **dialysis centre** | 0.71 | 21 journeys retimed | **one question asked** |

**A confidence threshold cannot separate those two.** The outcome differ can, because it compiles both
readings and compares what a *rider* would experience. That is why the agent is not a wrapper around OCR.

## Documentation

| Document | Contents |
|---|---|
| [`docs/VERIFIED_STACK.md`](docs/VERIFIED_STACK.md) | Model IDs, capabilities and limits verified against primary sources. Includes two model IDs that **do not exist** and were nearly built on. |
| [`docs/INFRASTRUCTURE.md`](docs/INFRASTRUCTURE.md) | GCP project, service accounts, the IAM deny and its proof. |
| [`docs/CHANGELOG.md`](docs/CHANGELOG.md) | Every defect found, with the measurement that found it. |

## Honest limits

* The calibration fixture is **rendered**, not a real photocopy. Those numbers choose between settings;
  they are not a claim about field accuracy.
* A generated feed is an **unofficial development feed** until an operator adopts it. It is labelled that
  way in `feed_info.txt` and is never submitted to a catalogue without consent.
* Zero ERROR notices from the validator proves **conformance, not correctness**. A completely false
  timetable can validate cleanly. The correctness number is cell-level fidelity against a frozen
  transcription, and it is reported separately.

## Prior art, named because hiding it would be worse

**National RTAP GTFS Builder** — the US incumbent, federally funded, and by its own published figures
*"Initial Data Input — average 4 hours per route."* It is macro-enabled Excel plus Google Earth: a human
types the schedule in. It reads no documents. HEADWAY removes the transcription, not the tool.

Also: `MobilityData/gtfs-validator` (the publish gate here), `gtfs-diff`, `heijul/pdf2gtfs` (dormant since
2023, text-layer PDFs only), and `k23rs125/gtfs-jp-creator` (Apr 2026 — photographed timetable to GTFS-JP
with a deterministic composer and a validator gate, the closest relative).
