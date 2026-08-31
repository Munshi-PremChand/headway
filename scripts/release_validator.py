#!/usr/bin/env python3
"""Validate a frozen release manifest and emit `.munshi/RELEASE_REPORT.json`.

WHY THIS EXISTS. The ship gate refuses any outward-facing action — publishing
the repository, deploying to Cloud Run, filing the submission — unless a valid
release report is on disk. No validator existed for this project, so the gate
was unopenable by construction and the only remaining move was an override. A
gate whose key does not exist teaches you to bypass gates. This is the key.

WHAT IT CHECKS, fail-closed on each:

  1. The artifact exists and hashes to `artifact.sha256`. For a source release
     the artifact is `git archive HEAD` — the exact tracked bytes, reproducible
     by anyone from the commit, and independent of git's internal object
     format.
  2. The manifest names the commit, and that commit is the current HEAD. A
     manifest that approved a different commit has expired.
  3. The working tree is CLEAN. Approving a hash while uncommitted edits sit on
     disk is how approved bytes and pushed bytes diverge.
  4. `approval.status == "approved"`, with a named human approver and a UTC
     timestamp, and `approval.artifactSha256` equals `artifact.sha256`. An
     approval must name the EXACT hash, so any rebuild silently invalidates a
     prior go rather than inheriting it.
  5. Every `checks.*` flag is true AND carries a non-empty evidence string. A
     bare `true` with no evidence is how a check becomes a formality.
  6. No tracked file matches the secret patterns. This is re-run at validation
     time rather than trusted from the manifest, because the scan is cheap and
     the cost of being wrong is permanent.

The report is always written, so a failure is inspectable rather than merely
loud. Exit 0 and `valid: true` only when every invariant holds.

    python3 scripts/release_validator.py
    python3 scripts/release_validator.py --manifest .munshi/RELEASE_MANIFEST.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Patterns that must never appear in a tracked file. Deliberately broader than
# "credentials": a billing account id is not a secret but is nobody's business.
SECRET_PATTERNS = [
    (r"ya29\.[0-9A-Za-z_-]{20,}", "google oauth access token"),
    (r"AIza[0-9A-Za-z_-]{30,}", "google api key"),
    (r"gh[pousr]_[0-9A-Za-z]{20,}", "github token"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY", "private key"),
    (r'"private_key"\s*:', "service account key"),
    (r"\b[0-9A-F]{6}-[0-9A-F]{6}-[0-9A-F]{6}\b", "gcp billing account id"),
]


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args],
                          capture_output=True, text=True,
                          check=True).stdout.strip()


def artifact_sha256() -> str:
    """sha256 of `git archive HEAD` — the exact tracked bytes at this commit."""
    proc = subprocess.run(
        ["git", "-C", str(REPO), "archive", "--format=tar", "HEAD"],
        capture_output=True, check=True)
    return hashlib.sha256(proc.stdout).hexdigest()


def scan_secrets() -> list[str]:
    findings: list[str] = []
    files = [f for f in _git("ls-files").splitlines() if f]
    for rel in files:
        p = REPO / rel
        try:
            text = p.read_text(errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue
        for pattern, label in SECRET_PATTERNS:
            if re.search(pattern, text):
                findings.append(f"{rel}: {label}")
    return findings


def validate(manifest_path: Path) -> tuple[bool, list[str], dict]:
    failures: list[str] = []
    detail: dict = {}

    if not manifest_path.exists():
        return False, [f"manifest missing at {manifest_path}"], detail
    m = json.loads(manifest_path.read_text())

    # 1 + 2: the artifact is this commit, and its bytes hash as approved.
    head = _git("rev-parse", "HEAD")
    detail["headCommit"] = head
    declared_commit = (m.get("artifact") or {}).get("commit")
    if declared_commit != head:
        failures.append(
            f"manifest approves commit {declared_commit}, HEAD is {head} — "
            f"the approval has expired, re-freeze and re-approve")

    actual = artifact_sha256()
    detail["artifactSha256"] = actual
    declared = (m.get("artifact") or {}).get("sha256")
    if declared != actual:
        failures.append(
            f"artifact sha256 mismatch: manifest says {declared}, "
            f"`git archive HEAD` hashes to {actual}")

    # 3: nothing uncommitted.
    dirty = _git("status", "--porcelain")
    detail["workingTreeClean"] = not dirty
    if dirty:
        failures.append(
            "working tree is not clean; approved bytes would differ from "
            f"pushed bytes:\n{dirty[:400]}")

    # 4: a human approved THIS hash.
    ap = m.get("approval") or {}
    if ap.get("status") != "approved":
        failures.append(f"approval.status is {ap.get('status')!r}, not 'approved'")
    if not str(ap.get("approver") or "").strip():
        failures.append("approval.approver is empty — an approval needs a name")
    if not str(ap.get("approvedUtc") or "").strip():
        failures.append("approval.approvedUtc is empty")
    if ap.get("artifactSha256") != actual:
        failures.append(
            "approval names a different artifact hash than the one on disk; "
            "a go does not carry over to rebuilt bytes")

    # 5: every check true, every check evidenced.
    checks = m.get("checks") or {}
    evidence = m.get("checkEvidence") or {}
    if not checks:
        failures.append("manifest declares no checks")
    for name, passed in sorted(checks.items()):
        if not passed:
            failures.append(f"check {name!r} is false")
        if not str(evidence.get(name) or "").strip():
            failures.append(f"check {name!r} has no evidence recorded")

    # 6: re-scan, never trust the manifest's word for it.
    found = scan_secrets()
    detail["secretScanFindings"] = found
    if found:
        failures.append(f"secret scan found {len(found)}: {found[:5]}")

    return (not failures), failures, detail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=".munshi/RELEASE_MANIFEST.json")
    ap.add_argument("--out", default=".munshi/RELEASE_REPORT.json")
    args = ap.parse_args()

    manifest_path = REPO / args.manifest
    ok, failures, detail = validate(manifest_path)

    report = {
        "schemaVersion": 1,
        "generatedUtc": dt.datetime.now(dt.timezone.utc)
                          .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "manifest": args.manifest,
        "valid": ok,
        "criticalFindings": len(failures),
        "failures": failures,
        "detail": detail,
    }
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")

    print(f"{'VALID' if ok else 'INVALID'} — {out.relative_to(REPO)}")
    print(f"  artifact sha256 : {detail.get('artifactSha256')}")
    print(f"  HEAD            : {detail.get('headCommit')}")
    print(f"  tree clean      : {detail.get('workingTreeClean')}")
    for f in failures:
        print(f"  FAIL: {f}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
