"""Tests for the individual spec-section parser (Milestone 4).

Grounded in the real 081113 / 081416 / 084229.33 sections verified during
exploration. Plain assert-style so they run with or without pytest.
"""
from __future__ import annotations

import pathlib

from src.models.spec import SpecSection
from src.pipeline.phase2_spec_parser import parse_spec_section, parse_spec_toc

MANUAL = pathlib.Path(__file__).resolve().parents[1] / "data" / "uccs" / "project_manual.pdf"

# Parse each section once and reuse; scanning the PDF per assertion is wasteful.
_TOC = parse_spec_toc(MANUAL)
_CACHE: dict[str, SpecSection] = {}


def _sec(number: str, hint: int = 340) -> SpecSection:
    if number not in _CACHE:
        _CACHE[number] = parse_spec_section(MANUAL, number, toc=_TOC, start_hint=hint)
    return _CACHE[number]


def test_section_identity():
    sec = _sec("081113")
    assert sec.section_title == "HOLLOW METAL DOORS AND FRAMES"
    assert sec.division_number == "08"
    assert sec.division_title == "OPENINGS"


def test_three_parts_in_order():
    sec = _sec("081113")
    assert [p.part_number for p in sec.parts] == [1, 2, 3]
    assert [p.part_title for p in sec.parts] == ["GENERAL", "PRODUCTS", "EXECUTION"]


def test_clause_counts():
    sec = _sec("081113")
    counts = {p.part_number: len(p.clauses) for p in sec.parts}
    assert counts == {1: 9, 2: 7, 3: 4}          # 20 clauses total, verified in source


def test_clause_lookup_and_titles():
    sec = _sec("081113")
    for clause_id, expected in [("1.2", "SUMMARY"), ("2.1", "MANUFACTURERS"), ("3.2", "INSTALLATION")]:
        c = sec.clause(clause_id)
        assert c is not None, f"clause {clause_id} not found"
        assert c.title == expected


def test_standards_extracted_and_clean():
    sec = _sec("081113")
    stds = sec.all_standards
    assert "ANSI/SDI A250.8" in stds
    assert "ASTM A1008/A1008M" in stds        # healed from a line-break split
    # no trailing punctuation or embedded whitespace survived normalization
    assert all(not s.endswith(".") and "\n" not in s and "  " not in s for s in stds)


def test_manufacturers_extracted():
    sec = _sec("081113")
    c = sec.clause("2.1")
    assert c is not None, "clause 2.1 (MANUFACTURERS) not found"
    assert "Steelcraft" in c.products
    assert len(c.products) >= 5


def test_page_range_plausible():
    sec = _sec("081113")
    start, end = sec.page_range
    assert start < end and (end - start) == 6    # 361..367


# --- Generality: parser is not overfit to 081113 ---

def test_generalizes_to_wood_doors():
    sec = _sec("081416", hint=360)
    assert sec.section_title == "FLUSH WOOD DOORS"
    assert [p.part_number for p in sec.parts] == [1, 2, 3]


def test_handles_decimal_section_number():
    sec = _sec("084229.33", hint=360)
    assert sec.section_number == "084229.33"
    assert sec.section_title == "SWINGING AUTOMATIC ENTRANCES"
    assert len(sec.parts) == 3