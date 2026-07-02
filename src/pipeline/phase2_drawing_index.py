"""Phase 2c — Drawing Index parser (Milestone 5).

Parses the drawing index on page 2 (sheet G1.1) of the drawings PDF into a sheet
registry: a list of SheetEntry records.

Findings from exploration (notebooks/02_explore_drawings.py) that drive this design:
  * Page 2 is NOT rotated (rotation=0), unlike most drawing sheets — so ordinary
    table extraction works here.
  * pdfplumber's extract_tables() returns the sheet list as clean 2-column tables
    (['G0.0', 'PROJECT COVER SHEET']) split by the page's two visual columns, plus
    a lot of noise tables from the project-notes / team blocks that we filter out.
  * Discipline sub-headers appear as rows with a null second column (['GENERAL', None]).

pdf_page_number is assigned provisionally in index reading order (spec-sanctioned
sequential numbering); Milestone 9 verifies/corrects it against title blocks.
"""
from __future__ import annotations

import pathlib
import re

import pdfplumber

from src.models.project import SheetEntry

_DEFAULT_PDF = pathlib.Path(__file__).resolve().parents[2] / "data" / "uccs" / "drawings.pdf"
_INDEX_PAGE_INDEX = 1  # 0-indexed -> PDF page 2

SHEET_NUMBER_RE = re.compile(r"^[A-Z]{1,3}\d[\w.]*$")

# Sheet-number alpha prefix -> discipline.
DISCIPLINE_MAP = {
    "G": "General", "S": "Structural",
    "A": "Architectural", "AD": "Architectural", "AF": "Architectural",
    "FP": "Fire Protection",
    "P": "Plumbing", "PD": "Plumbing",
    "M": "Mechanical", "MD": "Mechanical",
    "E": "Electrical", "ED": "Electrical", "EMP": "Electrical",
    "T": "Technology", "Y": "Security",
}

# Title keyword -> drawing type, in PRIORITY order (first match wins).
# Ordering resolves overlaps: "...SCHEDULE & ELEVATIONS" -> Schedule (not Elevation),
# "REFLECTED CEILING PLAN" -> its own type before the generic PLAN check.
DRAWING_TYPE_RULES: list[tuple[str, str]] = [
    ("REFLECTED CEILING PLAN", "Reflected Ceiling Plan"),
    ("SCHEDULE", "Schedule"),
    ("DEMOLITION", "Demolition Plan"),
    ("ENLARGED", "Enlarged Plan"),
    ("FLOOR PLAN", "Floor Plan"),
    ("ELEVATION", "Elevation"),
    ("SECTION", "Section"),
    ("DETAIL", "Detail"),
    ("ABBREVIATIONS", "Reference"),
    ("SYMBOLS", "Reference"),
]


def derive_discipline(sheet_number: str) -> str:
    m = re.match(r"^[A-Z]+", sheet_number)
    prefix = m.group() if m else ""
    return DISCIPLINE_MAP.get(prefix, "Unknown")


def derive_drawing_type(title: str) -> str | None:
    upper = title.upper()
    for keyword, dtype in DRAWING_TYPE_RULES:
        if keyword in upper:
            return dtype
    return None


def _is_sheet_list_table(table: list[list]) -> bool:
    """True if a table carries the 'SHEET NUMBER / SHEET NAME' header."""
    for row in table:
        if row and row[0] and "SHEET" in str(row[0]) and "NUMBER" in str(row[0]):
            return True
    return False


def parse_drawing_index(
    pdf_path: str | pathlib.Path = _DEFAULT_PDF,
    page_index: int = _INDEX_PAGE_INDEX,
) -> list[SheetEntry]:
    """Parse the drawing index into an ordered list of SheetEntry records."""
    with pdfplumber.open(pdf_path) as pdf:
        tables = pdf.pages[page_index].extract_tables()

    seen: set[str] = set()
    entries: list[SheetEntry] = []
    for table in tables:
        if not _is_sheet_list_table(table):
            continue
        for row in table:
            if len(row) < 2:
                continue
            number = (row[0] or "").strip()
            title = (row[1] or "").strip()
            if not (SHEET_NUMBER_RE.match(number) and title):
                continue  # skips discipline headers ('GENERAL', None) and blanks
            if number in seen:
                continue
            seen.add(number)
            entries.append(SheetEntry(
                sheet_number=number,
                sheet_title=title,
                discipline=derive_discipline(number),
                drawing_type=derive_drawing_type(title),
            ))

    # Provisional sequential page numbers (verified against title blocks in M9).
    for i, e in enumerate(entries, start=1):
        e.pdf_page_number = i
    return entries


if __name__ == "__main__":
    from collections import Counter

    registry = parse_drawing_index()
    print(f"sheets parsed : {len(registry)}")
    print("by discipline :")
    for disc, n in sorted(Counter(e.discipline for e in registry).items()):
        print(f"  {disc:<16}{n}")
    print("by type       :")
    for dtype, n in sorted(Counter(str(e.drawing_type) for e in registry).items()):
        print(f"  {dtype:<24}{n}")