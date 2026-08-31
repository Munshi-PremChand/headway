"""The demo surface, and the thing that gets deployed to Cloud Run.

Two jobs:

  * serve the page and the artifacts of a real run — the scan, every claim's
    bounding box, the ledger, and both feeds;
  * run the pipeline LIVE on request, so "it ran on Google Cloud" is something
    a viewer watches happen rather than something a slide asserts.

The prebuilt bundle under `web/data/` is what loads instantly; `POST /api/run`
re-executes the whole pipeline against a live PDF and rewrites it. A filmed
take wants the first; a judge poking at the deployment wants the second.

Health is deliberately cheap and dependency-free so Cloud Run's probe never
waits on Vertex.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
DATA = WEB / "data"
sys.path.insert(0, str(ROOT))

app = FastAPI(title="HEADWAY", docs_url="/api/docs")

if DATA.exists():
    app.mount("/data", StaticFiles(directory=str(DATA)), name="data")

_run_lock = asyncio.Lock()

# The photocopy measurements are a separate experiment shipped in the image.
# A live run rebuilds run.json WITHOUT them — losing the "take the text layer
# away" section for every later viewer of this instance (this is how one
# filmed take gutted the next). Snapshot the shipped copy at startup and
# carry it across rebuilds; the live run never re-measures it.
try:
    _PHOTOCOPY = json.loads((DATA / "run.json").read_text()).get("photocopy")
except Exception:                                               # noqa: BLE001
    _PHOTOCOPY = None


def _restore_photocopy() -> None:
    if not _PHOTOCOPY:
        return
    f = DATA / "run.json"
    try:
        bundle = json.loads(f.read_text())
        if not bundle.get("photocopy"):
            bundle["photocopy"] = _PHOTOCOPY
            f.write_text(json.dumps(bundle))
    except Exception:                                           # noqa: BLE001
        pass


@app.get("/api/healthz")
@app.get("/healthz")
def healthz() -> dict:
    """Cheap and dependency-free, so a probe never waits on Vertex.

    Served under /api as well: Cloud Run's own frontend answers a bare
    /healthz with a Google 404 page before the request reaches the container
    (measured 2026-08-31 — the response body is Google's error page, and no
    request appears in the container log).
    """
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    page = WEB / "templates" / "index.html"
    if not page.exists():
        raise HTTPException(500, "template missing")
    return HTMLResponse(page.read_text())


@app.get("/architecture", response_class=HTMLResponse)
def architecture() -> HTMLResponse:
    """The diagram the rules ask for, as a page rather than a flat image.

    Kept in the same design language as the demo so a judge moving between them
    does not have to re-orient, and rendered to `docs/architecture.png` for
    Devpost by `scripts/shoot_architecture.sh`.
    """
    page = WEB / "templates" / "architecture.html"
    if not page.exists():
        raise HTTPException(500, "template missing")
    return HTMLResponse(page.read_text())


@app.get("/api/run")
def latest() -> JSONResponse:
    f = DATA / "run.json"
    if not f.exists():
        raise HTTPException(404, "no run bundle; build it with "
                                 "scripts/build_demo_data.py")
    return JSONResponse(json.loads(f.read_text()))


@app.get("/api/feed/{which}")
def feed(which: str) -> FileResponse:
    if which not in ("headway", "baseline"):
        raise HTTPException(404, "unknown feed")
    f = DATA / f"{which}.zip"
    if not f.exists():
        raise HTTPException(404, "feed not built")
    return FileResponse(str(f), media_type="application/zip",
                        filename=f"{which}-gtfs.zip")


class RunRequest(BaseModel):
    pdf: str = ("https://st.redbus.in/Images/WL/ASTC/schedules_new/"
                "Guwahati_division.pdf")
    page: int = 1
    profile: str = "astc_guwahati"


@app.post("/api/run")
async def run_live(req: RunRequest) -> JSONResponse:
    """Re-execute the pipeline against a live PDF and rebuild the bundle.

    Serialised behind a lock: two concurrent runs would race on `web/data/`,
    and the honest failure is a queue rather than a corrupted bundle.
    """
    if _run_lock.locked():
        raise HTTPException(409, "a run is already in progress")
    async with _run_lock:
        started = time.time()
        proc = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "scripts/run_pipeline.py", "--pdf", req.pdf,
             "--page", str(req.page), "--profile", req.profile],
            capture_output=True, text=True, cwd=str(ROOT), timeout=600)
        build = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "scripts/build_demo_data.py", "--pdf", req.pdf,
             "--page", str(req.page), "--profile", req.profile],
            capture_output=True, text=True, cwd=str(ROOT), timeout=600)
        ok = proc.returncode == 0 and build.returncode == 0
        if ok:
            _restore_photocopy()
        return JSONResponse({
            "ok": ok,
            "seconds": round(time.time() - started, 1),
            "pipeline": proc.stdout[-8000:],
            "bundle": build.stdout[-2000:],
            "stderr": (proc.stderr or build.stderr)[-2000:] if not ok else "",
        }, status_code=200 if ok else 500)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
