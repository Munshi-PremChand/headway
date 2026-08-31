"""How the pipeline obtains a Gemini client, in a fixed order of preference.

There are three ways to reach `gemini-3.7-flash`, and until now only the first
was wired up:

1. **Vertex AI via Application Default Credentials.** The documented path.
   Requires `gcloud auth application-default login`, which writes
   `~/.config/gcloud/application_default_credentials.json`.
2. **Vertex AI via a `gcloud` access token.** MEASURED 2026-08-27: an ADC file
   was never actually required. `google-genai` accepts an explicit
   `credentials=` object, and a bearer token from
   `gcloud auth print-access-token` wrapped in `google.oauth2.credentials.
   Credentials` authenticates the same calls — verified with a live
   `generateContent` returning `modelVersion: gemini-3.7-flash`, and again
   through an ADK `LlmAgent` driven by `InMemoryRunner`.
3. **AI Studio API key.** No GCP project, no billing, no card. The hackathon
   rules permit either backend, so a judge who has only a free key can still
   run this repo.

Path 2 matters because it is the difference between a pipeline that anyone can
run right now and one that waits on an interactive browser login. Its cost is
that the token is short-lived (roughly an hour); `TokenExpired` names that
explicitly rather than letting a run die on a bare 401 an hour in.

Nothing here caches a credential to disk. Tokens stay in memory for the life of
the process.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

# Verified 2026-08-27: gemini-3.7-flash is served from `global`, NOT
# us-central1. Pointing a regional endpoint at it returns 404 for a model that
# plainly exists, which reads like a permissions problem and is not.
DEFAULT_PROJECT = "headway-atah-2026"
DEFAULT_LOCATION = "global"


class NoCredential(RuntimeError):
    """No usable credential was found. Never treated as a soft failure."""


class TokenExpired(RuntimeError):
    """A `gcloud` access token expired mid-run. Distinct from 'no credential'."""


@dataclass(frozen=True)
class Credential:
    """Which path was taken, so a run ledger can print it instead of guessing."""
    backend: str                 # "vertex-adc" | "vertex-token" | "ai-studio"
    project: str | None
    location: str | None
    detail: str


def _gcloud_token() -> str | None:
    """A short-lived OAuth token for the active `gcloud` account, or None."""
    if not shutil.which("gcloud"):
        return None
    try:
        proc = subprocess.run(["gcloud", "auth", "print-access-token"],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    tok = proc.stdout.strip()
    return tok if proc.returncode == 0 and tok else None


def _adc_present() -> bool:
    """Is there a usable Application Default Credential, from ANY source?

    MEASURED 2026-08-31, first Cloud Run deployment: checking for the ADC FILE
    is wrong, and wrong in exactly the environment that matters. On Cloud Run,
    Compute Engine and GKE there is no file — the credential comes from the
    metadata server. The file check returned False, the gcloud-token path found
    no `gcloud` binary in the container, and a service running as a service
    account with `aiplatform.user` reported "no usable Gemini credential".

    `google.auth.default()` is the one check that covers every source:
    GOOGLE_APPLICATION_CREDENTIALS, the gcloud file, and the metadata server.
    Asking the library the question it exists to answer beats guessing at where
    it keeps its answer.
    """
    try:
        import google.auth
        creds, _project = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"])
        return creds is not None
    except Exception:                                          # noqa: BLE001
        return False


def build_client(
    *,
    project: str | None = None,
    location: str | None = None,
    prefer: str | None = None,
) -> tuple[Any, Credential]:
    """Return `(genai.Client, Credential)` using the first path that is usable.

    `prefer` forces one backend ("vertex-adc", "vertex-token", "ai-studio") so a
    run can prove a specific path works rather than silently falling through to
    an easier one.
    """
    from google import genai

    # Cloud Run injects these; a laptop usually has neither, so the pinned
    # defaults stand in. Reading them means the same image runs in another
    # project without a rebuild.
    project = (project or os.environ.get("GOOGLE_CLOUD_PROJECT")
               or DEFAULT_PROJECT)
    location = (location or os.environ.get("GOOGLE_CLOUD_LOCATION")
                or DEFAULT_LOCATION)

    order = ["vertex-adc", "vertex-token", "ai-studio"]
    if prefer:
        if prefer not in order:
            raise NoCredential(f"unknown backend {prefer!r}; expected {order}")
        order = [prefer]

    tried: list[str] = []
    for backend in order:
        if backend == "vertex-adc":
            if not _adc_present():
                tried.append("vertex-adc: google.auth.default() found no "
                             "credential (no env var, no gcloud file, no "
                             "metadata server)")
                continue
            return (genai.Client(vertexai=True, project=project,
                                 location=location),
                    Credential("vertex-adc", project, location,
                               "application default credentials"))

        if backend == "vertex-token":
            tok = _gcloud_token()
            if not tok:
                tried.append("vertex-token: `gcloud auth print-access-token` "
                             "unavailable or returned nothing")
                continue
            from google.oauth2.credentials import Credentials
            return (genai.Client(vertexai=True, project=project,
                                 location=location,
                                 credentials=Credentials(token=tok)),
                    Credential("vertex-token", project, location,
                               "gcloud access token (expires ~1h)"))

        if backend == "ai-studio":
            key = (os.environ.get("GOOGLE_API_KEY")
                   or os.environ.get("GEMINI_API_KEY"))
            if not key:
                tried.append("ai-studio: GOOGLE_API_KEY / GEMINI_API_KEY unset")
                continue
            return (genai.Client(api_key=key),
                    Credential("ai-studio", None, None,
                               "AI Studio API key from the environment"))

    raise NoCredential(
        "no usable Gemini credential. Any ONE of these is enough:\n"
        "  gcloud auth application-default login      (Vertex, ADC)\n"
        "  gcloud auth login                          (Vertex, access token)\n"
        "  export GOOGLE_API_KEY=...                  (AI Studio, free key at\n"
        "                                              aistudio.google.com/apikey)\n"
        "tried:\n  - " + "\n  - ".join(tried))


def is_expired_token(exc: BaseException) -> bool:
    """Recognise the 401 a stale `gcloud` token produces, and only that.

    Worth naming separately: an hour into a long run the failure looks like a
    permissions problem, and the fix is one command rather than an audit of the
    IAM bindings.
    """
    text = f"{type(exc).__name__}: {exc}"
    return ("401" in text or "UNAUTHENTICATED" in text.upper()) and (
        "token" in text.lower() or "credential" in text.lower()
        or "authent" in text.lower())
