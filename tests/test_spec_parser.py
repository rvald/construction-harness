"""Tests for the spec TOC parser (Milestone 3).

Includes the three tests verbatim from the Build Spec (§ Milestone 3) plus a few
assertions grounded in the real document that we verified during exploration.

Written as plain assert-style functions so they run with or without pytest.
"""
from __future__ import annotations

import pathlib

from src.pipeline.phase2_spec_parser import parse_spec_toc

MANUAL = pathlib.Path(__file__).resolve().parents[1] / "data" / "uccs" / "project_manual.pdf"


# --- Verbatim from the Build Spec ---

def test_toc_parsing():
    toc = parse_spec_toc(MANUAL)
    assert toc.total_sections > 80
    div_08 = next(d for d in toc.divisions if d["number"] == "08")
    assert div_08["title"] == "OPENINGS"
    assert len(div_08["sections"]) == 9
    assert any(s["number"] == "081113" for s in div_08["sections"])


def test_not_applicable_divisions():
    toc = parse_spec_toc(MANUAL)
    div_04 = next(d for d in toc.divisions if d["number"] == "04")
    assert div_04["applicable"] is False


def test_all_divisions_present():
    toc = parse_spec_toc(MANUAL)
    expected = ["00", "01", "02", "03", "04", "05", "06", "07", "08", "09",
                "10", "11", "12", "13", "14", "21", "22", "23", "25", "26",
                "27", "28", "31", "32"]
    actual = [d["number"] for d in toc.divisions]
    assert actual == expected


# --- Reality-confirmed additions ---

def test_section_count_matches_document():
    # Verified by hand + parser against the actual 5-page TOC.
    assert parse_spec_toc(MANUAL).total_sections == 124


def test_not_applicable_set():
    toc = parse_spec_toc(MANUAL)
    na = {d["number"] for d in toc.divisions if not d["applicable"]}
    assert na == {"04", "05", "11", "13", "14", "25", "28", "31", "32"}


def test_decimal_section_numbers_preserved():
    toc = parse_spec_toc(MANUAL)
    div_08 = next(d for d in toc.divisions if d["number"] == "08")
    assert any(s["number"] == "084229.33" for s in div_08["sections"])


def test_wrapped_title_is_stitched():
    toc = parse_spec_toc(MANUAL)
    div_23 = next(d for d in toc.divisions if d["number"] == "23")
    sec = next(s for s in div_23["sections"] if s["number"] == "238123.12")
    # Title spans two source lines; both fragments must be present on one record.
    assert "LARGE CAPACITY" in sec["title"]
    assert "FLOOR-MOUNTED UNITS" in sec["title"]