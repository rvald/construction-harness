"""Phase 1 — Page profiler (Document Locator, M2).

Cheap per-page structural features for every page: size, rotation, text density,
whether it has a text layer, and counts of a few anchor tokens. Segmentation (M3)
and location (M5) build on these.

PERFORMANCE IS THE POINT. This runs on every page, so it uses only fitz
`page.rect` + `get_text()` (glyph extraction — fast) + substring counts. It never
calls `extract_tables()` or `get_drawings()`: those are what made the old
fixed-page code hang on large-format sheets, and they run later, on a handful of
candidate pages only. Budget: profile Pinney (525 pages) well under 60s.
"""
from __future__ import annotations

import pathlib
import re

import fitz  # PyMuPDF

from src.models.document_map import FileRef, PageProfile

_SHORT_TOKEN_RE = re.compile(r"\b[A-Z]{1,4}\b")   # abbreviation-sheet signal

# Cheap region/artifact signal tokens, counted by substring match on page text.
ANCHOR_TOKENS = (
    "DIVISION", "SECTION", "TABLE OF CONTENTS",       # manual / spec
    "SHEET NUMBER", "SHEET NAME",                     # drawing index
    "DOOR SCHEDULE", "FIRE RATING", "HARDWARE SET",   # door schedule
    "ROOM FINISH SCHEDULE", "FINISH SCHEDULE",        # finish schedule
    "ABBREVIATION",                                   # abbreviations
)

_LETTER_MAX_EDGE = 1000       # pt; below this a page is Letter/A4-scale (manual)
_LARGE_MIN_EDGE = 1500        # pt; at/above this a page is a large-format sheet
_TEXT_LAYER_MIN_CHARS = 20


def _size_class(width: float, height: float) -> str:
    """Size-first bucket. Size discriminates manual (small) from drawings (large)
    far more reliably than orientation, which flips with page rotation."""
    longest = max(width, height)
    if longest < _LETTER_MAX_EDGE:
        return "letter"
    if longest >= _LARGE_MIN_EDGE:
        return "large"
    return "other"


def _anchor_hits(upper_text: str) -> dict[str, int]:
    return {tok: upper_text.count(tok) for tok in ANCHOR_TOKENS if tok in upper_text}


def profile_page(file_id: str, page: "fitz.Page", page_index: int) -> PageProfile:
    rect = page.rect
    width, height = float(rect.width), float(rect.height)
    text = page.get_text() or ""
    char_count = len(text.strip())
    area = max(width * height, 1.0)
    return PageProfile(
        file_id=file_id,
        page_index=page_index,
        width=round(width, 1),
        height=round(height, 1),
        rotation=int(page.rotation),
        size_class=_size_class(width, height),
        char_count=char_count,
        text_density=round(char_count / (area / 1000.0), 3),   # chars per 1000 sq pt
        has_text_layer=char_count >= _TEXT_LAYER_MIN_CHARS,
        short_token_count=len(_SHORT_TOKEN_RE.findall(text)),
        anchor_hits=_anchor_hits(text.upper()),
    )


def profile_file(ref: FileRef) -> list[PageProfile]:
    with fitz.open(ref.path) as doc:
        return [profile_page(ref.file_id, doc[i], i) for i in range(doc.page_count)]


def profile_package(refs: list[FileRef]) -> list[PageProfile]:
    profiles: list[PageProfile] = []
    for ref in refs:
        profiles.extend(profile_file(ref))
    return profiles


if __name__ == "__main__":
    import sys
    import time
    from collections import Counter

    from src.pipeline.phase1_intake import intake_package

    base = pathlib.Path(__file__).resolve().parents[2] / "data" / "uccs"
    default = [base / "drawings.pdf", base / "project_manual.pdf"]
    refs = intake_package(sys.argv[1:] or default)

    for ref in refs:
        t0 = time.time()
        profs = profile_file(ref)
        dt = time.time() - t0
        by_size = dict(Counter(p.size_class for p in profs))
        anchors = Counter(tok for p in profs for tok in p.anchor_hits)
        print(f"{ref.file_id:<28} {len(profs):>5} pages in {dt:5.1f}s  size={by_size}")
        print(f"    top anchors: {dict(anchors.most_common(6))}")
