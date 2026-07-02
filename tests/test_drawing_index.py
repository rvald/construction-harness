"""Tests for the drawing index parser (Milestone 5).

Assertions are the spec's stated ground truth for the UCCS drawing set.
"""
from __future__ import annotations

import pathlib
from collections import Counter

from src.pipeline.phase2_drawing_index import (
    derive_discipline,
    derive_drawing_type,
    parse_drawing_index,
)

DRAWINGS = pathlib.Path(__file__).resolve().parents[1] / "data" / "uccs" / "drawings.pdf"

_REGISTRY = parse_drawing_index(DRAWINGS)
_BY_NUM = {e.sheet_number: e for e in _REGISTRY}


def test_total_sheet_count():
    assert len(_REGISTRY) == 133


def test_discipline_breakdown():
    counts = dict(Counter(e.discipline for e in _REGISTRY))
    assert counts == {
        "General": 4, "Structural": 1, "Architectural": 44, "Fire Protection": 2,
        "Plumbing": 8, "Mechanical": 22, "Electrical": 27, "Technology": 20, "Security": 5,
    }


def test_anchor_floor_plan():
    e = _BY_NUM["A2.1.1"]
    assert e.sheet_title == "LEVEL 1 - FLOOR PLAN - OVERALL"
    assert e.discipline == "Architectural"
    assert e.drawing_type == "Floor Plan"


def test_anchor_door_schedule():
    e = _BY_NUM["A9.3.1"]
    assert e.sheet_title == "DOOR AND FRAME SCHEDULE & ELEVATIONS"
    assert e.discipline == "Architectural"
    assert e.drawing_type == "Schedule"       # SCHEDULE must win over ELEVATIONS


def test_page_numbers_unique_and_in_range():
    pages = [e.pdf_page_number for e in _REGISTRY]
    assert all(p is not None for p in pages)
    assert sorted([p for p in pages if p is not None]) == list(range(1, 134))


def test_discipline_prefix_mapping():
    assert derive_discipline("AD2.1") == "Architectural"
    assert derive_discipline("AF2.4") == "Architectural"
    assert derive_discipline("EMP2.1.2") == "Electrical"
    assert derive_discipline("PD2.1.A") == "Plumbing"
    assert derive_discipline("MD2.1.A") == "Mechanical"
    assert derive_discipline("Y1.1.2") == "Security"


def test_drawing_type_priority():
    # SCHEDULE outranks ELEVATION; REFLECTED CEILING PLAN outranks FLOOR PLAN.
    assert derive_drawing_type("DOOR AND FRAME SCHEDULE & ELEVATIONS") == "Schedule"
    assert derive_drawing_type("LEVEL 1 - REFLECTED CEILING PLAN - OVERALL") == "Reflected Ceiling Plan"
    assert derive_drawing_type("DEMOLITION FLOOR PLAN - OVERALL") == "Demolition Plan"
    assert derive_drawing_type("PROJECT COVER SHEET") is None