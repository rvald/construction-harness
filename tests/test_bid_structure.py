"""Tests for Division 00/01 bid-structure extraction (bid_structure).

M1: alternates. Parser tested on the measured UCCS schedule shape, plus the real
012300 section located + parsed end-to-end.
"""
from __future__ import annotations

import pathlib

from src.pipeline.bid_structure import extract_bid_structure, parse_alternates

MANUAL = pathlib.Path(__file__).resolve().parents[1] / "data" / "uccs" / "project_manual.pdf"

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
