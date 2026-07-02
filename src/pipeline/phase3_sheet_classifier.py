"""Phase 3 — Sheet Classification (Milestone 9).

Extracts title-block metadata (sheet number, title, project number) from drawing
sheets and reconciles it against the sheet registry from Milestone 5 — which is how
the registry's provisional page numbers get verified.

Findings from exploration:
  * The title-block sheet number is the largest sheet-number token on the page
    (font height ~41pt) in the bottom-right corner. This holds across page
    rotations (0 and 90) and disciplines, because pdfplumber normalizes coordinates.
  * The sheet title sits directly above the number in mid-size font (larger than
    the small field labels, smaller than the number).
  * Project number ("12654.000") appears just above the number.

Per the spec, we classify a discipline-spanning SAMPLE of sheets, not all 133.
"""
from __future__ import annotations

import pathlib
import re

import pdfplumber

from src.models.project import SheetEntry, SheetMetadata

_DEFAULT_PDF = pathlib.Path(__file__).resolve().parents[2] / "data" / "uccs" / "drawings.pdf"

SHEET_NUMBER_RE = re.compile(r"^[A-Z]{1,3}\d+(?:\.\d+){0,3}$")
_PROJECT_NUMBER_RE = re.compile(r"\b\d{5}\.\d{3}\b")

# Spec's recommended discipline-spanning sample (0-indexed page numbers).
SAMPLE_PAGE_INDICES = [1, 5, 13, 14, 34, 37, 48, 49, 51, 59, 81]


def extract_title_block(pdf_path: str | pathlib.Path, page_index: int) -> SheetMetadata:
    """Extract title-block metadata from one drawing page."""
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_index]
        words = page.extract_words(keep_blank_chars=False)

    def height(w: dict) -> float:
        return w["bottom"] - w["top"]

    # Sheet number: largest sheet-number-pattern token on the page.
    number_words = [w for w in words if SHEET_NUMBER_RE.match(w["text"])]
    if not number_words:
        raise ValueError(f"No sheet-number token found on page {page_index + 1}.")
    num_word = max(number_words, key=height)
    sheet_number = num_word["text"]
    num_h = height(num_word)

    # Title: mid-font rows in the strip immediately above the number box. Walk
    # upward from the number and stop at a large vertical gap (that gap separates
    # the title from the project-name banner higher up in the block).
    mid = sorted(
        (w for w in words
         if w["x0"] > num_word["x0"] - 260
         and w["top"] < num_word["top"]
         and 0.4 * num_h <= height(w) < 0.9 * num_h),
        key=lambda w: -w["top"],
    )
    title_words: list[dict] = []
    prev_top = num_word["top"]
    for w in mid:
        if title_words and prev_top - w["top"] > 60:
            break
        title_words.append(w)
        prev_top = w["top"]
    title_words.sort(key=lambda w: (round(w["top"] / 6), w["x0"]))
    title = " ".join(w["text"] for w in title_words).strip()

    m = _PROJECT_NUMBER_RE.search(" ".join(w["text"] for w in words))
    return SheetMetadata(
        pdf_page_number=page_index + 1,
        sheet_number=sheet_number,
        sheet_title=title,
        project_number=m.group() if m else None,
    )


def classify_sheets(
    pdf_path: str | pathlib.Path = _DEFAULT_PDF,
    page_indices: list[int] | None = None,
) -> list[SheetMetadata]:
    indices = SAMPLE_PAGE_INDICES if page_indices is None else page_indices
    return [extract_title_block(pdf_path, i) for i in indices]


def reconcile(metadata: list[SheetMetadata], registry: list[SheetEntry]) -> list[dict]:
    """Cross-reference extracted title-block data against the sheet registry.

    Returns one report row per classified sheet, flagging: whether the sheet number
    exists in the registry, whether the registry's (provisional) page number matches
    the page we actually found it on, and whether the titles agree.
    """
    by_number = {e.sheet_number: e for e in registry}
    report: list[dict] = []
    for md in metadata:
        entry = by_number.get(md.sheet_number)
        row = {
            "pdf_page_number": md.pdf_page_number,
            "sheet_number": md.sheet_number,
            "in_registry": entry is not None,
            "registry_page": entry.pdf_page_number if entry else None,
            "page_matches": bool(entry and entry.pdf_page_number == md.pdf_page_number),
            "title_matches": bool(entry and entry.sheet_title.strip().upper() == md.sheet_title.strip().upper()),
            "extracted_title": md.sheet_title,
            "registry_title": entry.sheet_title if entry else None,
        }
        report.append(row)
    return report


if __name__ == "__main__":
    from src.pipeline.phase2_drawing_index import parse_drawing_index

    registry = parse_drawing_index()
    metadata = classify_sheets()
    print(f"classified {len(metadata)} sample sheets\n")
    print(f"{'page':>4} {'sheet':<9}{'in_reg':<7}{'reg_pg':>7}{'pg_ok':>7}{'title_ok':>9}  title")
    for r in reconcile(metadata, registry):
        print(f"{r['pdf_page_number']:>4} {r['sheet_number']:<9}{str(r['in_registry']):<7}"
              f"{str(r['registry_page']):>7}{str(r['page_matches']):>7}{str(r['title_matches']):>9}  {r['extracted_title'][:40]}")