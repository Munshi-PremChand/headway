# HEADWAY — INDIA INTEL DOSSIER

**Compiled 27 August 2026.** Every load-bearing claim below carries a source URL and a retrieval date. Nothing here is quoted from memory.

**Verification tiers used throughout:**

| Tier | Meaning |
|---|---|
| **[A]** | Retrieved *and* re-derived by running code against the bytes on 2026-08-27. Reproducible from the command given. |
| **[B]** | Retrieved on 2026-08-27 (HTTP status + byte count recorded), inspected but not exhaustively parsed. |
| **[C]** | Located only — a URL exists and is cited, but the content was not successfully retrieved. |
| **UNVERIFIED** | Could not be checked. Do not put on camera. |

**Constraint on this run:** no web-search tool was used (session search budget exhausted). Everything is a direct URL fetch, a GitHub API call, or local computation over files already on disk. Where that constraint left a hole, it is marked UNVERIFIED rather than filled.

---

## 1. THE NUMBER

### The claim to make

> **One active catalogued transit feed per 161 million Indians. In France, one per 79,804. A 2,020-fold gap.**

### How a judge reproduces it in thirty seconds

```bash
curl -sO https://files.mobilitydatabase.org/feeds_v2.csv
python3 - <<'PY'
import csv, collections
rows=list(csv.DictReader(open('feeds_v2.csv')))
print('total rows', len(rows))
ind=[r for r in rows if r['location.country_code']=='IN']
print('India feeds', len(ind))
print(collections.Counter(r['status'] for r in ind))
PY
```

**Source:** `https://files.mobilitydatabase.org/feeds_v2.csv` — retrieved 2026-08-27, **2,646,948 bytes, 6,496 data rows, 27 columns**. **[A]**

**Result:** exactly **20** rows with `location.country_code == "IN"`. Status split: **active 9 · inactive 8 · deprecated 3**. Worldwide: active 4,671 / deprecated 1,110 / inactive 680 / future 28 / development 7.

The 117 rows with a blank `location.country_code` were scanned separately: **zero** are India-related, so 20 is the true count, not a lower bound. **[A]**

### ⚠️ Two corrections to numbers circulating in the project brief

1. **"US = one feed per 47,500 people" is an arithmetic error.** 342,000,000 ÷ 2,463 = **138,845** (and with the World Bank 2024 denominator, **138,045**). **Do not ship 47,500.**
2. **The all-feeds ratio understates the gap.** 11 of India's 20 feeds are inactive or deprecated. The honest and *stronger* number is the active-feed ratio.

### Per-capita comparison table

Population denominators: World Bank indicator `SP.POP.TOTL`, year 2024, via `https://api.worldbank.org/v2/country/{ISO3}/indicator/SP.POP.TOTL?format=json&date=2024`. Feed counts from `feeds_v2.csv` above. **[A]**

| Country | All feeds | People per feed | **Active feeds** | **People per ACTIVE feed** |
|---|---:|---:|---:|---:|
| **India** | **20** | **72,546,790** | **9** | **161,215,087** |
| Indonesia | 4 | 70,871,983 | 1 | 283,487,931 |
| Brazil | 15 | 14,133,238 | 5 | 42,399,714 |
| Mexico | 13 | 10,066,231 | 2 | 65,430,503 |
| United Kingdom | 47 | 1,474,064 | 41 | 1,689,780 |
| Germany | 68 | 1,228,185 | 45 | 1,855,924 |
| Italy | 165 | 357,289 | 99 | 595,481 |
| Spain | 212 | 230,419 | 146 | 334,581 |
| Japan | 800 | 154,969 | 753 | 164,641 |
| **United States** | **2,463** | **138,045** | 1,629 | 208,719 |
| Canada | 521 | 79,198 | 350 | 117,892 |
| **France** | **1,127** | **60,827** | 859 | **79,804** |

- India = **0.31%** of the world catalogue (20/6,496) and **0.19%** of active feeds (9/4,671), for **17.6%** of humanity.
- India vs France, active basis: **2,020×**. India vs US, active basis: **772×**.
- Pakistan (251m) and Bangladesh (174m): **zero feeds each**. This is a regional data desert, not an India-only story.

### The sharper framing: India's feeds are not missing, they are *lapsing*

A liveness test was run against all 20 `direct_download` URLs (ranged GET, 2026-08-27) **[A]**:

| Finding | Detail |
|---|---|
| Working active feeds | **8 of 20** |
| Feeds that come from an agency (`is_official=True`) and work | **1** — mdb-3361 TGSRTC Hyderabad |
| **mdb-2457 Hyderabad Metro Rail** — the only "official + active" metro feed in India | Returns **HTML, not a ZIP** (Google Drive interstitial). Broken. |
| mdb-1209 Kochi Metro | **DNS dead** (`kmrl.e-smartlab.com`), status `deprecated` |
| mdb-1262 DTC Delhi | **404**, status `inactive` |
| mdb-2336 MSRTC | **404**, status `inactive` |

**Delhi, Chennai and Kochi are not uncovered — they are lapsed.** Kochi Metro, India's *first* GTFS agency, is deprecated with a dead download. That is HEADWAY's actual thesis in one sentence: a feed is not a one-time artifact, it is a build that has to keep passing.

**India has ZERO GTFS-Realtime feeds catalogued.** Global split is gtfs 4,532 / gtfs_rt 1,964; there is no `catalogs/sources/gtfs/realtime/in-*.json` file in the repo at all (verified against the full recursive git tree, 2026-08-27). **[A]**

---

## 2. TARGET OPERATOR

### Recommendation

| Slot | Operator | Why |
|---|---|---|
| **PRIMARY** | **Assam State Transport Corporation (ASTC)**, Guwahati division | The only Indian artifact found with **genuine per-stop arrival AND departure times**. Everything else forces invented `stop_times`. Assam goes 0 → 1; India goes 20 → 21. |
| **BACKUP 1** | **Chandigarh Transport Undertaking (CTU)** | Freshest artifact in the sweep (dated 25.07.2026), completely virgin in the catalogue, but requires interpolated interior times and a new geocoder. |
| **BACKUP 2** | **UPSRTC (Uttar Pradesh)** | 946 per-route PDFs with the same arr/dep + cumulative-km structure as ASTC, at 20× the scale. Only lightly verified — see the honesty note. |
| **SECOND INPUT (not a feed target)** | **JKRTC** scanned timetables / **Kerala KSRTC** raster Malayalam PDFs | These are the *only* artifacts that prove HEADWAY's multimodal reader claim. Neither ASTC nor CTU can. |

---

### PRIMARY — Assam State Transport Corporation (ASTC / ASSAMRTC)

**City / scope:** Guwahati division (recommended demo scope), plus 8 further divisions covering the state.

**Artifact URLs** (all confirmed HTTP 200, `application/pdf`, re-checked 2026-08-27):

- Operator index page: `https://astcbus.in/schedules` — 200, **408,404 bytes**; the 9 PDF hrefs were re-extracted from its HTML this run. **[A]**
- `https://st.redbus.in/Images/WL/ASTC/schedules_new/Guwahati_division.pdf` — 680,240 bytes, 10 pages
- `.../schedules_new/Tezpur_division.pdf` — 695,823 B, 14 pp
- `.../schedules_new/Bongaigaon_division.pdf` — 489,344 B, 14 pp
- `.../schedules_new/Silchar_division.pdf` — 596,796 B, 5 pp
- `.../schedules_new/Jorhat_division.pdf` — 534,698 B, 6 pp
- `.../schedules_new/Lakhimpur_Division.pdf` — 390,823 B, 3 pp
- `.../schedules_new/Nagaon_division.pdf` — 408,696 B, 4 pp
- `.../schedules_new/Sivasagar_Division.pdf` — 379,350 B, 7 pp
- `https://st.redbus.in/Images/WL/ASTC/schedule/Tinsukia_division.pdf` — 131,431 B, 10 pp — **note the path differs**: `/schedule/`, not `/schedules_new/`. **[A]**

All nine were **retrieved** (not merely located) and text-extracted. `scripts/run_pipeline.py` re-fetches any of
them by URL and caches the bytes under `.tmp/sources/`, keyed by the sha256 of the URL, so a rerun costs no
bandwidth and the sha256 of the exact PDF that was read is printed in the run ledger.

**What the artifact contains.** Each numbered service is a stop-by-stop table:

```
1. Service : Paltanbazar to North Lakhimpur (Day Super)
Sl.No   Station          km    Arrival time   Departure time
  1  Paltanbazar          0                      7.15 AM
  2  Khanapara           10      7.30 AM         7.35 AM
  3  Kaliabor           174     11.00 AM        11.05 AM
  4  Tezpur             194     11.55 AM       12.00 Noon
 ...
 12  North Lakhimpur    409      4.15 PM
```
(verbatim from `astc_Guwahati_division.txt`, re-parsed this run)

**Route counts, re-derived on 2026-08-27 [A]:**

| Measure | Guwahati division | Corpus (9 files) |
|---|---:|---:|
| Numbered services | **40** | **310** |
| Stop rows parsed | **255** | ~2,079 |
| Distinct station strings | **51** | 393 |

The 40 / 255 / 51 figures for Guwahati were reproduced exactly by a ~15-line regex parser over `astc_Guwahati_division.txt` this run. Service classes present corpus-wide: ordinary ×32, day super ×19, super ×9, night super ×9, express ×5 — usable `route_desc` / `trip_headsign` material.

**Why it is a good demo.**

1. **`stop_times.txt` is READ, not synthesised.** This is the single differentiator. At t≈10s the screen shows page 1, row 3 highlighted — `Kaliabor | 174 | 11.00 AM | 11.05 AM` — cutting to `arrival_time=11:00:00, departure_time=11:05:00, shape_dist_traveled=174`. A 5-minute dwell that came out of the document. **[A]**
2. **Bounding-box provenance is real, not drawn.** `pdftotext -bbox-layout` on page 1 yields per-word coordinates, e.g. `<word xMin="85.439999" yMin="243.335562" xMax="125.640477" yMax="257.976112">Kaliabor</word>`. The highlight rectangle is computed. **[A]**
3. **The midnight normaliser fires on real data.** 77 within-service backward time transitions in the Guwahati division alone — night services needing exactly the `23:45 → 24:15` normalisation HEADWAY already ships. **[A]**
4. **An impossible reading that arithmetic cannot rescue.** Lakhimpur division contains `Sipajarh 30.15 pm / 30.17 pm`. A grep of the entire corpus for impossible hours returns **exactly two hits, both this stop**. `30:15 PM` cannot be normalised; the Composer must refuse it and the Reader must offer `3.15 pm` as a *bounded alternative* with a page-2 bbox. This is the ideal on-camera case for the alternative-readings machinery. **[A]**
5. **An outcome-differ case, not a threshold case.** Sivasagar service 3: `Tinkhong arr 7.30 A.M dep 7.35 P.M` — a 12-hour dwell from an AM/PM inversion. **[A]**
6. **Absence is airtight.** Assam appears nowhere in the catalogue under any name — see below.

**Absence from the catalogue, verified three ways [A]:**

- `feeds_v2.csv`: all 20 India rows printed; subdivisions present are Kerala, Delhi, Karnataka, Maharashtra, Telangana, Andhra Pradesh, Tamil Nadu, Gujarat, plus two blanks. No Assam.
- **Trading-name guard**: regex over *every field of all 6,496 rows* for `assam|guwahati|astc|assamrtc|silchar|dibrugarh|jorhat|tezpur|bongaigaon|tinsukia|sivasagar|nagaon|lakhimpur|gauhati|redbus|north east` → 9 hits, all false positives, none Indian (Keisei ×3 JP, Northeast Oregon, Connect Transit Texas City, Go North East GB, NECALG Colorado, WCC Oregon, Prasarana Malaysia Northeast Penang).
- **Repo tree**: `https://api.github.com/repos/MobilityData/mobility-database-catalogs/git/trees/main?recursive=1` — 2026-08-27, `truncated=false`, **2,475 schedule + 1,032 realtime** files, **19** `in-*` schedule files, zero paths matching the Assam keyword set.

**Every blocker, stated plainly:**

| # | Blocker | Severity |
|---|---|---|
| B1 | **Zero coordinates in the source.** `stop_without_location` is ERROR in the pinned validator → publish gate cannot open. See §3. | **Hard gate** |
| B2 | **`calendar.txt` has no source.** All 9 PDFs grepped for `monday|…|sunday|daily|except|alternate|weekly` → **zero hits**. Days-of-operation must be defaulted to Mon–Sun. Defensible for an intercity RTC, but it is the one required file that is *assumed*, not read. Presenting it as extracted would be a false provenance claim. | **Honesty gate** |
| B3 | **Parser fragility is worse than the brief said.** Not "2 of 9 files differ" — **8+ distinct header schemas**, and the column *order* changes: Lakhimpur is `Station \| Arrive \| Departure \| Km` (km last); Silchar is `STATION \| KM \| ARRIVAL TIME \| DEPATUAL TIME` (sic); Bongaigaon and Tinsukia each mix two layouts *within one file*. Per-document schema inference is mandatory. | High |
| B4 | **Jorhat and Tinsukia have NO km column** → `shape_dist_traveled` unavailable there, and the km-based coordinate plausibility gate (§3) does not apply. | Medium |
| B5 | **`0` is used as a NULL placeholder** in Silchar and Lakhimpur (`ARRIVAL TIME 0` at origin). A naive reader emits `00:00:00`. Must be typed as *absent*. | High |
| B6 | **Title/body direction contradictions.** Silchar service 4 is titled `SILCHAR TO SHILLONG` but its rows run SHILLONG (km 0) → SILCHAR ISBT (km 240). Jorhat service 2 titled `Jorhat - Namrup` runs NAMRUP → SONARI → SIVASAGAR → JORHAT. Trusting the title produces reversed trips. | High |
| B7 | **~3,500 time literals in ≥10 surface forms**: `7.15 AM`, `8.15AM`, `6.00 A.M`, `1:00 PM`, `12.00 Noon`, `12.15 noon`, `18.00 HRS`, bare `5.45`. | Medium |
| B8 | **Name normalisation** needed before multi-division dedup: Kaliabor/Kaliabar, Nagaon Bypass/Nagaon By Pass, Doomduma/Doomdooma, Jagiroad/Jagirod, Baihata/Bihata Chariali, `B/chariali`, ISBT / `Guwahati- ISBT` / Guwahati. | Medium |
| B9 | **`direct_download` host is a private commercial CDN** (`st.redbus.in`), not a `.gov.in` host, and the Tinsukia file already sits on a different path than its 8 siblings. Mitigation: host the *built* zip on a GitHub release (established practice, §5) and set `is_producer_url_unstable: "True"`. | Medium |
| B10 | **No open licence.** Footer verbatim, re-fetched this run: `Copyright © All Rights Reserved Assam State Transport Corporation, Government Of Assam.` No terms page, no GODL notice. See §4. | Legal — managed |
| B11 | **100% Latin script.** Zero Devanagari, zero Assamese/Bengali script anywhere in the 9 PDFs; place names arrive already transliterated. This *helps* the reader and *hurts* the multilingual pitch. | Narrative |
| B12 | **These are born-digital text PDFs**, fully `pdftotext`-extractable. They are not "a photographed/scanned paper timetable". | Narrative |
| B13 | **Intercity, not urban.** Guwahati → North Lakhimpur is 409 km / 9 hours. The urban-women-commuting rider-impact framing in §6 does not transfer cleanly and must be re-pointed. | Narrative |
| B14 | **Ridership UNVERIFIED.** No ridership figure is published on `astcbus.in` and none was retrieved from any primary source. **Do not state an ASTC ridership number on camera.** | UNVERIFIED |

**Robots compliance (checked, 2026-08-27) [A]:** `astcbus.in/robots.txt` disallows only `/api`, `/searchbus`, `/paymentPage` and booking/refund paths. `/schedules` is **not** disallowed. `st.redbus.in` has no `robots.txt` (404). All fetching was robots-compliant.

---

### BACKUP 1 — Chandigarh Transport Undertaking (CTU), Chandigarh Administration

**Scope:** tri-city Chandigarh / Mohali / Panchkula.

**Artifact URLs** — all four **retrieved** 2026-08-27, HTTP 200, `application/pdf`, SHA-256 recorded **[A]**:

| File | URL | Bytes | Pages | SHA-256 (first 16) |
|---|---|---:|---:|---|
| Local & tri-city | `https://chdctu.gov.in/cadmin/uploads/1785232444_e91748013c2b5c737091.pdf` | 756,044 | 11 | `f47c8f10c3e4c03e` |
| Inter-state long route | `https://chdctu.gov.in/files/2026-04/TimeTableLongRoute_220426.pdf` | 652,376 | 13 | `e4add2cb3471c8b4` |
| Sub-urban | `https://chdctu.gov.in/files/.../Sub_TimeTable_010623.pdf` | 360,445 | 5 | `83e0679c6c13c47a` |
| Airport shuttle | `https://chdctu.gov.in/files/.../airport-shuttle-bus-service_2024.pdf` | 485,149 | 2 | `886bfa6a447a1dee` |

**Contents.** Local PDF header verbatim: `CHANDIGARH TRANSPORT UNDERTAKING TIME TABLE OF CTU BUS SERVICES OPERATION LOCAL & TRY-CITY ROUTES / DEPOT NO-II,III &IV AS ON 25.07.2026`. Columns: `Sr.No | Route No | Description of Routes | Time | Frequency | Length in KM | No. of Buses`. The *Description* is a genuine ordered via-chain.

**Route count, re-derived [A]:** **68** local routes (serials 1–68, 68 distinct route numbers); the *No. of Buses* column sums to exactly **386** (a first pass gave 426; the 40 delta was a single regex false positive on the text `Sector-123   40`, isolated at line 283). Beyond that: 139 long-route timetable blocks / 306 departures; 38 sub-urban blocks / 276 departures; airport shuttle 38AS = 45 departure **triples** across 3 timing points, 36AS = 30 pairs.

**Why it is a good demo.**

- **Freshest artifact in the whole sweep** — `AS ON 25.07.2026`, one month old, and the date is bold on page 1, so freshness lands without narration.
- **The midnight crossing is literal and adjacent.** The last rows of the 38AS grid read `9.50 | 14.50 | 23.40`, then `10.10 | 15.10 | 24.00`, then `11.00 | 16.00 | 0.55`. `23.40 → 24.00 → 0.55` in adjacent cells of one published government table. **[A]**
- **Mixed formats in one file**: 38AS uses dots (`4.20`), 36AS on the next page uses colons (`04:30`).
- **Airport shuttle needs zero invention**: three genuine timing points per trip, offsets consistent row to row (4.20/4.40/5.20; 5.00/5.20/6.00).
- **Truly virgin**: GitHub API search returns `total_count 0` for `chandigarh gtfs`, `chandigarh transport bus`, and `ctu gtfs`; zero issues or PRs in the MobilityData repo mention Chandigarh. No community repo exists, unlike BMTC/Chennai/Mumbai. **[A]**

**Absence verified four ways [A]**, including a geometric guard: of all 6,496 feeds, exactly one bounding box *contains* Chandigarh (30.7333 N, 76.7794 E) — mdb-2867 Indian Railways, national-scale, rail, `inactive`. No bus operator's bbox covers the city.

**Blockers:**

| # | Blocker |
|---|---|
| C1 | **No coordinates.** ~150 distinct stops: 133 sector-pair tokens (`22/17`, `Sec-38/25`) plus 19 named landmarks. |
| C2 | **Sector-number collision across the tri-city.** 17 of 78 OSM sector numbers exist in *both* Chandigarh and Panchkula, up to 12.8 km apart (Sector 11 at 30.7599,76.7845 *and* 30.6848,76.8524). Naive lookup yields coordinates in the wrong city that **still pass the validator**. |
| C3 | **Interior stop times must be interpolated.** The local PDF gives an endpoint window plus a headway range, never per-stop times. That is exactly the flaw Delhi OTD confesses to. **The claim "no schedule is invented" is FALSE for the 68 local routes** (it is true only for the airport shuttle). |
| C4 | **`compose.py:484` hardcodes `timepoint: 1`** on every stop_time — i.e. "published/exact". For CTU that is a false provenance claim on every interior stop. Fix: `timepoint=1` on published endpoints, `timepoint=0` on interpolated interiors. That converts the weakness into a provenance demonstration. |
| C5 | **The Composer emits no `frequencies.txt` and no `shapes.txt`** — the fixed file set at `compose.py:37-38` is agency/stops/routes/trips/stop_times/calendar/calendar_dates/feed_info, and `grep -r frequencies headway/` returns nothing. The brief's "one PDF yields an entire city network as frequencies.txt" is **not supported by the current code**. Recommended fix: expand headways into explicit trips (~4,900 trips, ~120k stop_times rows), preserving the 8-file architecture and the model-free-arithmetic claim. |
| C6 | **Not a messy artifact.** `pdffonts` shows embedded Calibri/Arial TrueType; `pdfimages` lists **zero** images; Creator `Microsoft Word 2016`, Producer `www.ilovepdf.com`. Born-digital. The reader's genuine advantage here is confined to merged/rowspan cells — real (`Mins` appears 66 times, only 8 co-located with their number) but far less dramatic than a scan. |
| C7 | **Zero non-Latin script.** Devanagari 0, Gurmukhi 0; total non-ASCII is 5 en-dashes. |
| C8 | **Small.** Chandigarh UT ~1.06m; 68 routes / 386 buses vs BMTC's 6,272 schedules and 67,841 daily trips. ~1–2% of a flagship operator. Cannot carry a scale argument. |
| C9 | **Licence is permission-based.** `chdctu.gov.in/copyright-policy` verbatim: *"Material featured on this Portal may be reproduced free of charge after taking proper permission by sending a mail to us."* Not GODL. No anti-scraping clause anywhere (T&C and Privacy read in full; `/website-policies` and `/hyperlinking-policy` both soft-404). Contact `ctu-chd@nic.in`. |
| C10 | **Unstable producer URL** — the local timetable sits at an opaque hashed CMS path while its three siblings have stable named paths. Requires `is_producer_url_unstable: "True"`. |
| C11 | **Incomplete TLS chain on `chdctu.gov.in`** — curl accepts it, Node `fetch` rejects with *"unable to verify the first certificate"*. A live-demo fetch with a strict TLS client fails on camera. **Pre-cache the PDFs.** |
| C12 | **Mixed vintages**: local 25.07.2026, long-route 22.04.2026, sub-urban 01.06.2023. Exclude sub-urban and long-route, or mark staleness explicitly. |
| C13 | **OSM gives geometry, not stop order.** 110 bus route relations in the tri-city bbox, *all* tagged `operator="Chandigarh Transport Undertaking"`, covering 59 refs — but **0 of 110 have any ordered stop or platform members** (10,819 way members, all empty-role). 54 of 68 PDF routes have a matching relation; 14 do not. |

**Correction to the brief — do not say this on camera as written.** The claim that the local timetable is reachable "only via an unlabelled hashed link" and that "a rider cannot find it" is **overstated and was disproved**: the homepage megamenu anchor for that hashed path carries the visible link text **"Local Routes"**. A rider clicking the nav does reach the PDF. The accurate version: *the "Local Routes" nav item points at an opaque hashed CMS upload path while its three siblings get stable named paths, and the page route that ought to hold it (`/time-table/local-routes`) returns HTTP 200 with a body reading "404 Page Not Found"*. That is a fragility story, not a discoverability one. **[A]**

---

### BACKUP 2 — UPSRTC (Uttar Pradesh State Road Transport Corporation)

- Index: `https://upsrtc.up.gov.in/en/article/time-table` — declares `<base href="https://upsrtc.up.gov.in" />`, so links resolve to `/Time-Table-2/N.pdf`.
- Example: `https://upsrtc.up.gov.in/Time-Table-2/1.pdf`
- **946 per-route PDFs**, 1–2 pages each, with a real text layer. Structure: header rows `Sl.No / Depot / Region / Type Of Service`, then one block per stop with interleaved `ARR` and `DEP` rows and a cumulative `K.M.` column, in Up and Dn directions. The index HTML names each route (`MEERUT-MORADABAD`, `SULTAN PUR - AMETHI`, `LUCKNOW-JAIPUR`).

**Honesty note: this is Tier [B], not [A].** Four of the 946 PDFs were retrieved and text-extracted. The 946 count comes from the index page's link list, not from fetching all 946. Structural consistency across the full set is **UNVERIFIED**. Coordinate coverage, licence terms, and catalogue-absence via the trading-name guard have **not** been run for UPSRTC to the standard applied to ASTC and CTU. **If UPSRTC is promoted to primary, redo the full absence + licence + coordinate sweep first.**

---

### SECOND INPUT — the artifacts that actually prove the multimodal reader

Both ASTC and CTU are born-digital, Latin-script, `pdftotext`-friendly. Neither can demonstrate "reads a photographed timetable". These can:

**JKRTC / JKSRTC (Jammu & Kashmir)** — `https://www.jksrtc.co.in/timetable.php`; `https://www.jksrtc.co.in/pdf/timejammu.pdf` (5 pp, 1.47 MB) and `timekashmirr.pdf` (14 pp, 2.67 MB). **Opened with PyMuPDF: every page returns 0 text characters.** No text layer at all — only embedded raster images (page 3 of the Kashmir file alone carries 46 image objects). Rendered to PNG and read: Jammu p.2 is *"Timings of JKRTC Buses of Interstate Division, Jammu"*, a 47-row table (`S.No / Route / Departure Timings from GBS Jammu / Return Timings`). Kashmir p.4 is a photocopied *"TIME TABLE OF TOURIST SERVICES DIVISION, SRINAGAR"* **with a handwritten signature and date over the bottom of the table**. **[B]** — This is the single best HEADWAY input found in India.

**Kerala KSRTC City Circular (Thiruvananthapuram)** — `https://citycircular.keralartc.com/assets/doc/guide.pdf` (8,126,437 B, `/Image` + `DCTDecode` JPEG streams; `pdftotext` recovers **18 characters** from the whole file); `FPMC.pdf` (1,660,942 B, 5 chars); `SuperNH.pdf` (673,481 B, 2 chars); `BYPASSMC.pdf` (60,776 B — has a text layer but in a legacy non-Unicode Malayalam font, so extraction yields mojibake: `േകരള േ് േറാഡ് ടാൻസ്േപാർ് േകാർേറഷൻ`). **[B]** — the only genuinely non-Latin-script artifact retrieved anywhere in India.

**Recommended structure:** file the PR for **ASTC** (feed target — real times, clean absence), and use **JKRTC or Kerala** as a *second document in the demo* to show the reader handling a scan and a script the deterministic extractor cannot touch. Do not claim the second document produces the submitted feed unless it actually does.

### Located but NOT retrieved — do not cite as evidence **[C]**

- **AICTSL Indore** — `http://citybusindore.com/Index.php?page=bus-routes` resolves (A record 137.59.53.138) but every connection attempt timed out at 20s and 45s on both http and https. Format **UNVERIFIED**. `aicts.in` returns 404 at root and `/routes`; `aictsl.com`, `aictslindore.com`, `myaicts.in`, `ltms.aicts.in` are NXDOMAIN.
- **Uttarakhand UTC** — `https://utconline.uk.gov.in/route.aspx` **was** retrieved (406 KB, 568 `<tr>` route rows, `Route | From Station | To Station`). But `timetable.aspx` is a search form only; times sit behind `__VIEWSTATE` / `__VIEWSTATEENCRYPTED` postbacks per O-D pair. **No departure time was extracted.**
- **Haryana Roadways** — 25 depot-wise text-layer PDFs on the NIC S3WAAS CDN (`https://hartrans.gov.in/bus-time-table-depot-wise/`); 4 of 25 retrieved (Gurugram 23pp, Ambala 87pp, Hisar 46pp, Rohtak 28pp). Columns `Depot | From | To | Via | Departure Time | Type of Service | Operator | Service Days` — note it **has** service days, which ASTC lacks. There is also a Flutter web app at `https://timetable.hrtransport.org/` backed by `https://api.hrtransport.org/misInfo/TimetableList`; both endpoints return **HTTP 401** without the app's token. **[B]**
- **WBTC Kolkata** — retrieved and parsed, and **eliminated**: `https://wbtconline.in/wbtc-city-bus-routes` (55,961 B) has **130 route rows** and the PDF twin has **107** (they are *not* twins; the PDF is a stale Feb-2024 Excel export). But grepping both for `HH:MM` / `HH.MM` returns **zero matches**, as does `frequenc|headway|interval|timing|first bus|last bus`. **There are no times anywhere in the WBTC artifact.** A GTFS feed from it would be 100% invented schedule. **Do not use WBTC as a backup.** **[A]**

---

## 3. THE COORDINATE PROBLEM

### The gate, verified in the pinned validator source

HEADWAY vendors **gtfs-validator v8.0.1** (jar sha256 `19293ddd9b6f954f216d4f12054bd8a3232921751c4484339e339764a91000e2`). This run resolved tag `v8.0.1` → commit **`d74d7177f9f7c6bc7adc69508bb939362f2cf770`** and read the source **[A]**:

`main/src/main/java/org/mobilitydata/gtfsvalidator/validator/StopRequiredLocationValidator.java`:

```java
@GtfsValidationNotice(severity = ERROR, files = @FileRefs(GtfsStopSchema.class))
static class StopWithoutLocationNotice extends ValidationNotice { ... }
```
emitted when:
```java
if ((stop.locationType() == GtfsLocationType.STOP
        || stop.locationType() == GtfsLocationType.STATION
        || stop.locationType() == GtfsLocationType.ENTRANCE)
    && !stop.hasStopLatLon()) { ... }
```

`GtfsStopSchema.java` marks `stopLat()` and `stopLon()` `@ConditionallyRequired`. So: **any stop with `location_type` 0/1/2 and a missing lat or lon produces an ERROR-severity notice, and the publish gate cannot open.** `compose.py:323-324` writes `stop_lat`/`stop_lon` as an empty string when the value is `None` — so a `None` coordinate is not a silent omission, it is a guaranteed ERROR.

> ⚠️ **Version-pinning matters here.** The *current live* rules page — `https://gtfs-validator.mobilitydata.org/rules.html`, retrieved 2026-08-27 — lists `stop_without_location` in a **Deprecated** block ("This rule is deprecated from the validator since version undefined"). It is **not** deprecated in v8.0.1, which is what HEADWAY runs. State the version whenever this notice is mentioned on camera; a judge who checks the live docs will otherwise think the claim is stale.

### The plan for ASTC: three independent sources, one of which ships

**Ruling: the coordinates that ship in the feed come from open, redistributable data (GeoNames + OSM). Gemini does name work, not coordinate work.**

#### Source 1 (primary, shipped) — GeoNames `IN` dump

- `https://download.geonames.org/export/dump/IN.zip` — retrieved 2026-08-27, **15,747,002 bytes**, members `readme.txt` + `IN.txt`, **660,026 records**. **[A]**
- Licence, verbatim from `https://download.geonames.org/export/dump/readme.txt`: *"This work is licensed under a Creative Commons Attribution 4.0 License, see https://creativecommons.org/licenses/by/4.0/"*. **CC-BY 4.0 — redistributable with attribution.** **[A]**

**Measured coverage against the real 51 Guwahati-division station strings** (not a sample — the actual parsed set) **[A]**:

| Result | Count |
|---|---:|
| Exact match on name / ASCII name / alternate name | **38** |
| Fuzzy match ≥0.86 restricted to Assam (`admin1=03`) | **2** |
| **Resolved** | **40 / 51 = 78%** |
| Miss | 11 |

The 11 misses are all one of three kinds:
- **Bus-station landmarks GeoNames does not carry**: `Paltanbazar`, `ISBT`, `Guwahati- ISBT`. Searching all 1,883 Assam GeoNames records for `paltan`, `isbt`, `bus stand` returns **nothing**.
- **Road/junction points**: `Nagaon Bypass`, `Nagaon By Pass`, `Kohora`, `Bandordowa`.
- **Spelling variants** GeoNames stores differently: `Doomduma` → GeoNames has `Doom Dooma` (27.62792, 95.57832) and `Dum Duma` (27.56884, 95.55664); `Jamugurihat` → GeoNames has `Jāmuguri`; `Ghilamara`, `Demow` → no Assam record at all.

#### Source 2 (fills the misses) — OpenStreetMap

OSM carries exactly what GeoNames lacks: bus stands, ISBTs, and bypass junctions. Precedent for shipping OSM-derived coordinates in this catalogue is established and recent: **`bo-c-trufi-association-gtfs-3507.json`**, `"license": "https://www.openstreetmap.org/copyright"`, `is_official: "False"`, merged **2026-08-26 in 4 hours**. ODbL attribution is required in the feed's `ATTRIBUTION.md` and in `agency.txt`/README, not in every row.

Precision warning, measured on this corpus: **Nominatim free-text search silently returns wrong-but-plausible results.** `Jagiroad` resolved to *"Jagiroad Hardware Stores, A T Road, Pan Bazar, Guwahati"* — a shop ~55 km from the town. `Biswanath Chariali` returned a sub-divisional hospital. `Laluk` returned a road segment. And `Paltanbazar` — the origin of most Guwahati services and the most important stop in the feed — **missed entirely**, resolving only when re-queried as `Paltan Bazaar, Guwahati` (26.17923, 91.75127). **[A, prior run]**

Note the contrast, which is a genuine finding: **GeoNames got Jagiroad right** — 26.20782, 92.40601, the actual town, `P.PPL`. For intercity town-stops, the gazetteer beats the free-text geocoder. Use OSM only for the landmark class GeoNames cannot serve.

#### Source 3 (the check, not a source) — the document's own cumulative-km column

Every ASTC row carries cumulative km. That is an *in-document, model-free* geometric constraint. Three gates were built and tested against real coordinates this run **[A]**:

**Gate A — administrative fence.** Every stop must land in the expected state, or escalate. This gate *fires correctly*: `Janji` exact-matched a GeoNames record at **22.13016, 82.27941 with `admin1=37` (Chhattisgarh)** — a silently-wrong hit 1,200 km away that name matching alone accepts. Likewise `Shillong` resolved to `Shillong Plateau` (a landform, `admin1=18`, Meghalaya) rather than the city. Legitimate out-of-state stops exist (Siliguri and Jalpaiguri in West Bengal, Shillong in Meghalaya are on real ASTC services), so this gate must **escalate for review, never auto-reject.**

**Gate B — monotone km ordering.** Only 2 non-monotonic km transitions across the whole Guwahati division.

**Gate C — detour-ratio (document km ÷ crow-fly km).** Computed segment-by-segment over the flagship service using GeoNames coordinates:

| Segment | ratio | crow-fly km | doc km |
|---|---:|---:|---:|
| Paltanbazar→Khanapara | 0.85 | 11.8 | 10 |
| Khanapara→Kaliabor | 1.36 | 121.0 | 164 |
| Kaliabor→Tezpur | 1.21 | 16.6 | 20 |
| Tezpur→Balipara | **0.80** | 23.7 | 19 |
| Balipara→Jamugurihat | **0.45** | 26.8 | 12 |
| Jamugurihat→Biswanath Chariali | 1.07 | 21.4 | 23 |
| Biswanath Chariali→Gohpur | 1.21 | 49.7 | 60 |
| Gohpur→Narayanpur | 1.83 | 25.2 | 46 |
| Laluk→North Lakhimpur | 1.02 | 21.5 | 22 |

> ⚠️ **CORRECTION to a number in the brief.** The claimed "tight 1.18–1.71 band" does **not** reproduce with these coordinates. The measured per-segment band is **0.45 – 1.83, median 1.07**. Ratios below 1.0 are physically impossible (road distance cannot be shorter than the straight line), so `Tezpur→Balipara` (0.80) and `Balipara→Jamugurihat` (0.45) are *detections* — one of those coordinates or km values is wrong. **The per-segment gate has high recall and low precision: it must escalate, not reject.** The **endpoint** ratio is far better behaved: 409 doc km vs **261.7** crow-fly km, **ratio 1.56** — a plausible road detour factor, and a usable feed-level sanity check.
>
> **Honest negative result, carried forward from the prior run:** the km gate did **not** catch the bad Nominatim `Jagiroad` hit (ratio 1.34, coincidentally in-band because the error lay along the route axis near the terminus). **The km gate catches gross errors and misses along-route errors near endpoints.** Say this out loud rather than claiming a clean gate.

**Gate D — km-interpolation disambiguation.** This one works cleanly and is the best on-camera demonstration. `Jamuguri` has **two** Assam GeoNames candidates 100 km apart: (26.72171, 92.93113) and (26.38740, 93.96375). Interpolating linearly between the neighbouring stops by km — Tezpur (km 194) and Biswanath Chariali (km 248) — gives the expected point for km 225 at **(26.68640, 92.99897)**. Candidate A is **7.8 km** away; candidate B is **101.6 km** away. The document's own km column resolves the ambiguity with no model involved. **[A]**

#### Where Gemini fits — and where it must not

**gemini-3.7-flash does NOT produce the coordinates that ship.** Its jobs, all defensible:

1. **Name normalisation and transliteration** — mapping `Doomduma` ↔ `Doom Dooma`, `Kaliabar` ↔ `Kaliabor`, `B/chariali` ↔ `Biswanath Chariali`, `Nagaon By Pass` ↔ `Nagaon Bypass`. This is a text task on text the operator published; nothing about it is a coordinate.
2. **Escalation signalling** — where Maps grounding disagrees with the GeoNames/OSM pick, flag the stop for review. The signal gates human attention; the *value written to `stops.txt` is always the open-data value.*

> ⚠️ **The licence reason, stated honestly.** Publishing latitude/longitude obtained from Google Maps into a redistributable public GTFS feed runs into Google Maps Platform terms on caching and creating derived datasets. **The specific current text of those terms was NOT retrieved this run — this is a risk judgement, not a verified reading, and is marked UNVERIFIED.** The safe path costs nothing: GeoNames is CC-BY, OSM is ODbL, both are already-accepted sources in this catalogue, and the Gemini bonus (+0.2 for an extra Google AI model with a real visible job) is earned by the normalisation and escalation work regardless. **Before shipping any Maps-grounded coordinate, retrieve and read the current Maps Platform terms.**

#### How correctness is actually checked

The pipeline for each of the 51 stops:

1. GeoNames exact/alias match, restricted to `admin1=03` (Assam) unless the stop is a known out-of-state terminus. → 40/51.
2. OSM lookup for the remaining 11 (bus stands, ISBTs, bypass junctions), with an explicit admin-boundary filter.
3. **Gate A** administrative fence → escalate anything outside the expected states.
4. **Gate B** km monotonicity.
5. **Gate D** km-interpolation disambiguation whenever a name yields more than one candidate.
6. **Gate C** detour-ratio, per segment **and** endpoint-level → escalate, never auto-accept, never auto-reject.
7. Anything still unresolved or escalated is a **SourceClaim with bounded alternatives**, surfaced to the operator — which is HEADWAY's existing machinery, not a new subsystem.
8. Final: gtfs-validator v8.0.1 must return **ERROR = 0**. That is the publish gate, and it is a hard gate.

**Bounding box, computed from the 40 resolved Guwahati-division coordinates [A]:**
```
minimum_latitude   25.58333    maximum_latitude   27.83103
minimum_longitude  88.42851    maximum_longitude  95.66824
```
Wide, because Guwahati-division services legitimately reach Siliguri and Jalpaiguri (West Bengal) and Shillong (Meghalaya). The catalogue tooling recomputes this from `stops.txt` anyway (`helpers.py:403 extract_gtfs_bounding_box` = min/max of `stop_lat`/`stop_lon`, NaNs dropped) — do not hand-write it.

**Residual, stated plainly:** a geocoder is a **new subsystem**. HEADWAY today is reader → claims → composer → validator → PR, and nothing in it maps a place name to a coordinate. **This is the single largest build item for either target.**

---

## 4. LICENSING AND LEGITIMACY

### The ruling

**You may generate, self-host, and submit to the Mobility Database a GTFS feed derived from a publicly published Indian operator timetable without operator consent, provided you set `is_official="False"`, attribute the source, disclaim endorsement, and honour takedown.** That is not a risk-tolerant reading; it is the documented, quantified, current norm of the catalogue — **17 of the 20 existing Indian feeds already do exactly this**, and only 3 rows carry `is_official=True` (all three Hyderabad; one deprecated, one broken).

**You may NOT push that feed into Google Maps without the operator.** Google's intake form rejects "End User" submissions and requires an authorized signatory plus an endorsement document for the aggregator path. **Do not claim Google Maps ingestion as HEADWAY's terminal action.**

- ✅ Defensible: *"files a PR adding the operator to the Mobility Database — the catalogue Google Maps, Transit and OpenTripPlanner draw from."*
- ❌ Not defensible: *"gets it into Google Maps."*

### The legal spine

**Statute.** The Copyright Act, 1957 (Act 14 of 1957), retrieved 2026-08-27 from `https://copyright.gov.in/documents/copyrightrules1957.pdf` (956,958 bytes — **note the file is misnamed on the government site; its content is the Act, not the Rules**; first line reads `THE COPYRIGHT ACT, 1957 (14 OF 1957)`).

- **§2(o)** — *"'literary work' includes computer programmes, tables and compilations including computer databases."* A timetable **is** within the subject-matter class. Do not argue it is outside the Act.
- **§13(1)(a)** — copyright subsists in ***original*** works. Originality is a statutory precondition. **This is where the argument lives.**
- **§17(dd)** — a *public undertaking* is first owner. ASTC, CTU, BMTC, MSRTC, PMPML, BEST are public undertakings (limb (i) or (iii)), **not** "Government" under §2(k). **§28A** — 60 years from first publication.
- **§52(1)(q)** — the non-infringement carve-out covers only Official Gazette matter, Acts, reports laid before a legislature, and court judgments. ⚠️ **There is NO government-works exemption for a bus timetable. Do not build the defence on §52.** Anyone saying "it's a government document so it's free" is wrong.

**The actual defence — *Eastern Book Company v. D.B. Modak*.** Supreme Court of India, Civil Appeal 6472 of 2004, decided 12 December 2007; (2008) 1 SCC 1; AIR 2008 SC 809. Bench B.N. Agrawal & P.P. Naolekar; author Naolekar J. Full text retrieved 2026-08-27 from `https://indiankanoon.org/doc/1062099/`. **[B]** — *Indian Kanoon is a reproduction service, not the Court's own site; `https://main.sci.gov.in/judgment/judis/29325.pdf` was unreachable from this environment, so the text is verified-as-retrieved but not verified against the Registry copy.*

Verbatim holdings:

> *"To claim copyright in a compilation, the author must produce the material with exercise of his skill and judgment which may not be creativity in the sense that it is novel or non-obvious, but at the same time it is not a product of merely labour and capital."*

> *"To support copyright, there must be some substantive variation and not merely a trivial variation, not the variation of the type where limited ways/unique of expression available and an author selects one of them which can be said to be a garden variety."*

> *"There is a distinction between creation and discovery. The first person to find a particular fact has not created the fact, he or she has merely discovered its existence."*

The Court **expressly rejected "sweat of the brow"** and adopted the *CCH Canadian* skill-and-judgment standard.

**Applied:**

| Element | Protected in India? | Why |
|---|---|---|
| "Kaliabor, km 174, arr 11.00 AM" — **the fact** | **NO** | Discovered operational fact; facts may be copied at will. |
| The **set** of times, stops, headways | **NO** | Arrangement dictated by operational reality — "limited ways of expression… garden variety". |
| The **PDF layout, typography, column design, borders** | **PLAUSIBLY YES** | Layout can carry the minimal skill-and-judgment *EBC* requires. **Copy none of it.** |
| A **route map graphic** | **ASSUME YES** | A schematic map involves real design choice. Highest-risk input class. |
| Operator **name, logo, crest** | **YES** — trade mark | **Never embed.** |
| Your **photograph** of a paper timetable | Yours, but it embeds their layout | Use as input; show cropped evidence regions only; do not republish as a deliverable. |

> **The architectural sentence to say out loud:** *HEADWAY's Composer discards the expression and keeps only the facts — which is precisely the boundary Eastern Book Company draws.* That is an architectural argument, not a legal excuse.

**Residual risk that is NOT zero:** database/unfair-competition theories; contractual browse-wrap Terms of Use on the operator's own site (a *contract* question, not copyright — check the source site's terms before scraping); and the trade-mark exclusions.

### GODL-India — and why it does not cover ASTC

**Source:** Gazette of India, EXTRAORDINARY, Part I—Section 1, No. 42, New Delhi, Monday **13 February 2017**; MeitY notification **F.No. 8(2)/2013-EG-I** dated 10 February 2017; signed R.K. Sudhanshu, Jt. Secy. Retrieved 2026-08-27 from `https://data.gov.in/sites/default/files/Gazette_Notification_OGDL.pdf` (1,165,344 bytes). **[A]** — *no version number is stated in the instrument; the "GODL 1.0" label circulating online is UNVERIFIED against this text.*

- **§3** grants *"a worldwide, royalty-free, non-exclusive license to use, adapt, publish… and create derivative works (including products and services), for all lawful commercial and non-commercial purposes."*
- **§4(a)** attribution required; **§4(b)** a single linked attribution page is permitted for multi-source data — this is the clause that licenses one `ATTRIBUTION.md`; **§4(c)** *"The user must not indicate or suggest in any manner that the data provider(s) endorses their use and/or the user"*; **§4(d)** no warranty; **§4(e)** no continuity guarantee.
- **§6(c)/(d)** exclude *"Names, crests, logos and other official symbols of the data provider(s)"* and trade-marked material. → **Do not embed the operator's logo or crest in the feed, the artifact, or the demo. Scrub logos from any rendered timetable image shown on screen.** `agency_name` as a factual identifier is fine; the mark is not licensed.
- **§7** rights end on breach, auto-reinstated if cured within 30 days.

**GODL is the blanket default for datasets on the OGD Platform** (`https://data.gov.in/policies`, footer verbatim: *"The content published on data.gov.in is owned by the respective Ministry/State/Department/Organization and licensed under the Government Open Data License - India."*). **It is NOT automatically the licence of a timetable PDF on an STU's own website.** ASTC's footer says *"All Rights Reserved"*. So for ASTC the operative authority is *EBC*, not GODL. Say GODL only where it actually applies.

> ⚠️ The `data.gov.in` instance served this run carries the footer *"This is a sandbox environment created for testing and demonstration purposes only."* Treat page chrome from that host as UNVERIFIED; the Gazette PDF is a static file and is authoritative on its own.

### Exact disclosure language

**On screen, as a persistent lower-third during any segment showing operator material:**

> Unofficial community feed. Not produced or endorsed by Assam State Transport Corporation.
> Schedule facts extracted from ASTC's published timetables. Stop coordinates: GeoNames (CC BY 4.0) and OpenStreetMap (ODbL).

**In the feed itself** — `feed_info.txt` `feed_publisher_name`:
```
HEADWAY (unofficial community feed — not endorsed by Assam State Transport Corporation)
```

**In `README.md` and `ATTRIBUTION.md`, verbatim:**

```markdown
## Source and attribution

This is an UNOFFICIAL, community-produced GTFS feed. It is not produced, reviewed,
endorsed, or authorised by Assam State Transport Corporation or the Government of Assam.
The Mobility Database entry for this feed is marked `is_official: "False"`.

Schedule facts (stop names, arrival and departure times, route numbers, cumulative
distances) were extracted from timetables published by Assam State Transport Corporation
at https://astcbus.in/schedules (retrieved 2026-08-27). Only unprotected facts were
extracted; no page layout, typography, imagery, logo, crest or other mark of ASTC is
reproduced here, and the source PDFs are not mirrored by this project.

Stop coordinates are derived from:
  - GeoNames, https://download.geonames.org/export/dump/  (CC BY 4.0,
    https://creativecommons.org/licenses/by/4.0/)
  - OpenStreetMap contributors, https://www.openstreetmap.org/copyright  (ODbL)

Days of operation are NOT published in the source timetables. calendar.txt defaults to
daily (Monday-Sunday) service. This is an assumption made by this project, not a fact
read from the source, and it is recorded as such in the provenance record for every trip.

Takedown: if Assam State Transport Corporation asks for this feed to be withdrawn, it
will be removed from publication and the Mobility Database entry marked inactive, without
argument. Contact: <maintainer email>.
```

**The `calendar.txt` paragraph is not optional.** It is the difference between a provenance system and a provenance claim.

---

## 5. THE SUBMISSION RUNBOOK

**Repository:** `MobilityData/mobility-database-catalogs` — Apache-2.0, default branch `main`. HEAD at time of writing: **`77848fa9` "Add Cochabamba, Bolivia (#1640)", 2026-08-26T19:04:50Z**. **[A]**

### Step 0 — Preconditions

- The built GTFS zip must be **publicly live at a stable URL before you run the tooling** — `add_gtfs_schedule_source` downloads and parses it (`representations.py:724 build` → `download_dataset` → `is_readable(load_func=load_gtfs)`).
- gtfs-validator v8.0.1 must return **ERROR = 0** on that exact zip. This is HEADWAY's own gate and it comes first.
- **Signed CLA.** CLAassistant comments on every PR (observed on PR #1107).

### Step 1 — Mirror path: where the zip lives

Do **not** point `direct_download` at `st.redbus.in`. Host the built zip on a **GitHub release or raw URL**. This is established, recently-accepted practice **[A]**:

| Precedent | direct_download host | Outcome |
|---|---|---|
| `bo-c-trufi-association-gtfs-3507.json` | `raw.githubusercontent.com/trufi-association/…/cochabamba.gtfs.zip` | merged **2026-08-26 in 4 hours**, `is_official:"False"`, OSM-derived, `license: openstreetmap.org/copyright` |
| `in-maharashtra-pmpml-gtfs-3137.json` | `raw.githubusercontent.com/croyla/pmpml-gtfs/…` | merged |
| `in-chennai-transport-gtfs-3360.json` | `raw.githubusercontent.com/ungalsoththu/ChennaiGTFS/…` | merged |
| `in-gujarat-vapi-city-bus-service-gtfs-3426.json` | `github.com/shubhamvelani/VapiGTFS/releases/download/v1.0.0/Vapi_GTFS.zip` | merged |

**HEADWAY does not need its own CDN.** Set `is_producer_url_unstable: "True"` (mdb-3361 does), since the upstream PDFs sit on a commercial CDN.

### Step 2 — Fork, branch, environment

```bash
gh repo fork MobilityData/mobility-database-catalogs --clone
cd mobility-database-catalogs
git checkout -b feat/add-astc-assam

# README-documented setup (Python 3.9+):
brew install GDAL spatialindex          # required by gtfs_kit, imported at module scope in tools/helpers.py
python3.9 -m venv env && source env/bin/activate
pip install -r requirements.txt
```

### Step 3 — Allocate the `mdb_source_id` (do this at filing time, not before)

**The rule is a file count, not `max(id)+1`.** `tools/representations.py:107`:
```python
@staticmethod
def identify(catalog_root):
    return sum(len(files) for path, sub_dirs, files in os.walk(catalog_root)) + 1
```
`catalog_root` = `catalogs/sources` (`constants.py:41`) — it walks schedule **and** realtime together.

**Measured 2026-08-27 [A]:** 2,475 schedule + 1,032 realtime = **3,507 files → next id = 3508**. The `mdb_source_id` values are exactly the contiguous set 1…3507, zero gaps, zero duplicates.

> ⚠️ **LIVE RACE — re-check before filing.** Open PR **#1641 "Import Arroyobus"** (`ianktc`, not a draft, updated 2026-08-26T20:15:22Z) **already claims 3508, 3509, 3510 and 3511** — confirmed by reading its file list this run. It is the *only* non-draft source PR currently open. **If #1641 merges first, HEADWAY's next free id is 3512.**

The contiguity test is real (`tests/test_integration.py`):
```python
def test_catalogs_gtfs_source_ids_are_incremental():
    source_ids = [source[MDB_SOURCE_ID] for source in get_sources(data_type=ALL).values()]
    assert sorted(source_ids) == list(range(1, len(source_ids) + 1))
```
An id too low collides (fails uniqueness *and* contiguity); an id too high leaves a gap (fails contiguity). Either way `integration-tests (3.9)` goes red. Maintainers do fix this — PR #1640's commit list includes `ianktc: increment to next available stable id`, pushed directly to the contributor's branch — so a stale id costs a round trip, not a rejection. **But on camera you want it right first time.**

Re-derive immediately before filing:
```bash
python - <<'PY'
import os
n=sum(len(f) for _,_,f in os.walk('catalogs/sources'))
print('files:',n,'next id:',n+1)
PY
gh pr list --repo MobilityData/mobility-database-catalogs --state open --json number,title,files
```

### Step 4 — Add the source (use the tooling, not a hand-written file)

CONTRIBUTING.md: *"adding or updating sources manually is possible, although not recommended."*

```python
from tools.operations import *
add_gtfs_schedule_source(
    provider="Assam State Transport Corporation",
    country_code="IN",
    subdivision_name="Assam",
    municipality="Guwahati",
    direct_download_url="https://github.com/<owner>/headway-feeds/releases/download/astc-v1/astc_guwahati_gtfs.zip",
    license_url=None,                 # ASTC publishes no open licence; omit rather than invent one
    name="Assam State Transport Corporation — Guwahati division intercity services, "
         "compiled by HEADWAY from ASTC's published division timetables",
    feed_contact_email="<maintainer email>",
    status="active",
    features=[],
    redirects=[],
    is_official="False",
    is_producer_url_unstable="True",
)
```

**Filename produced** (`constants.py:23` template, rendered by `helpers.py:create_filename`, each component through `helpers.py:323 normalize` — text before first comma → lowercase → alnum/space/hyphen only → whitespace collapsed to `-` → unidecode):

```
in-assam-assam-state-transport-corporation-gtfs-<id>.json
```

**`urls.latest` is derived, never invented** (`helpers.py:260 create_latest_url`):
```
https://storage.googleapis.com/storage/v1/b/mdb-latest/o/in-assam-assam-state-transport-corporation-gtfs-<id>.zip?alt=media
```
**The stem must match the JSON filename exactly.** This is the single most common defect in merged files — `in-chennai-transport-gtfs-3360.json` carries a `latest` URL with a different stem, and the Sri Lanka file lost its `-3490` suffix in both.

**Serialization** (`helpers.py:29 to_json`): `json.dump(obj, fp, indent=4, ensure_ascii=False)` — 4-space indent, **no trailing newline** (PR #1640's patch ends `\ No newline at end of file`), non-ASCII left literal.

**Expected file** (id shown as 3508; re-derive at filing):

```json
{
    "mdb_source_id": 3508,
    "data_type": "gtfs",
    "provider": "Assam State Transport Corporation",
    "name": "Assam State Transport Corporation — Guwahati division intercity services, compiled by HEADWAY from ASTC's published division timetables",
    "feed_contact_email": "<maintainer email>",
    "is_official": "False",
    "is_producer_url_unstable": "True",
    "features": [],
    "status": "active",
    "location": {
        "country_code": "IN",
        "subdivision_name": "Assam",
        "municipality": "Guwahati",
        "bounding_box": {
            "minimum_latitude": 25.58333,
            "maximum_latitude": 27.83103,
            "minimum_longitude": 88.42851,
            "maximum_longitude": 95.66824,
            "extracted_on": "2026-08-2XTXX:XX:XX+00:00"
        }
    },
    "urls": {
        "direct_download": "https://github.com/<owner>/headway-feeds/releases/download/astc-v1/astc_guwahati_gtfs.zip",
        "latest": "https://storage.googleapis.com/storage/v1/b/mdb-latest/o/in-assam-assam-state-transport-corporation-gtfs-3508.zip?alt=media"
    },
    "redirect": []
}
```

**Schema notes that bite** (`https://raw.githubusercontent.com/MobilityData/mobility-database-catalogs/main/schemas/gtfs_schedule_source_schema.json`, draft-07, retrieved 2026-08-27):

- Top-level `required`: `mdb_source_id`, `data_type`, `provider`, `location`, `urls`.
- `urls.required`: `direct_download`, `latest`. `urls.license` is **optional** and must be a **URL**, not an SPDX id.
- `location.bounding_box` requires **all five** keys; the four coordinates are `oneOf` all-numbers or all-`null`, but `extracted_on` is always required.
- `is_official`, `is_producer_url_unstable`, `is_seasonal` are **strings** `"True"`/`"False"`, not booleans.
- `authentication_type` enum 0/1/2. If 1 or 2 → `authentication_info` **and** `api_key_parameter_name` are required; if 0 → both are **forbidden**. **Cleanest is to omit all three**, as PR #1640 does.
- **`authentication_type` 1 or 2 cannot be added from a fork** (CONTRIBUTING.md). HEADWAY's feed must be unauthenticated.

Note for calibration: the catalogue tolerates unvalidated geometry — `in-gujarat-vapi-city-bus-service-gtfs-3426.json` ships a bounding box at 45.2–45.5 N, 12.2–12.4 E (**Venice, Italy**) and it is still in `main`. Nobody checks the bbox against the country. Do not take that as licence to be sloppy; take it as evidence the bar for acceptance is low and the bar for *being right* is yours.

### Step 5 — Pre-flight, without GDAL

The six integration assertions can be reproduced with `jsonschema` alone — no GDAL, no catalogue tooling.
A standalone `preflight.py` implementing all six was written and validated against a real checkout:

```bash
python preflight.py <checkout>
# PASS  schedule=2475 realtime=1032 next_free_mdb_source_id=3508
```
A candidate India file at id 3508 was generated and re-run through preflight on 2026-08-27: **PASS** (then deleted). **The write path is proven end to end.** **[A]**

Then let CI run the canonical suite:
```bash
pytest                                     # includes tests/test_integration.py (6 tests)
pytest --ignore=./tests/test_integration.py  # what CI runs for unit tests
```
Style: Black via `.pre-commit-config.yaml`, flake8 in CI. A data-only PR passes trivially.

### Step 6 — Open the PR

```bash
git add catalogs/sources/gtfs/schedule/in-assam-assam-state-transport-corporation-gtfs-<id>.json
git commit -m "feat: Add Assam State Transport Corporation GTFS Source [SOURCES]"
git push -u origin feat/add-astc-assam
gh pr create --draft \
  --title "feat: Add Assam State Transport Corporation (Guwahati) GTFS Source [SOURCES]" \
  --body-file PR_BODY.md
```

**PR conventions, verified [A]:**

- **Conventional Commits: CONFIRMED.** `.github/semantic.yml` configures `zeke/semantic-pull-requests` with `titleOnly: true` — the **title** is validated; commits are ignored.
- **`[SOURCES]` suffix: CONFIRMED, and it is a workflow trigger, not a lint.** `.github/workflows/direct_download_urls_test_for_sources.yml:13`:
  ```yaml
  if: contains(github.event.pull_request.title, '[SOURCES]')
  ```
  Without it the download-and-parse validation **never runs**. Enforcement is soft in practice (only 5 of 13 merged 2026 outsider PRs carried it; #1640 had neither prefix nor suffix and merged in 4 hours) — **use it anyway**, because you want that check visibly green on camera.
- **Open as a draft first**, then convert to ready-for-review and request a MobilityData reviewer. CONTRIBUTING.md: *"if you need to modify your contribution after this step, you will be asked to convert your pull request back to draft."*
- `.github/workflows/greetings.yml` auto-posts *"Thanks for opening this pull request! You're awesome."* plus a Slack invite; `greetingsmerge.yml` posts *"Congrats on getting your first pull request merged!"* — free, real, on-camera moments.

### Step 7 — What to expect

README, verbatim: *"Updating the CSV is a community effort. Contributors either create a PR here directly or they submit an update through the form, which MobilityData then adds as a PR within approximately a week of submission… we usually do updates 1-3 times a month."*

Measured outsider-PR cohort (authors with ≤3 PRs in the last 400, so no maintainer self-merges), 2026: **93% ever merge, median 3.96 days, 50% merge within 4 days, ZERO still open.** The only outsider PR ever filed for an Indian feed — `Neo2308`, PR #1107 "Add schedule for Indian Railways" — opened 2025-11-01, **merged 2025-11-12 (11 days)**, +25 lines, 1 file, maintainer comment *"Thanks for this great contribution @Neo2308!"*

**Do not promise a merge inside the hackathon window.** Promise a filed, CI-green, correctly-numbered PR — that is the deliverable you control.

---

## 6. RIDER IMPACT

### The opening line, ready to lift

> **The bus is the largest vehicular commute mode for urban Indian women — 22% of urban women who travel to work go by bus, more than two-wheeler, auto, train and car. India has one active catalogued transit feed per 161 million people. France has one per 79,804.**

### The commuting data, computed from primary microdata

**Source:** Census of India 2011, Table **B-28** — *"Other workers by distance from residence to place of work and mode of travel to place of work, INDIA"*. Catalogue id 13954, file `DDW-0000B-28.xlsx`.
`https://censusindia.gov.in/nada/index.php/catalog/13954` → `https://censusindia.gov.in/nada/index.php/catalog/13954/download/17067/DDW-0000B-28.xlsx`
Office of the Registrar General & Census Commissioner, India. Downloaded and parsed 2026-08-27. **[A]** *(note: `censusindia.gov.in` serves an incomplete TLS chain; fetching requires relaxed verification.)*

Denominator = "All Modes" − "No travel" (the published "All Modes" total includes workers who do not travel and must not be used raw).

**All India — 140,233,922 "other workers" travel to work:**

| Mode | Persons | Share |
|---|---:|---:|
| On foot | 45,266,568 | 32.28% |
| Bicycle | 26,272,609 | 18.73% |
| Two-wheeler | 25,464,837 | 18.16% |
| **Bus** | **22,901,495** | **16.33%** |
| Train | 7,015,528 | 5.00% |
| Auto/taxi | 6,040,414 | 4.31% |
| Car/jeep/van | 5,476,050 | 3.90% |

**Urban India — 87,974,767 travel to work:**

| Mode | Persons | Share | **Share among urban women commuters** |
|---|---:|---:|---:|
| On foot | 26,717,480 | 30.37% | 45.42% |
| Two-wheeler | 19,094,104 | 21.70% | 10.77% |
| Bicycle | 15,053,364 | 17.11% | 4.43% |
| **Bus** | **13,241,229** | **15.05%** | **22.03%** |
| Train | 4,824,201 | 5.48% | 5.36% |
| Auto/taxi | 3,929,597 | 4.47% | 6.21% |
| Car | 4,215,686 | 4.79% | 5.07% |

**3,165,868** urban women commuted by bus in 2011; **4,752,178** nationally. Urban public transport (bus + train) = **20.53%** of urban commuters who travel; **bus carries 2.7× more urban commuters than train**, yet Indian Railways has a feed (lapsed, "unofficial") while most bus operators have none.

> **Caveat to state honestly on camera or in the README:** B-28 covers *"other workers"* only (it excludes cultivators and agricultural labourers) and counts *commute-to-work* trips only — not education, healthcare or social travel. **It is a floor, not total ridership.**

### Accessibility and the no-smartphone rider

**Source:** Census of India 2011, Table **C-20**, id 43369, `DDW-C20-0000.xlsx`, `https://censusindia.gov.in/nada/index.php/catalog/43369`, retrieved 2026-08-27. **[A]**

| Disability | All India | Urban India |
|---|---:|---:|
| **Total disabled** | **26,814,994** | 8,178,636 |
| In seeing | 5,033,431 | 1,529,873 |
| In hearing | 5,072,914 | 1,679,186 |
| **In movement** | **5,436,826** | 1,401,085 |
| In speech | 1,998,692 | 694,752 |
| Multiple | 2,116,698 | 532,194 |

**5.03 million Indians cannot see.** A printed paper timetable nailed to a bus shelter is unreadable to every one of them. A GTFS feed is machine-readable by definition — that is the accessibility argument, and it needs no embellishment.

### Measured harm, peer-reviewed

- **Chennai: ~35% of young women reported harassment on public transport in the previous six months** (n=530). *Journal of Victimology and Victim Justice* (2020), DOI `10.1177/2516606920927303`; OA PDF `https://journals.sagepub.com/doi/pdf/10.1177/2516606920927303`
- **Lucknow: harassment victimisation is "most prevalent in buses and increases with the frequency of use of public transport"** (n=200). Borrion & Tripathi, *Crime Prevention & Community Safety* (2017), DOI `10.1057/s41300-017-0029-0`; OA PDF `https://discovery.ucl.ac.uk/1557686/1/Borrion_Tripathi2017_Article_SexualHarassmentOfStudentsOnPu.pdf`
  → **This is the causal hinge: risk scales with exposure.** Unknown headways force longer waits and more trips in the dark. Schedule data reduces exposure directly.
- **Chennai, n=3,816 women + 944 men**; *"at night, lighting is generally poor, especially in the narrow side streets…"*; NCRB IPC §509 recorded 9,796 "insult to modesty" incidents. Natarajan et al., *Crime Science* (2016), gold OA: `https://crimesciencejournal.biomedcentral.com/articles/10.1186/s40163-016-0054-9`
- **Waiting-time perception is worse for women and is driven by security, not shelter aesthetics.** Lagune-Reutler / Loukaitou-Sideris et al., *Transportation Research Part A* (2016), DOI `10.1016/j.tra.2016.04.012`, OA PDF `https://conservancy.umn.edu/bitstreams/8c4f1ae0-d334-48d6-a515-765b30b3eeb1/download`. And *Journal of Public Transportation* 13(3) 2010 (n=749): riders *"would prefer short, predictable waits… in a safe, if simple or even dreary, environment over long waits for late-running vehicles in even the most elaborate station"* — `https://digitalcommons.usf.edu/cgi/viewcontent.cgi?article=1159&context=jpt`
  → **"Short, predictable waits" is precisely what a valid GTFS feed buys.**
- **Bangalore, BMTC-specific service gaps and women's safety:** Sundararajan, *Transportation Research Procedia* (2017), DOI `10.1016/j.trpro.2017.05.283`, OA PDF `https://www.sciencedirect.com/science/article/pii/S2352146517305902/pdf`
- **Greater Mumbai: measured spatial inequity in public-transport access to government healthcare.** Accessibility built from travel time and number of transit stops; the transit-aware measure *"explains the coverage and usage of healthcare services better than the traditional accessibility measure"*; the burden falls on the socially vulnerable *"who mostly rely on government healthcare services."* *Journal of Transport Geography* (2021), DOI `10.1016/j.jtrangeo.2021.103123`.
  → **Direct support for the dialysis-centre escalation already built into HEADWAY's outcome differ.** The literature says stop-level accuracy is what makes healthcare-access modelling work — which is exactly what a corrupted `stop_times` row destroys.

### Operator scale, from the operator's own site

**BMTC "at a glance", as on 18 July 2026** — `https://mybmtc.karnataka.gov.in/35/bmtc-glance/en` **[A]**: 6,272 schedules · 6,955 vehicles (incl. 1,768 e-buses under GCC) · **67,841 trips/day** · 12.28 lakh service-km/day · ₹7.19 crore daily traffic revenue · 50 depots · 48 bus stations · 28,866 staff. BMTC publishes no ridership figure on this page.

### ⚠️ Numbers you must NOT use

- **National daily bus boardings — UNVERIFIED.** `morth.gov.in` is an Angular SPA returning an identical 40,262-byte shell for *every* path including direct `.pdf` URLs; the Road Transport Year Book is not reachable by direct fetch. ASRTU (`asrtu.org`) and CIRT (`cirtindia.com`) publish only tenders and notices. **Do not put a national daily bus-ridership number in the video.**
- **ASTC ridership — UNVERIFIED.** Nothing published on `astcbus.in`.
- **Real-time-information effect sizes — UNVERIFIED.** Brakewood, Macfarlane & Watkins, *TR-C* (2015), DOI `10.1016/j.trc.2015.01.021`, and Watkins et al., *TR-A* (2011), DOI `10.1016/j.tra.2011.06.010` both exist and their titles, venues and citation counts (157 and 371) are confirmed — **but both are paywalled and neither Crossref, OpenAlex nor Semantic Scholar returned an abstract. The effect sizes were not verified.** Cite by title only. Do not state a percentage from memory.
- **The intercity mismatch.** If ASTC is the target, the urban-women-commuting framing does not transfer cleanly — Guwahati → North Lakhimpur is a 409 km, 9-hour coach service. Either re-point the human case to intercity access (§6's healthcare-access and no-smartphone material transfers fine) or use the urban figures strictly as the *national context*, not as ASTC's riders.

---

## 7. INDIA TRANSIT DATA LANDSCAPE

### Who is already doing this: about six hobbyists and two MobilityData staff. Nobody official.

Commit-history check on every India JSON file (GitHub API, 2026-08-27) **[A]**: almost every Indian feed was added **by MobilityData staff importing a community GitHub repo** — not by the community member, and never by the agency.

- `ianktc` — PR #1258 (2026-02-05, APSRTC), #1417 (2026-05-11, Ahmedabad / PMPML / Mumbai / Hubli-Dharwad), #1540 (2026-07-20, Chennai + TGSRTC), #1629 (2026-08-25, unstable-URL flag)
- `emmambd` — PR #1580 "Italy, India, Bulgaria, Poland updates" (2026-07-31 → 2026-08-04, Vapi)
- **The only outsider PR ever filed for an Indian feed:** `Neo2308` (P. Radha Krishna), PR #1107, merged in 11 days.
- `Vonter`, `croyla`, `shubhamvelani`, `ungalsoththu` were each checked against the repo's PR list: **0 PRs each.** They publish the data; they never file the catalogue entry.

### The producers (all GitHub, verified 2026-08-27) **[A]**

| Repo | ⭐ | last push | licence | covers |
|---|---:|---|---|---|
| `Vonter/bmtc-gtfs` | 42 | 2026-07-12 | none | BMTC Bengaluru |
| `Vonter/bmrcl-gtfs` | 1 | 2026-08-17 | – | **Namma Metro — NOT catalogued** |
| `croyla/mumbai-gtfs` | 2 | 2026-08-19 | MIT-0 | BEST, TMT, KDMT |
| `croyla/pmpml-gtfs` | 1 | 2026-08-06 | MIT-0 | Pune/PCMC |
| `croyla/amd-gtfs` | 0 | 2026-08-13 | MIT | AMTS + Janmarg |
| `croyla/hdbrts-gtfs` | 0 | 2026-08-24 | MIT | Hubli-Dharwad BRTS |
| `croyla/rrl-gtfs` | 0 | 2026-08-13 | MIT-0 | Rajkot Rampath |
| `croyla/ksrtc-gtfs` | 0 | 2026-08-25 | – | **Karnataka KSRTC — NOT catalogued** |
| `croyla/jctsl-gtfs` | 0 | 2025-11-07 | – | **Jaipur — NOT catalogued** |
| `croyla/dvg-gtfs` | 0 | 2026-06-05 | – | **Davangere — NOT catalogued** |
| `Neo2308/indianrailways-gtfs` | 3 | 2026-05-30 | none | Indian Railways |
| `Neo2308/apsrtc-gtfs` | 1 | 2026-05-30 | none | APSRTC |
| `Neo2308/aictsl-gtfs` | 0 | 2026-05-30 | – | **Indore — NOT catalogued** |
| `ungalsoththu/ChennaiGTFS` | 4 | 2026-04-27 | MIT | Chennai MTC |
| `ungalsoththu/chennai-gtfs` | 0 | 2026-03-25 | – | **CMRL Chennai Metro — NOT catalogued** |
| `shubhamvelani/VapiGTFS` | 0 | 2026-07-06 | none | Vapi |
| `Neelabho/kolkata-bus-gtfs` | 0 | 2026-02-28 | – | **Kolkata — NOT catalogued** |
| `quantum2code/kolkata_gtfs` | 0 | 2025-10-31 | – | **Kolkata — NOT catalogued** |
| `Jungle-Bus/KochiTransport` | 0 | 2022-09-27 | none | Kochi (French OSM collective) |
| `openbangalore/gtfs-data` | 2 | **2015-10-02** | MIT | BMTC — dead, still catalogued as mdb-2013 |

**Verified absent from all 20 India rows** (string-matched on provider / municipality / URL): bmrcl/namma metro, ksrtc, jctsl/jaipur, kolkata, aictsl/indore, davangere, cmrl, nagpur, surat, lucknow, kanpur, bhopal, coimbatore, visakhapatnam, guwahati, patna, chandigarh, bhubaneswar, navi mumbai, thane, noida, gurugram, mysuru, thiruvananthapuram, kozhikode, vadodara, nashik, dehradun, vijayawada, warangal, trichy, upsrtc, rsrtc, tnstc, wbtc, osrtc, bsrtc, hrtc, punbus, **astc**, keralartc. **Present: tgsrtc and apsrtc only.**

### The nearest neighbour — cite it, do not collide with it

**`https://github.com/WRI-Cities/static-GTFS-manager`** — 159 ⭐, 57 forks, GPL-3.0, created 2018-03-29, **last push 2022-06-05**, not archived, issues still trickling in (#175 opened 2025-11-07, #174 2025-08-22). Origin story: `https://datameet.org/2018/04/13/a-tool-for-composing-transit-schedules-data-in-static-gtfs-standard/` (Nikhil VJ, WRI India + KMRL): *"On 17 March this year, Kochi Metro Rail Ltd became India's first transit agency to publish static GTFS feed."*

It is a **browser GUI for humans to hand-type schedules into GTFS**. It requires Chrome and a Python backend and has been dormant four years. It does **not** read a photographed timetable, does not do provenance, does not gate on the validator, and does not file a PR. **It is HEADWAY's nearest neighbour and it is dormant and manual.** Cite it as prior art; do not claim to be the first to think about Indian GTFS tooling.

### Adjacent efforts that are NOT collisions (all checked 2026-08-27) **[B]**

- **Datameet** `https://datameet.org/` — alive as a blog; the community's transit output is that one 2018 post. `datameet.org/community/` → 404.
- **Beckn / ONDC / Namma Yatri** — a *transaction* protocol for booking and discovery, not a schedule-publication standard. No GTFS artefact. Different layer; no collision.
- **Chalo** (`https://chalo.com/`) and **Tummoc** — private closed apps running live tracking for many Indian city buses. Both 200 OK; **neither exposes GTFS** (`chalo.com/gtfs.zip` → 404). **They are the reason agencies feel they have "done data" without publishing any.**
- **Data{Meet} OpenCity** `https://data.opencity.in/` — a live CKAN. `package_search?q=GTFS` returns **exactly 2** datasets, both Telangana. Bengaluru's BMTC entry there is KML/CSV of stops and routes from **2012**, no timetable.
- **OpenStreetMap India** — `wiki.openstreetmap.org/wiki/India/Public_Transport` → **404**. Whether an organised OSM-India transit mapping group is currently active is **UNVERIFIED** (no live page reachable without search).

### Government portals

- **`data.gov.in` — currently unusable.** Returns *"The portal is undergoing maintenance. We expect to resume normal operations by 16th August"* and *"This is a sandbox environment created for testing and demonstration purposes only."* Every query (`GTFS`, `bus route`, `timetable`) renders "No Result Found". The v2 API at `api.data.gov.in/lists` responds (237,471 records) but **ignores the `q` parameter**, returning the same 40 junk rows regardless. **Whether data.gov.in holds any GTFS is UNVERIFIED — its search is broken, not proven empty.**
- **`https://otd.delhi.gov.in/` — the most complete Indian government transit-data programme, and it is not properly in the Mobility Database.** Run by GNCT Delhi Dept of Transport with IIIT-Delhi. `/data/static` (DTC/cluster bus): STOPS 3,464 · ROUTES 543 · STOP TIMES 378,324 · TRIPS 16,562, **"Last Updated: June 20, 2024"**. `/data/staticDMRC` (Delhi Metro): STOPS 262 · ROUTES 36 · STOP TIMES 411,686 · TRIPS 17,997, **"Last Updated: Aug. 10, 2023"**. `/documentation` carries a candid warning: *"The arrival and departure times of buses as mentioned in stop_times.txt is not accurate and is a rough estimate generated by assuming a constant speed of travel."* `/data/realtime` serves **GTFS-Realtime VehiclePositions** at `/api/realtime/VehiclePositions.pb?key=YOUR_PRIVATE_KEY` — confirmed live, **HTTP 401** without a key. **This is the only official Indian GTFS-RT feed found, and India has 0 realtime feeds catalogued.** Download is gated behind a "state your purpose" modal, which is exactly why both catalogued Delhi rows point at transitland mirrors and are both `inactive`, one 404ing. *(An API-key feed is `authentication_type` 1 or 2 → cannot be added from a fork → must go through `https://mobilitydatabase.org/contribute`.)*
- **`https://tgsrtc.telangana.gov.in/open-data`** — a real, well-drafted open-data policy: *"General Transit Feed Specification (GTFS) is the format that has been selected"*, granting a *"limited worldwide licence to use, adapt, reproduce, store, display, copy, transmit and redistribute"*, permitting commercial use, requiring attribution *"Contains data provided by TGSRTC"*. **But the download sits behind a Google Form**, hence `is_producer_url_unstable:"True"` on mdb-3361 and its opencity.in mirror.
- **`https://kochimetro.org/open-data/`** — page live; its only data link is a **tinyurl** (`https://tinyurl.com/kmrlopendata`) that redirects to a TinyURL interstitial, not a ZIP. **India's flagship open-transit-data agency has a broken public path.**
- **`https://hmrl.co.in/open-data.html`** — returns **HTTP 406** to any non-browser client (bot-blocked). Liveness **UNVERIFIED**.
- Probed and dead/empty: `data.telangana.gov.in` (200 but no CKAN API); `data.karnataka.gov.in`, `openbengaluru.in`, `bmlta.karnataka.gov.in`, `kochiopenmobility.com/.org` — **all DNS-nonexistent**; `cumta.tn.gov.in` — 200, an empty shell.
- Across 26 RTC/agency homepages probed for `GTFS` / `open data` / `developer API`: **three publish GTFS in the whole country** — TGSRTC, Delhi OTD, KMRL (broken).

### Is HEADWAY's contribution welcome or duplicative?

**Welcome, and not duplicative — for ASTC specifically.**

1. **The catalogue explicitly invites it.** README: *"Updating the CSV is a community effort."* Measured outsider merge rate 93%, median 3.96 days, zero PRs left open. No prior-approval requirement, no anti-bot policy; their own workflow authors PRs as `github-actions[bot]`.
2. **`is_official="False"` is the documented, normal state** — the schema's own words: *"False if a feed is created by researchers or partners unaffiliated with the agency or municipality."* 17 of 20 India rows are already that.
3. **Assam is genuinely virgin.** No repo, no PR, no issue, no row under any name.
4. **The community that produces these feeds does not file the catalogue entries.** `Vonter`, `croyla`, `ungalsoththu`, `shubhamvelani` have zero PRs between them. HEADWAY automating the *last mile* — validate, host, file, correctly numbered — is complementary to their work, not competitive with it.

**Where you must be careful not to overclaim:** do not target BMTC, Mumbai, Chennai, Pune, Ahmedabad, Hubli-Dharwad or Rajkot. Those are `croyla`'s and `Vonter`'s live, actively-maintained feeds, and filing over them would be a duplicative land-grab against people doing this work for free. Assam, Chandigarh, UP, Haryana, J&K, Kolkata, Goa and Uttarakhand are all genuinely uncovered.

---

## 8. OPEN QUESTIONS AND UNVERIFIED CLAIMS

### Must be resolved before filming or filing

| # | Item | Status | Action |
|---|---|---|---|
| 1 | **Google Maps Platform terms** on caching / derived datasets, as applied to publishing Maps-grounded coordinates in a redistributable GTFS feed | **UNVERIFIED** — the current terms text was not retrieved this run | Retrieve and read before any Maps-derived coordinate ships. Default plan (§3) avoids the question entirely. |
| 2 | **`mdb_source_id` at filing time** | Currently 3508, but PR **#1641 claims 3508–3511** and is open and non-draft | Re-derive with the file-count rule immediately before pushing; scan open PRs. |
| 3 | **National daily bus ridership** | **UNVERIFIED** — MoRTH is an SPA that shells every path; ASRTU and CIRT publish nothing usable | Do not state a number. |
| 4 | **ASTC ridership** | **UNVERIFIED** — nothing published | Do not state a number. |
| 5 | **Effect sizes** in Brakewood 2015 and Watkins 2011 | **UNVERIFIED** — both paywalled, no abstract from Crossref / OpenAlex / Semantic Scholar | Cite by title only, or obtain the PDFs. |
| 6 | ***EBC v. D.B. Modak* text** verified only against Indian Kanoon | **[B]** — `main.sci.gov.in` unreachable from this environment | Verify against the Registry copy before quoting verbatim in a legal-sounding claim. |
| 7 | **ASTC's terms of use / browse-wrap contract** | Footer says "All Rights Reserved"; **no terms page was found**, so no browse-wrap contract was found either — but absence of a page is not proof of absence of terms | Re-check `astcbus.in` for any terms/legal page before filing. |
| 8 | **`calendar.txt` for ASTC** | Confirmed to have **no source** in the document | Must be declared an assumption in feed_info, README and on camera. Non-negotiable. |
| 9 | **`compose.py:484` hardcodes `timepoint: 1`** | Confirmed in code | Must change if CTU is used; consider a provenance-typed timepoint for ASTC too, since arrival at the origin stop and departure at the terminus are absent in the source. |
| 10 | **No `frequencies.txt` / `shapes.txt` emitter** | Confirmed: `grep -r frequencies headway/` returns nothing; file set fixed at `compose.py:37-38` | The "one PDF yields an entire city network as frequencies.txt" demo beat is **not supported by current code**. Either build it or drop the claim. |

### Weaker-than-briefed findings, carried forward so they are not re-discovered on camera

- **The detour-ratio gate band is 0.45–1.83, not 1.18–1.71** (§3). It fires on 3 of 9 flagship segments. It is an *escalation* signal, not an acceptance test.
- **The km gate demonstrably misses along-route coordinate errors near termini** (the Nominatim `Jagiroad` case, ratio 1.34, in-band and wrong).
- **ASTC parser fragility is 8+ schemas with variable column order**, not "2 of 9 files differ".
- **ASTC route count is 310 services corpus-wide by this run's count, not 244** — the two counts use different definitions (numbered item lines vs lines matching `N. Service:`). Pick one definition and state it.
- **CTU discoverability claim is overstated and was disproved** — the "Local Routes" nav link is visible and works (§2).
- **Neither ASTC nor CTU has any non-Latin script.** Devanagari 0, Assamese 0, Gurmukhi 0. The multilingual/multimodal beat must come from JKRTC or Kerala KSRTC, or be dropped.
- **Neither ASTC nor CTU is a scanned or photographed artifact.** Both are born-digital text PDFs that `pdftotext` largely handles. If the pitch says "a photographed/scanned paper timetable", the demo must actually show one — JKRTC's `timejammu.pdf` returns **0 text characters on every page** and is the artifact that earns that sentence.

### Not retrieved at all — do not cite as evidence

- **AICTSL Indore** — `citybusindore.com` resolves but times out on every connection attempt (20s and 45s, http and https). Format **UNVERIFIED**. **[C]**
- **UTC Uttarakhand timetable data** — behind `__VIEWSTATEENCRYPTED` postbacks; **no departure time was extracted**. The route list (568 rows) *was* retrieved. **[C for times, B for routes]**
- **Haryana Roadways structured API** — `https://api.hrtransport.org/misInfo/TimetableList` and `/TimetableStationList/` both return **HTTP 401** without the Flutter app's token. **[C]**
- **`opendata.iiitd.edu.in`** — the licence URL cited by mdb-1262 and mdb-3360 — was **network-unreachable** (DNS/route failure, not a 404). Possibly dead. **UNVERIFIED**.
- **UPSRTC beyond 4 of 946 PDFs** — structural consistency, coordinate coverage, licence terms and the trading-name absence guard are all **UNVERIFIED** for this operator. Redo the sweep before promoting it.

### Reproduction artifacts on disk

Every artifact below is fetched from a public URL, so the table names the SOURCE rather than a path on one
machine. `headway.pipeline.render.fetch()` caches each into `.tmp/sources/` and records its sha256.

| Source | What |
|---|---|
| `st.redbus.in/Images/WL/ASTC/schedules_new/*.pdf` (+ `/schedule/` for Tinsukia) | All 9 ASTC division PDFs; §3 lists each URL with its byte count and page count |
| `chdctu.gov.in` route PDFs | The 4 CTU Chandigarh PDFs, SHA-256 recorded in §4 |
| `wbtconline.in` route listing | WBTC — eliminated, no times published |
| Kerala RTC and JCTSL route PDFs | Raster-only; no text layer |
| `github.com/MobilityData/mobility-database-catalogs` | Cloned for the pre-flight re-checks in §5 |
| `egazette.gov.in` GODL notification; Copyright Act 1957 | Licence basis, §7 |
| `download.geonames.org/export/dump/IN.zip` | GeoNames India, 15,747,002 bytes, 660,026 records, CC BY 4.0 |