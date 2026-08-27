"""Fetch a source document and render one page to pixels. NO MODEL.

The reader is a vision model, so a PDF has to become an image before anything
can read it. Three properties are load-bearing:

* **The bytes that were read are the bytes that get hashed.** The rendered PNG
  carries its own sha256 into the run ledger, so "the model read page 1" is
  checkable rather than assertable. A different DPI is a different image and
  therefore a different hash, which is the intended behaviour.
* **Rendering is deterministic and offline.** `pdftoppm` at a fixed DPI with
  the same input produces the same pixels. No network call sits between the
  download and the read.
* **A text layer is extracted too, and never fed to the model.** These ASTC
  PDFs happen to carry one. It is kept strictly as an INDEPENDENT oracle for
  scoring what the reader saw — feeding it to the reader would make the vision
  claim meaningless, and scoring against it is only fair if the reader never
  had it.

Downloads are cached under `.tmp/` by URL hash so a re-run costs no bandwidth
and the same artifact is provably reused.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DPI = 200
JRE_IMAGE = "eclipse-temurin:21-jre"
USER_AGENT = "headway-gtfs/0.1 (transit feed builder; contact via repository)"


class RenderUnavailable(RuntimeError):
    """The page could not be rendered. Never silently substituted."""


@dataclass(frozen=True)
class RenderedPage:
    """One page, as pixels, with everything needed to prove which page it was."""
    png_bytes: bytes
    page: int
    dpi: int
    width: int
    height: int
    source_uri: str
    source_sha256: str
    page_sha256: str
    page_count: int
    text_layer: str

    def as_dict(self) -> dict[str, object]:
        return {
            "source_uri": self.source_uri,
            "source_sha256": self.source_sha256,
            "page": self.page,
            "page_count": self.page_count,
            "dpi": self.dpi,
            "pixels": f"{self.width}x{self.height}",
            "page_sha256": self.page_sha256,
            "png_bytes": len(self.png_bytes),
            "text_layer_chars": len(self.text_layer),
        }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _cache_dir() -> Path:
    d = _repo_root() / ".tmp" / "sources"
    d.mkdir(parents=True, exist_ok=True)
    return d


def fetch(uri: str, *, timeout: int = 120) -> tuple[Path, str]:
    """Return a local path to `uri` and the sha256 of its bytes.

    A local path is accepted unchanged so the pipeline can be run offline
    against a file a judge supplies.
    """
    local = Path(uri).expanduser()
    if local.exists():
        return local, hashlib.sha256(local.read_bytes()).hexdigest()

    if not uri.lower().startswith(("http://", "https://")):
        raise RenderUnavailable(f"not a readable file or http(s) URL: {uri!r}")

    key = hashlib.sha256(uri.encode()).hexdigest()[:16]
    suffix = Path(uri.split("?")[0]).suffix or ".bin"
    dest = _cache_dir() / f"{key}{suffix}"
    if not dest.exists():
        req = urllib.request.Request(uri, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                dest.write_bytes(r.read())
        except Exception as exc:                              # noqa: BLE001
            raise RenderUnavailable(f"could not fetch {uri}: {exc}") from exc
    return dest, hashlib.sha256(dest.read_bytes()).hexdigest()


def _pdfinfo_pages(pdf: Path) -> int:
    if not shutil.which("pdfinfo"):
        return 0
    proc = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True)
    for line in proc.stdout.splitlines():
        if line.startswith("Pages:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                return 0
    return 0


def _text_layer(pdf: Path, page: int) -> str:
    """The embedded text of one page, if the PDF has any. Never sent to a model."""
    if not shutil.which("pdftotext"):
        return ""
    proc = subprocess.run(
        ["pdftotext", "-f", str(page), "-l", str(page), "-layout", str(pdf), "-"],
        capture_output=True, text=True)
    return proc.stdout if proc.returncode == 0 else ""


def _png_size(data: bytes) -> tuple[int, int]:
    """Width and height straight from the PNG IHDR, so PIL is not required."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise RenderUnavailable("rendered output is not a PNG")
    return (int.from_bytes(data[16:20], "big"),
            int.from_bytes(data[20:24], "big"))


def render_page(uri: str, *, page: int = 1, dpi: int = DEFAULT_DPI) -> RenderedPage:
    """Render one page of a PDF to PNG bytes at a fixed DPI."""
    if page < 1:
        raise RenderUnavailable(f"page must be >= 1, got {page}")

    pdf, source_sha = fetch(uri)
    page_count = _pdfinfo_pages(pdf)
    if page_count and page > page_count:
        raise RenderUnavailable(
            f"{uri} has {page_count} page(s); page {page} was requested")

    if not shutil.which("pdftoppm"):
        raise RenderUnavailable(
            "pdftoppm is required to rasterise a PDF (brew install poppler).")

    work = _repo_root() / ".tmp" / "render"
    work.mkdir(parents=True, exist_ok=True)
    stem = work / f"{source_sha[:16]}_p{page}_{dpi}"
    out = stem.with_suffix(".png")
    if not out.exists():
        # `-singlefile` suppresses pdftoppm's zero-padded page suffix, so the
        # output path is the one we asked for rather than `-01.png`.
        proc = subprocess.run(
            ["pdftoppm", "-png", "-r", str(dpi), "-f", str(page), "-l",
             str(page), "-singlefile", str(pdf), str(stem)],
            capture_output=True, text=True, timeout=300)
        if proc.returncode != 0 or not out.exists():
            raise RenderUnavailable(
                f"pdftoppm failed on page {page}: exit={proc.returncode} "
                f"stderr={proc.stderr[-800:]}")

    data = out.read_bytes()
    width, height = _png_size(data)
    return RenderedPage(
        png_bytes=data,
        page=page,
        dpi=dpi,
        width=width,
        height=height,
        source_uri=uri,
        source_sha256=source_sha,
        page_sha256=hashlib.sha256(data).hexdigest(),
        page_count=page_count,
        text_layer=_text_layer(pdf, page),
    )
