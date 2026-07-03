"""Phase 1 — Intake (thin), for the Document Locator.

Enumerates the files of a bid package into FileRef records: checksum, page count,
and a coarse format classification (vector text PDF vs scanned/no-text). This is
the 'files' layer the rest of discovery builds on. Separate-file and combined
packages both reduce to a list of FileRef here — the separate-vs-combined
distinction is handled later, by segmentation over regions.

Deliberately thin: no dedup / addenda-versioning / RFI handling yet (deferred).
"""
from __future__ import annotations

import hashlib
import pathlib

import fitz  # PyMuPDF

from src.models.document_map import FileRef

_TEXT_SAMPLE_PAGES = 10          # number of pages sampled to decide vector-vs-scanned
_TEXT_LAYER_MIN_CHARS = 20       # a page with >= this many non-space chars "has text"


def _checksum(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _detect_format(doc: "fitz.Document") -> str:
    """Vector if any sampled page carries an embedded text layer, else scanned.

    Sampled (not exhaustive) so intake stays cheap on large sets. Cover/divider
    pages can be text-light, so a single text page across the sample is enough to
    call the file a vector PDF.
    """
    n = doc.page_count
    if n == 0:
        return "unknown"
    step = max(1, n // _TEXT_SAMPLE_PAGES)
    sampled = range(0, n, step)
    with_text = sum(
        1 for i in sampled
        if len((doc[i].get_text() or "").strip()) >= _TEXT_LAYER_MIN_CHARS
    )
    return "pdf_vector" if with_text > 0 else "pdf_scanned"


def intake_file(path: str | pathlib.Path) -> FileRef:
    """Intake a single file into a FileRef."""
    p = pathlib.Path(path)
    with fitz.open(str(p)) as doc:
        page_count = doc.page_count
        doc_format = _detect_format(doc)
    return FileRef(
        file_id=p.stem,
        path=str(p),
        checksum_sha256=_checksum(p),
        page_count=page_count,
        doc_format=doc_format,
    )


def intake_package(paths: list[str | pathlib.Path]) -> list[FileRef]:
    """Intake every file in a bid package (separate files or one combined PDF)."""
    return [intake_file(p) for p in paths]


if __name__ == "__main__":
    import sys

    base = pathlib.Path(__file__).resolve().parents[2] / "data" / "uccs"
    default = [base / "drawings.pdf", base / "project_manual.pdf"]
    paths = sys.argv[1:] or default
    for ref in intake_package(paths):
        print(f"{ref.file_id:<24} {ref.page_count:>5} pages  {ref.doc_format:<11} "
              f"{ref.checksum_sha256[:12]}…")
