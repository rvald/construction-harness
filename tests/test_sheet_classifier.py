"""Tests for sheet classification (Milestone 9).

The reconciliation here doubles as verification of Milestone 5's provisional page
numbers: page_matches being true for every sampled sheet confirms the sequential
mapping was correct.
"""
from __future__ import annotations

import pathlib

from src.pipeline.phase2_drawing_index import parse_drawing_index
from src.pipeline.phase3_sheet_classifier import (
    SHEET_NUMBER_RE,
    classify_sheets,
    reconcile,
)

DRAWINGS = pathlib.Path(__file__).resolve().parents[1] / "data" / "uccs" / "drawings.pdf"

_REGISTRY = parse_drawing_index(DRAWINGS)
_META = classify_sheets(DRAWINGS)
_REPORT = reconcile(_META, _REGISTRY)


def test_classified_sample_count():
    assert len(_META) == 11


def test_all_sheet_numbers_valid():
    assert all(SHEET_NUMBER_RE.match(m.sheet_number) for m in _META)


def test_all_sampled_sheets_in_registry():
    assert all(r["in_registry"] for r in _REPORT)


def test_provisional_page_numbers_verified():
    # Confirms Milestone 5's sequential page numbering across sampled disciplines.
    assert all(r["page_matches"] for r in _REPORT)


def test_titles_reconcile_with_registry():
    assert all(r["title_matches"] for r in _REPORT)


def test_specific_sheet_metadata():
    m = next(x for x in _META if x.sheet_number == "A2.1.1")
    assert m.sheet_title == "LEVEL 1 - FLOOR PLAN - OVERALL"
    assert m.pdf_page_number == 14
    assert m.project_number == "12654.000"