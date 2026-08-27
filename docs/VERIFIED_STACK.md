# Verified stack facts

All verified 2026-08-27 against primary sources. Anything not listed here is unverified.

## Model — `gemini-3.7-flash`

[Model card](https://ai.google.dev/gemini-api/docs/models/gemini-3.7-flash), fetched 2026-08-27.

| Property | Value |
|---|---|
| **Model code** | `gemini-3.7-flash` ← the hardcoded string in `COMPLIANT_MODELS` is **correct** |
| Stable version | `gemini-3.7-flash` |
| Inputs | **Text, Image, Video, Audio, and PDF** |
| Output | Text |
| Input tokens | 1,048,576 |
| Output tokens | 65,536 |

Supported: structured outputs · function calling · **thinking (low / medium / high)** · code execution ·
search grounding · **grounding with Google Maps** · URL context · file search · caching · Batch API ·
flex + priority inference · computer use (Preview).

Not supported: image generation, audio generation, Live API.

**Gotcha:** thinking level `minimal` is **not supported and returns an error** on this model. Use
`low` / `medium` / `high` only.

**Compliance:** satisfies the hackathon's "Gemini 3.5 or newer" gate. `gemini-3.1-pro` does **not** —
it is Preview and numbered 3.1, the Flash line having overtaken the Pro line. `tests/test_reader.py`
asserts four plausible-but-disqualifying IDs are rejected.

### Two capabilities that change the build

1. **Grounding with Google Maps is supported natively.** This directly addresses the critical-path problem
   found on 26 Aug: `gtfs-validator` emits `stop_without_location` at **ERROR** severity, so a feed whose
   stops have names but no coordinates can never pass the publish gate — and a photocopied timetable
   carries no coordinates. Maps grounding is a first-party path from "the gas station at the crossroads"
   to a latitude/longitude, and it keeps the geocoder inside the Google stack rather than adding a
   third-party dependency.
2. **Native PDF and audio input.** Board notices (PDF) and dispatcher voice memos (audio) go into the same
   model as the timetable photograph — one reader, four media, which is the Collaborative Partner twist
   ("unusual, messy, highly complex unstructured streams") satisfied by construction rather than by
   bolting on a separate transcription service.

Also new: the **Interactions API is GA** and is Google's recommended path for latest features/models.

## ⚠ Models that DO NOT EXIST — do not build against these

A generated plan proposed `gemini-3.7-pro` and `gemini-3.7-flash-lite`. **Neither appears in the complete
"All Gemini 3 models" table** on the official model list, fetched 2026-08-27. There is no 3.7 Pro and no
3.7 Flash-Lite. The only Pro is `gemini-3.1-pro-preview`, which **fails** the 3.5+ gate.

### The complete real list (verified)

| Model | Endpoint | Clears 3.5+ gate? |
|---|---|---|
| Gemini 3.7 Flash | `gemini-3.7-flash` | ✅ **core reasoner** |
| Gemini 3.6 Flash | `gemini-3.6-flash` | ✅ |
| Gemini 3.5 Flash | `gemini-3.5-flash` | ✅ |
| Gemini 3.5 Flash-Lite | `gemini-3.5-flash-lite` | ✅ **use this as the second opinion** |
| Gemini 3.1 Flash-Lite | `gemini-3.1-flash-lite` | ❌ 3.1 |
| Gemini 3.1 Pro | `gemini-3.1-pro-preview` | ❌ 3.1, Preview |
| Gemini 3 Flash | `gemini-3-flash-preview` | ❌ |
| Gemini 3.5 Live Translate | `gemini-3.5-live-translate-preview` | ✅ |
| Gemini 3.1 Flash Live | `gemini-3.1-flash-live-preview` | ❌ |
| **Gemini 3.1 Flash TTS** | `gemini-3.1-flash-tts-preview` | n/a — specialised |
| Gemini Omni Flash | `gemini-omni-flash` | n/a |
| Nano Banana 2 / 2 Lite / Pro | `gemini-3.1-flash-image` / `gemini-3.1-flash-lite-image` / `gemini-3-pro-image` | n/a — image |

Specialised task models (not gated by the 3.5 rule, since they are not the core reasoner):

| Model | Endpoint | Note |
|---|---|---|
| **Gemini Embedding 2** | `gemini-embedding-2-preview` | first **multimodal** embedding model — text, images, video, audio, PDFs in one space |
| Gemini Embedding | `gemini-embedding-001` | text only, stable |
| Gemini Robotics ER 2 | `gemini-robotics-er-2-preview` | not relevant here |

### Corrected multi-model bonus plan (+0.6, each with a real visible job)

1. **`gemini-3.7-flash`** — Reader. Timetable/PDF/audio → typed claims with bbox provenance. *Core model.*
2. **`gemini-3.5-flash-lite`** — Disagreement Gate. Independent second read of the same cell; if the two
   models disagree the claim is **escalated, never composed**. Replaces the fictional `3.7-flash-lite`.
   This is "fluency is not evidence" compiled into an architecture.
3. **`gemini-embedding-2-preview`** — Stop Reconciler. Matches handwritten stop names against the catalogue.
   Multimodal, so it also indexes the scan crops. Output is scored pairs into deterministic code, never
   free text.
4. **`gemini-3.1-flash-tts-preview`** — rider-facing stop announcement, for a low-literacy or blind rider.
   Optional 4th; a real deliverable, and the strongest Multimodal-UX artifact available.

**For the "escalation writer" reasoning job there is no Pro model available.** Use `gemini-3.7-flash` with
**thinking level `high`** — the model card confirms low/medium/high are supported (`minimal` errors).

## Validator — `gtfs-validator` v8.0.1

- Release `v8.0.1`, published 2026-05-12. Asset `gtfs-validator-8.0.1-cli.jar`, 40,256,884 bytes.
- `sha256 = 19293ddd9b6f954f216d4f12054bd8a3232921751c4484339e339764a91000e2`
- Repo has 423 stars, last pushed 2026-08-22 — actively maintained, canonical.
- **No Java runtime on this machine.** Runs containerised:
  `docker run --rm -v "$PWD":/w -w /w eclipse-temurin:21-jre java -jar vendor/gtfs-validator-8.0.1-cli.jar -i out/gtfs.zip -o out/report`
- Docker runs under colima; `colima start` is required after a reboot.

### Measured validator behaviour (not assumed)

| Notice | Severity | Consequence |
|---|---|---|
| `stop_without_location` | **ERROR** | publish gate closed — geocoding is mandatory |
| `invalid_url` | **ERROR** | `.invalid` TLD placeholders fail; use a real-looking URL |
| `missing_feed_contact_email_and_url` | WARNING | tolerable |
| `trip_coverage_not_active_for_next7_days` | WARNING | feed_start must be ≤ today |
| non-boardable stop mis-tagged | **nothing at all** | pure rider-harm error no validator catches |

## ✅ LIVE CALL VERIFIED — 2026-08-27

The model ID was a hardcoded string that had never touched an endpoint. It has now.

```
POST https://aiplatform.googleapis.com/v1/projects/headway-atah-2026/locations/global
     /publishers/google/models/gemini-3.7-flash:generateContent
  -> HTTP 200
  -> "HEADWAY GATE OK"
  -> modelVersion: gemini-3.7-flash
  -> thinkingConfig {"thinkingLevel": "low"} ACCEPTED
  -> usage: prompt 8 / candidates 4 / total 12, trafficType ON_DEMAND
```

**Location is `global`, not `us-central1`.** The host is `aiplatform.googleapis.com` with
`locations/global` in the path. Regional hosts are a separate endpoint; do not assume `us-central1`.

Viability gate status:

| Requirement | Status |
|---|---|
| Gemini 3.5 or newer | ✅ `gemini-3.7-flash` live on Vertex, verified |
| A Google agent framework | ⬜ ADK not yet imported |
| A Google Cloud service | ✅ project on billing, 12 APIs enabled, Vertex responding |

## Google Cloud

### Project `headway-atah-2026` — provisioned 2026-08-27

Created under organization `anshulmalik3024-org` (id `520136476995`), linked to billing account
`01CE9A-4C8786-A3E22E` → **`billingEnabled: true`**.

APIs enabled: `aiplatform` · `run` · `firestore` · `pubsub` · `storage` · `secretmanager` · `cloudbuild` ·
`artifactregistry` · `cloudtrace` · `logging` · `generativelanguage` · `bigquerystorage`.

```bash
gcloud config set project headway-atah-2026
```

**Still required for client libraries:** `gcloud auth application-default login`. The gcloud CLI is
authenticated, but there is no ADC file, and `google-genai` / `google-cloud-firestore` / `google-cloud-storage`
read ADC, not the CLI session. A raw REST call with `gcloud auth print-access-token` works without ADC — that
is how the live call above was made — but the SDKs will not.

### Earlier state (superseded)

`gcloud` authed as `anshulmalik3024@gmail.com`. SDK 569.0.0.

| Project | Billing |
|---|---|
| `gen-lang-client-0663638124` ("Gemini API", AI Studio-linked) | ❌ disabled |
| `waywise-484204` | ❌ disabled |
| `project-160e48dc-9dd4-41fe-a2c` (active) | ❌ disabled |

**An OPEN billing account exists: `01CE9A-4C8786-A3E22E` ("My Billing Account").** It is not linked to any
project. Cloud Run, Vertex AI, Firestore and Pub/Sub all require a linked billing account.

**Action required (~2 minutes, do before any GCP work):**

```bash
gcloud billing projects link <PROJECT_ID> --billing-account=01CE9A-4C8786-A3E22E
gcloud services enable aiplatform.googleapis.com run.googleapis.com \
    firestore.googleapis.com pubsub.googleapis.com --project=<PROJECT_ID>
```

Until then, the Gemini half of the viability gate can be satisfied **without billing** using an AI Studio
API key from <https://aistudio.google.com/apikey> — no project, no card. The rules permit "Gemini 3.5 or
newer, accessed through the Gemini API **or** Vertex AI", so either path is compliant.

A gcloud user OAuth token does **not** work against `generativelanguage.googleapis.com` — it returns
`ACCESS_TOKEN_SCOPE_INSUFFICIENT`. That endpoint wants an API key. Vertex AI accepts the OAuth token but
needs billing plus `aiplatform.googleapis.com` enabled.

## Local toolchain

Python 3.14.6 · Node v22.12.0 · Docker 29.7.1 (colima) · git 2.50.1 · gcloud 569.0.0 · **no Java runtime**.
