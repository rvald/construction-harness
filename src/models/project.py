"""Project-level models.

For now this holds SheetEntry, produced by the Milestone 5 drawing-index parser.
ProjectInfo / FileInfo (Phase 1 intake) land at their milestone.
"""
from __future__ import annotations

from dataclasses import dataclass

from .base import JsonModel


@dataclass
class SheetEntry(JsonModel):
    """A single entry from the drawing index (sheet registry)."""

    sheet_number: str                       # e.g. "A2.1.1"
    sheet_title: str                        # e.g. "LEVEL 1 - FLOOR PLAN - OVERALL"
    discipline: str                         # e.g. "Architectural"
    drawing_type: str | None = None         # e.g. "Floor Plan", "Schedule", "Section"
    pdf_page_number: int | None = None      # 1-indexed page in the PDF (provisional until M9)


@dataclass
class SheetMetadata(JsonModel):
    """Title-block metadata extracted from an actual drawing sheet (Milestone 9)."""

    pdf_page_number: int                    # 1-indexed page the metadata came from
    sheet_number: str                       # from the bottom-right title-block box
    sheet_title: str                        # directly above the sheet-number box
    project_number: str | None = None       # e.g. "12654.000"