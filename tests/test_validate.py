"""Publish-gate tests. The gate must fail CLOSED on every failure mode.

The bug these defend against is the worst one available to this project: a
gate that reports OPEN when the validator never actually ran. That would make
every "ERROR=0" claim in the video and the write-up false.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from headway.composer.compose import compose  # noqa: E402
from headway.pipeline.validate import (  # noqa: E402
    VALIDATOR_SHA256, ValidatorUnavailable, run_validator, verify_jar,
)
from headway.schema.claims import ClaimSet  # noqa: E402

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/claims/sample_agency.json"
START = date(2026, 8, 24)
JAR = Path(__file__).resolve().parents[1] / "vendor/gtfs-validator-8.0.1-cli.jar"
needs_jar = pytest.mark.skipif(not JAR.exists(), reason="validator jar not vendored")


def feed_bytes() -> bytes:
    raw = json.loads(FIXTURE.read_text())
    cs = ClaimSet.from_dicts(raw["agency_id"], raw["claims"])
    return compose(cs, feed_start=START, horizon_days=120).to_zip_bytes()


@needs_jar
def test_jar_is_the_exact_binary_we_claim():
    """If the jar is swapped, every ERROR=0 claim becomes unverifiable."""
    assert verify_jar() == VALIDATOR_SHA256


@needs_jar
def test_gate_opens_on_the_good_feed():
    r = run_validator(feed_bytes())
    assert r["errors"] == 0
    assert r["publish_gate"] == "OPEN"


@needs_jar
def test_report_binds_the_exact_bytes_validated():
    """A certificate must not be able to claim feed A was validated while
    feed B was published."""
    import hashlib
    data = feed_bytes()
    r = run_validator(data)
    assert r["feed_sha256"] == hashlib.sha256(data).hexdigest()
    assert r["feed_bytes"] == len(data)
    assert r["validator_sha256"] == VALIDATOR_SHA256


@needs_jar
def test_gate_closes_on_a_feed_with_errors():
    """Stops without coordinates -> stop_without_location at ERROR severity."""
    raw = json.loads(FIXTURE.read_text())
    for c in raw["claims"]:
        if c["kind"] == "stop":
            c["scope"].pop("lat", None)
            c["scope"].pop("lon", None)
    cs = ClaimSet.from_dicts(raw["agency_id"], raw["claims"])
    data = compose(cs, feed_start=START, horizon_days=120,
                   require_coordinates=False).to_zip_bytes()
    r = run_validator(data)
    assert r["errors"] > 0
    assert r["publish_gate"] == "CLOSED"
    assert any(code == "stop_without_location" for _sev, code in r["codes"])


@needs_jar
def test_corrupt_zip_fails_closed_rather_than_opening_the_gate():
    """The decisive property: no report means NO PASS, never a silent OPEN."""
    with pytest.raises(ValidatorUnavailable):
        run_validator(b"this is not a zip file at all")


def test_missing_jar_fails_closed(monkeypatch, tmp_path):
    import headway.pipeline.validate as v
    monkeypatch.setattr(v, "_jar_path", lambda: tmp_path / "absent.jar")
    with pytest.raises(ValidatorUnavailable, match="missing"):
        v.verify_jar()


def test_tampered_jar_fails_closed(monkeypatch, tmp_path):
    import headway.pipeline.validate as v
    fake = tmp_path / "gtfs-validator-8.0.1-cli.jar"
    fake.write_bytes(b"not the real validator")
    monkeypatch.setattr(v, "_jar_path", lambda: fake)
    with pytest.raises(ValidatorUnavailable, match="sha256 mismatch"):
        v.verify_jar()


def test_java_stub_on_macos_is_not_mistaken_for_a_runtime(monkeypatch):
    """macOS ships /usr/bin/java as a stub with no JRE behind it. `which java`
    is truthy and the validator then never runs. This caught itself once."""
    import subprocess

    import headway.pipeline.validate as v
    monkeypatch.setattr(v.shutil, "which", lambda n: "/usr/bin/java")
    monkeypatch.setattr(
        v.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, b"", b"no runtime"))
    assert v._java_works() is False


@needs_jar
def test_report_carries_proof_the_feed_was_parsed():
    """ERROR=0 is meaningless unless the validator demonstrably read the feed."""
    r = run_validator(feed_bytes())
    p = r["parsed"]
    assert p["counts"]["Stops"] == 4
    assert p["counts"]["Routes"] == 2
    assert p["counts"]["Trips"] == 3
    assert len(p["files"]) == 8
    assert "stop_times.txt" in p["files"]
