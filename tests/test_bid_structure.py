"""Tests for Division 00/01 bid-structure extraction (bid_structure).

M1: alternates. Parser tested on the measured UCCS schedule shape, plus the real
012300 section located + parsed end-to-end.
"""
from __future__ import annotations

import pathlib

from src.pipeline.bid_structure import (
    build_bid_structure, extract_bid_structure, parse_alternates, parse_unit_prices,
)

DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "uccs"
MANUAL = DATA / "project_manual.pdf"
PINNEY = DATA / "pinney" / "pinney_library_drawings_and_project_manual.pdf"

# The measured shape of UCCS 012300 PART 3 (SCHEDULE OF ALTERNATES).
_SAMPLE = """PART 3 - EXECUTION
3.1
SCHEDULE OF ALTERNATES
A.
Alternate No. 1: Bench Millwork.
1.
Base Bid: Provide built-in millwork benches with incorporated electrical power.
2.
Deductive Alternate: Delete two (2) built-in millwork benches.
B.
Alternate No. 2: West Restroom Renovation.
1.
Base Bid: Renovate sink areas in existing West restrooms.
2.
Deductive Alternate: Existing West restrooms to remain.
"""


def test_parse_alternates_shape():
    items = parse_alternates(_SAMPLE, {"section": "012300"})
    assert [i.number for i in items] == ["1", "2"]
    assert items[0].kind == "alternate"
    assert items[0].title == "Bench Millwork"
    assert items[0].basis == "deduct"                         # "Deductive Alternate" present
    assert "millwork benches" in items[0].description         # base-bid scope captured
    assert items[1].title == "West Restroom Renovation"


_UP_SAMPLE = """PART 3 - EXECUTION
3.1
SCHEDULE OF UNIT PRICES
A.
Unit Price No. 1: Moisture Vapor Emission Control
1.
Description: Provide Moisture Vapor Emission Control in accordance with Section 090561.13.
2.
Unit of Measurement: Square feet.
B.
Unit Price No. 2: Resilient Tile Flooring
1.
Description: Provide Resilient Tile Flooring in accordance with Section 096519.
2.
Unit of Measurement: Square feet.
"""


def test_parse_unit_prices_shape():
    items = parse_unit_prices(_UP_SAMPLE, {"section": "012200"})
    assert [i.number for i in items] == ["1", "2"]
    assert items[0].kind == "unit_price" and items[0].basis == "unit"
    assert items[0].title == "Moisture Vapor Emission Control"
    assert items[0].unit == "Square feet"
    assert "090561.13" in items[0].description


def test_extract_alternates_from_real_manual():
    items, located = extract_bid_structure(MANUAL)
    assert located["alternate"] == "found"
    alts = [i for i in items if i.kind == "alternate"]
    assert len(alts) >= 3                                      # UCCS has Alternates 1, 2, 3, ...
    by_num = {i.number: i for i in alts}
    assert by_num["1"].title == "Bench Millwork"
    assert by_num["2"].title == "West Restroom Renovation"
    assert all(i.source["section"] == "012300" for i in alts)
    assert all(i.source["page"] for i in alts)                # provenance recorded


def test_extract_unit_prices_from_real_manual():
    items, located = extract_bid_structure(MANUAL)
    assert located["unit_price"] == "found"
    ups = [i for i in items if i.kind == "unit_price"]
    assert len(ups) >= 2
    by_num = {i.number: i for i in ups}
    assert by_num["1"].title == "Moisture Vapor Emission Control"
    assert by_num["1"].unit and "square feet" in by_num["1"].unit.lower()
    assert all(i.source["section"] == "012200" for i in ups)


def test_allowances_absent_flagged():
    # UCCS has no 012100 Allowances section -> degrade + flag, never faked.
    _, located = extract_bid_structure(MANUAL)
    assert located["allowance"] == "absent"


def test_build_artifact_summary():
    report = build_bid_structure(MANUAL)
    s = report["summary"]
    assert s["located"]["alternate"] == "found" and s["located"]["allowance"] == "absent"
    assert s["counts"]["alternate"] >= 3 and s["counts"]["unit_price"] >= 2
    assert s["total_items"] == len(report["items"])


def test_pinney_degrades_all_absent():
    # Pinney has no formal Div-01 pricing sections -> everything absent, items empty.
    items, located = extract_bid_structure(PINNEY)
    assert items == []
    assert set(located.values()) == {"absent"}
