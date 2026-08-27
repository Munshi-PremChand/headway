"""The publish gate: MobilityData's gtfs-validator, run on the exact bytes.

Two properties matter and both were bugs earlier:

1. **The gate must not open on a validator that never ran.** A previous
   Makefile swallowed stderr and then read a report file; if the validator
   crashed, a stale report could still read ERROR=0. Here a missing or
   unparseable report raises, and the run fails closed.
2. **The gate must bind the BYTES it validated.** The report carries the
   sha256 of the exact zip that was validated, so a certificate cannot claim
   feed A was validated while feed B was published.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

VALIDATOR_JAR = "gtfs-validator-8.0.1-cli.jar"
VALIDATOR_VERSION = "8.0.1"
# sha256 of the vendored jar, verified on download 2026-08-26.
VALIDATOR_SHA256 = "19293ddd9b6f954f216d4f12054bd8a3232921751c4484339e339764a91000e2"
JRE_IMAGE = "eclipse-temurin:21-jre"


class ValidatorUnavailable(RuntimeError):
    """The validator could not be run at all. Never treat this as a pass."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _jar_path() -> Path:
    return _repo_root() / "vendor" / VALIDATOR_JAR


def verify_jar() -> str:
    """Confirm the vendored jar is the exact binary we claim to gate on."""
    p = _jar_path()
    if not p.exists():
        raise ValidatorUnavailable(f"validator jar missing at {p}")
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    if digest != VALIDATOR_SHA256:
        raise ValidatorUnavailable(
            f"validator jar sha256 mismatch: expected {VALIDATOR_SHA256}, got {digest}")
    return digest


def _java_works() -> bool:
    """macOS ships a /usr/bin/java STUB that exists but has no runtime, so
    `shutil.which("java")` is truthy on a machine with no JRE. Actually run it."""
    if not shutil.which("java"):
        return False
    try:
        return subprocess.run(["java", "-version"], capture_output=True,
                              timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _java_cmd(work: Path, feed_rel: str, out_rel: str) -> list[str]:
    """Prefer a real local JRE; fall back to a container."""
    jar = _jar_path()
    if _java_works():
        return ["java", "-jar", str(jar), "-i", str(work / feed_rel),
                "-o", str(work / out_rel)]
    if shutil.which("docker"):
        root = _repo_root()
        return ["docker", "run", "--rm",
                "-v", f"{root}:/repo", "-v", f"{work}:/work", "-w", "/work",
                JRE_IMAGE, "java", "-jar", f"/repo/vendor/{VALIDATOR_JAR}",
                "-i", f"/work/{feed_rel}", "-o", f"/work/{out_rel}"]
    raise ValidatorUnavailable(
        "neither a java runtime nor docker is available to run gtfs-validator")


def run_validator(feed_bytes: bytes, *, timeout: int = 300) -> dict[str, Any]:
    """Validate exactly these bytes. Fails closed on any problem."""
    jar_digest = verify_jar()
    feed_sha = hashlib.sha256(feed_bytes).hexdigest()

    # Stage inside the repo, not the system tempdir. On macOS a tempdir lives
    # under /var/folders, which colima does not share with the Docker VM — the
    # container would see FileNotFoundException for a file that plainly exists.
    staging = _repo_root() / ".tmp"
    staging.mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory(dir=staging) as td:
        work = Path(td)
        (work / "gtfs.zip").write_bytes(feed_bytes)
        cmd = _java_cmd(work, "gtfs.zip", "report")
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

        report_path = work / "report" / "report.json"
        if not report_path.exists():
            raise ValidatorUnavailable(
                "gtfs-validator produced no report — the gate must NOT open.\n"
                f"exit={proc.returncode}\nstderr={proc.stderr[-1500:]}")
        try:
            raw = json.loads(report_path.read_text())
        except json.JSONDecodeError as exc:
            raise ValidatorUnavailable(f"unparseable validator report: {exc}") from exc

    # ------------------------------------------------------------------
    # THE MOST IMPORTANT CHECK IN THIS FILE.
    #
    # gtfs-validator writes a report even when it CANNOT LOAD THE FEED AT ALL.
    # MEASURED 2026-08-27: feeding it 29 bytes of garbage produced a report with
    # zero notices, which naively reads as ERROR=0 and opened the publish gate.
    # Every "ERROR=0" claim in the demo would have been false, and a judge
    # dropping in a bad file would have exposed it live.
    #
    # Discriminator, measured on both paths:
    #   good feed -> exit 0, summary has counts / files / agencies
    #   garbage   -> exit 255, summary has NONE of those and 0 notices
    # Both guards are applied; neither alone is trusted.
    # ------------------------------------------------------------------
    summary = raw.get("summary", {}) or {}
    counts = summary.get("counts") or {}
    files = summary.get("files") or []

    if proc.returncode != 0:
        raise ValidatorUnavailable(
            f"gtfs-validator exited {proc.returncode} — the feed was not "
            f"validated, so the gate must NOT open.\n"
            f"stderr={proc.stderr[-1200:]}")

    if not counts or not files:
        raise ValidatorUnavailable(
            "gtfs-validator produced a report with no parsed-feed evidence "
            "(summary.counts / summary.files absent). It did not read the "
            "feed, so zero notices does NOT mean zero errors.")

    parsed_rows = sum(v for v in counts.values() if isinstance(v, int))
    if parsed_rows <= 0:
        raise ValidatorUnavailable(
            f"gtfs-validator parsed zero rows ({counts}); refusing to treat "
            f"an empty parse as a pass.")

    notices = raw.get("notices", [])
    totals: dict[str, int] = {}
    for n in notices:
        totals[n["severity"]] = totals.get(n["severity"], 0) + n["totalNotices"]

    report = {
        "validator_version": VALIDATOR_VERSION,
        "validator_sha256": jar_digest,
        "feed_sha256": feed_sha,
        "feed_bytes": len(feed_bytes),
        "errors": totals.get("ERROR", 0),
        "warnings": totals.get("WARNING", 0),
        "infos": totals.get("INFO", 0),
        "codes": sorted({(n["severity"], n["code"]) for n in notices}),
        "publish_gate": "OPEN" if totals.get("ERROR", 0) == 0 else "CLOSED",
        # Proof the validator actually read the feed, carried into the release
        # certificate so "ERROR=0" is never assertable without it.
        "parsed": {"counts": counts, "files": sorted(files),
                   "agencies": summary.get("agencies", []),
                   "validation_seconds": summary.get("validationTimeSeconds")},
    }
    return report
