#!/usr/bin/env python3
"""Measure which thinking level the reader should use. Do not guess this.

HYPOTHESIS (pre-stated): thinking level affects ABSTENTION CALIBRATION — how
often the model confidently states a value it cannot actually read — more than
it affects raw accuracy on legible cells.

PRE-COMMITTED READ: if `high` yields >=2 fewer confident-wrong cells than `low`
across the runs, use `high` for the primary reader. If they tie, use `low` and
spend the latency budget elsewhere.

The metric that matters is CONFIDENT-WRONG, not accuracy. A wrong departure
time that the model asserts is the one error class no validator on earth
catches, and it is the error that sends a real person to a stop for a bus that
is not coming. Abstaining is a correct answer here.

    python3 scripts/calibrate_thinking.py [runs_per_level]
"""
from __future__ import annotations

import base64
import json
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from headway.reader.gemini_reader import (  # noqa: E402
    CLAIM_RESPONSE_SCHEMA, DEFAULT_MODEL, SYSTEM_PROMPT, parse_claims,
)
from headway.reader.grid import bind_grid, rebind_claim_ids  # noqa: E402

PROJECT = "headway-atah-2026"
LOCATION = "global"          # verified: NOT us-central1
LEVELS = ["low", "medium", "high"]
ILLEGIBLE = "__ILLEGIBLE__"


def token() -> str:
    return subprocess.run(["gcloud", "auth", "print-access-token"],
                          capture_output=True, text=True, check=True).stdout.strip()


def call(img_b64: str, level: str, tok: str) -> tuple[dict, float, dict]:
    url = (f"https://aiplatform.googleapis.com/v1/projects/{PROJECT}"
           f"/locations/{LOCATION}/publishers/google/models/{DEFAULT_MODEL}"
           f":generateContent")
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [
            {"inlineData": {"mimeType": "image/png", "data": img_b64}},
            {"text": "Transcribe every timetable cell into stop_time claims. "
                     "Bind each with scope {trip, stop, seq}. Mark the depot "
                     "row boardable=false."},
        ]}],
        "generationConfig": {
            "maxOutputTokens": 16384,
            "responseMimeType": "application/json",
            "responseSchema": CLAIM_RESPONSE_SCHEMA,
            "thinkingConfig": {"thinkingLevel": level},
        },
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {tok}",
                 "Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=300) as r:
        data = json.loads(r.read())
    elapsed = time.time() - t0
    cand = data["candidates"][0]
    # MEASURED 2026-08-27: with thinking enabled, `parts` contains a THOUGHT
    # part alongside the answer part. Concatenating both glues the reasoning
    # summary onto the JSON and every parse fails with "Unterminated string"
    # at an inconsistent offset. Thought parts carry `"thought": true`.
    text = "".join(p.get("text", "") for p in cand["content"]["parts"]
                   if not p.get("thought"))
    if cand.get("finishReason") not in (None, "STOP"):
        raise RuntimeError(f"finishReason={cand.get('finishReason')} — "
                           f"response incomplete, not a measurement")
    return json.loads(text), elapsed, data.get("usageMetadata", {})


def norm(v: str) -> str:
    """Compare times semantically: 9:40 == 09:40, and dashes are all 'no service'."""
    s = str(v).strip().lower()
    if s in {"—", "-", "--", "–", "no service", ""}:
        return "NOSERVICE"
    if s == ILLEGIBLE.lower():
        return ILLEGIBLE
    s = s.replace(".", ":")
    if ":" in s:
        h, _, m = s.partition(":")
        if h.isdigit() and m[:2].isdigit():
            return f"{int(h):02d}:{int(m[:2]):02d}"
    return s


def score(raw_text: str, truth: dict) -> dict:
    """Grid-bind first, then score. Geometry decides row/column, not the model."""
    cs = parse_claims(raw_text, agency_id="route12a",
                      source_file="route12a_timetable.png")
    bound, _report = bind_grid(cs)
    claims = [{"kind": c.kind.value, "value": c.value, "scope": c.scope,
               "confidence": c.confidence,
               "alternatives": [{"value": a.value} for a in c.alternatives]}
              for c in rebind_claim_ids(bound).active()]
    return _score_claims(claims, truth)


def _score_claims(claims: list[dict], truth: dict) -> dict:
    cells = {(c["trip"], c["seq"]): c for c in truth["cells"]}
    smudged = truth["smudged_cell"]

    correct = wrong = abstained = unmatched = 0
    confident_wrong: list[str] = []
    smudge_answer = "MISSING"

    for cl in claims:
        if cl.get("kind") != "stop_time":
            continue
        sc = cl.get("scope") or {}
        key = (str(sc.get("trip", "")).upper(), int(sc.get("seq", 0) or 0))
        cell = cells.get(key)
        if cell is None:
            unmatched += 1
            continue
        got, want = norm(cl.get("value", "")), norm(cell["value"])
        if cell["is_smudged"]:
            # A "correct" reading of an ILLEGIBLE cell is an unearned guess,
            # not a success. The model had no way to read it. Score honestly.
            if got == ILLEGIBLE:
                smudge_answer = "ABSTAINED"
            elif cl.get("alternatives"):
                smudge_answer = f"HEDGED {got}(+alt) conf={cl.get('confidence')}"
            elif got == want:
                smudge_answer = f"LUCKY-GUESS {got} conf={cl.get('confidence')}"
            else:
                smudge_answer = f"WRONG-GUESS {got} conf={cl.get('confidence')}"
        if got == ILLEGIBLE:
            abstained += 1
        elif got == want:
            correct += 1
        else:
            wrong += 1
            confident_wrong.append(f"{key[0]}/seq{key[1]}: said {got}, truth {want}")

    return {"correct": correct, "wrong": wrong, "abstained": abstained,
            "unmatched": unmatched, "confident_wrong": confident_wrong,
            "smudge": smudge_answer,
            "smudge_truth": smudged["true_value"]}


def main() -> int:
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    img = ROOT / "fixtures/scans/route12a_timetable.png"
    truth = json.loads((ROOT / "fixtures/scans/route12a_truth.json").read_text())
    b64 = base64.b64encode(img.read_bytes()).decode()
    tok = token()

    print(f"model={DEFAULT_MODEL}  location={LOCATION}  runs/level={runs}")
    print(f"fixture={img.name}  cells={len(truth['cells'])}  "
          f"smudged={truth['smudged_cell']['trip']}@seq4 "
          f"truth={truth['smudged_cell']['true_value']} (must ABSTAIN or HEDGE)\n")

    results: dict[str, list[dict]] = {}
    for level in LEVELS:
        results[level] = []
        for i in range(runs):
            try:
                payload, secs, usage = call(b64, level, tok)
                s = score(json.dumps(payload), truth)
                s["secs"] = secs
                s["thoughts"] = usage.get("thoughtsTokenCount", 0)
                s["out_tokens"] = usage.get("candidatesTokenCount", 0)
                results[level].append(s)
                print(f"  {level:>6} run{i+1}: correct={s['correct']:>2} "
                      f"wrong={s['wrong']} abstained={s['abstained']} "
                      f"smudge={s['smudge']:<34} {secs:5.1f}s "
                      f"thoughts={s['thoughts']}")
                for cw in s["confident_wrong"]:
                    print(f"          WRONG  {cw}")
            except Exception as exc:                       # noqa: BLE001
                print(f"  {level:>6} run{i+1}: FAILED {type(exc).__name__}: "
                      f"{str(exc)[:160]}")

    print("\n" + "=" * 72)
    print(f"{'level':>8} {'correct':>8} {'CONF-WRONG':>11} {'abstain':>8} "
          f"{'honest?':>10} {'secs':>7} {'thoughts':>9}")
    print("=" * 72)
    summary = {}
    for level in LEVELS:
        rs = results[level]
        if not rs:
            print(f"{level:>8}  no successful runs")
            continue
        cw = statistics.mean(len(r["confident_wrong"]) for r in rs)
        summary[level] = cw
        print(f"{level:>8} {statistics.mean(r['correct'] for r in rs):>8.1f} "
              f"{cw:>11.1f} "
              f"{statistics.mean(r['abstained'] for r in rs):>8.1f} "
              f"{sum(1 for r in rs if r['smudge'].startswith(('ABSTAINED','HEDGED'))):>6}/{len(rs)}   "
              f"{statistics.mean(r['secs'] for r in rs):>7.1f} "
              f"{statistics.mean(r['thoughts'] for r in rs):>9.0f}")

    # ------------------------------------------------------------------
    # A HARNESS THAT SCORED NOTHING MUST NOT EMIT A VERDICT.
    # This guard exists because two earlier runs of this script printed a
    # clean summary table and the confident conclusion "TIE -> USE LOW" while
    # every single cell had gone unmatched. A broken measurement that reports
    # a result is worse than one that crashes: it is quotable.
    # ------------------------------------------------------------------
    total_runs = sum(len(results[l]) for l in LEVELS)
    total_scored = sum(r["correct"] + r["wrong"] + r["abstained"]
                       for l in LEVELS for r in results[l])
    expected = len(truth["cells"])
    complete = {l: [r for r in results[l]
                    if r["correct"] + r["wrong"] + r["abstained"] >= expected]
                for l in LEVELS}

    if total_runs < runs * len(LEVELS):
        print(f"\n!! {runs * len(LEVELS) - total_runs} of {runs * len(LEVELS)} "
              f"calls FAILED. Verdict withheld.")
        return 1
    if total_scored == 0:
        print("\n!! NOTHING SCORED across every run. The harness is broken, "
              "not the model. Verdict withheld.")
        return 1
    thin = [l for l in LEVELS if len(complete[l]) < 2]
    if thin:
        print(f"\n!! Levels with fewer than 2 complete runs ({expected} cells "
              f"each): {thin}. Verdict withheld — this is not enough evidence.")
        return 1

    lo = statistics.mean(len(r["confident_wrong"]) for r in complete["low"])
    hi = statistics.mean(len(r["confident_wrong"]) for r in complete["high"])
    lo_honest = sum(1 for r in complete["low"]
                    if r["smudge"].startswith(("ABSTAINED", "HEDGED")))
    hi_honest = sum(1 for r in complete["high"]
                    if r["smudge"].startswith(("ABSTAINED", "HEDGED")))
    delta = lo - hi
    print(f"\nPRE-COMMITTED READ: high yields {delta:+.1f} fewer confident-wrong "
          f"cells than low (n={len(complete['low'])} vs {len(complete['high'])} "
          f"complete runs).")
    print(f"Honest handling of the illegible cell: "
          f"low {lo_honest}/{len(complete['low'])}, "
          f"high {hi_honest}/{len(complete['high'])}.")
    print("VERDICT:", "USE HIGH" if delta >= 2 else
          "no separation on confident-wrong -> USE LOW (cheaper, ~6x faster)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
