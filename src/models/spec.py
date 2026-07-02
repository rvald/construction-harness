"""Specification models.

For now this holds only SpecTOC, the model the Milestone 3 TOC parser produces.
Section-level models (SpecSection / SpecPart / SpecClause) land in Milestone 4,
just before the section parser that populates them.

A division dict has the shape:
    {"number": "08", "title": "OPENINGS",
     "sections": [{"number": "081113", "title": "HOLLOW METAL DOORS AND FRAMES"}, ...],
     "applicable": True}
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .base import JsonModel


@dataclass
class SpecTOC(JsonModel):
    """Table of contents for the project manual."""

    divisions: list[dict] = field(default_factory=list)
    total_sections: int = 0

    def division(self, number: str) -> dict | None:
        """Look up a division dict by its two-digit number (e.g. '08')."""
        return next((d for d in self.divisions if d["number"] == number), None)


@dataclass
class SpecClause(JsonModel):
    """A single top-level clause within a spec section part (e.g. '1.2 SUMMARY')."""

    clause_id: str                              # e.g. "1.2", "2.1"
    title: str                                  # e.g. "SUMMARY"
    text: str                                   # full body text of the clause
    products: list[str] = field(default_factory=list)   # product/manufacturer names
    standards: list[str] = field(default_factory=list)  # referenced standards (ASTM, ANSI, ...)


@dataclass
class SpecPart(JsonModel):
    """Part 1, 2, or 3 of a spec section."""

    part_number: int                            # 1, 2, or 3
    part_title: str                             # "GENERAL", "PRODUCTS", "EXECUTION"
    clauses: list[SpecClause] = field(default_factory=list)


@dataclass
class SpecSection(JsonModel):
    """A single CSI specification section."""

    section_number: str                         # e.g. "081113"
    section_title: str                          # e.g. "HOLLOW METAL DOORS AND FRAMES"
    division_number: str                        # e.g. "08"
    division_title: str                         # e.g. "OPENINGS"
    parts: list[SpecPart] = field(default_factory=list)
    page_range: tuple[int, int] = (0, 0)        # 1-indexed start/end pages in the PDF
    raw_text: str = ""

    def clause(self, clause_id: str) -> SpecClause | None:
        for part in self.parts:
            for c in part.clauses:
                if c.clause_id == clause_id:
                    return c
        return None

    @property
    def all_standards(self) -> list[str]:
        seen: dict[str, None] = {}
        for part in self.parts:
            for c in part.clauses:
                for s in c.standards:
                    seen.setdefault(s, None)
        return list(seen)