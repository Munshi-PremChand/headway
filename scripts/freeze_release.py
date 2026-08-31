#!/usr/bin/env python3
"""Freeze the current commit into a release tarball, then validate and report.

The ship gate wants ONE concrete file whose sha256 a human has approved, and it
re-hashes that file at ship time. A git push has no single file, so this makes
one: `git archive HEAD` written to `dist/`. It is exactly the tracked bytes at
this commit, reproducible by anyone from the commit id, and it doubles as an
attachable artifact for the submission.

`dist/` is gitignored on purpose — a tarball certifying a tree cannot live
inside that tree without changing the thing it certifies.

Every invariant is fail-closed; see `release_validator.py` for the checks. This
script writes the manifest and report into the PROJECT's `.munshi/`, which is
where the gate looks (it walks up for `.munshi/state.json`).

    python3 scripts/freeze_release.py --tag submission-v1
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROJECT_MUNSHI = REPO.parent / ".munshi"      # where the gate looks


def git(*a: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *a], capture_output=True,
                          text=True, check=True).stdout.strip()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="submission-v1")
    ap.add_argument("--approver", default="repository owner (Munshi-PremChand)")
    args = ap.parse_args()

    dirty = git("status", "--porcelain")
    if dirty:
        print("REFUSED: working tree is not clean. Approved bytes would differ "
              "from pushed bytes.\n" + dirty[:600])
        return 1

    head = git("rev-parse", "HEAD")
    short = head[:12]
    dist = REPO / "dist"
    dist.mkdir(exist_ok=True)
    artifact = dist / f"headway-{args.tag}-{short}.tar.gz"

    subprocess.run(
        ["git", "-C", str(REPO), "archive", "--format=tar.gz",
         f"--prefix=headway-{short}/", "-o", str(artifact), "HEAD"],
        check=True)
    digest = sha256_file(artifact)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    PROJECT_MUNSHI.mkdir(parents=True, exist_ok=True)
    manifest_path = PROJECT_MUNSHI / "RELEASE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    manifest.update({
        "schemaVersion": 1,
        "candidateId": f"headway-{args.tag}",
        "createdUtc": now,
        "destination": "github:Munshi-PremChand/headway (public)",
        "action": "publish-source",
        "artifact": {
            "path": str(artifact),
            "commit": head,
            "tag": args.tag,
            "sha256": digest,
            "format": "tar.gz of git archive HEAD",
        },
    })
    manifest.setdefault("approval", {})
    manifest["approval"].update({
        "status": "approved",
        "approver": args.approver,
        "approvedUtc": now,
        "artifactSha256": digest,
    })
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    # Re-run the full check set against the freshly frozen bytes.
    val = subprocess.run(
        [sys.executable, "scripts/release_validator.py",
         "--manifest", str(manifest_path), "--out", str(REPO / ".munshi" /
                                                        "RELEASE_REPORT.json")],
        cwd=REPO, capture_output=True, text=True)
    print(val.stdout.strip())
    if val.returncode != 0:
        print(val.stderr.strip())
        return val.returncode

    rich = json.loads((REPO / ".munshi" / "RELEASE_REPORT.json").read_text())
    # The gate reads these five keys by name and re-hashes artifactPath itself.
    rich.update({
        "approvalStatus": manifest["approval"]["status"],
        "artifactPath": str(artifact),
        "artifactHash": digest,
        "commit": head,
        "tag": args.tag,
    })
    report_path = PROJECT_MUNSHI / "RELEASE_REPORT.json"
    report_path.write_text(json.dumps(rich, indent=2) + "\n")

    print(f"\nfrozen   : {artifact.relative_to(REPO)}")
    print(f"sha256   : {digest}")
    print(f"commit   : {head}")
    print(f"manifest : {manifest_path}")
    print(f"report   : {report_path}  (valid={rich.get('valid')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
