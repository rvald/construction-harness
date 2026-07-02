"""Tests for the door schedule parser (Milestone 7).

The two anchor rows (N101A, N107B) are pinned by the spec's ground truth; N107B is
the linchpin of the end-to-end trace.
"""
from __future__ import annotations

import pathlib

from src.pipeline.phase2_schedule_parser import (
    extraction_confidence,
    parse_door_schedule,
)

DRAWINGS = pathlib.Path(__file__).resolve().parents[1] / "data" / "uccs" / "drawings.pdf"

_DOORS = parse_door_schedule(DRAWINGS)
_BY_MARK = {d.door_mark: d for d in _DOORS}


def _nospace(s: str) -> str:
    return s.replace(" ", "")


def test_door_count_near_ground_truth():
    assert 55 <= len(_DOORS) <= 62          # spec: "approximately 58"


def test_all_marks_north_or_south():
    assert all(d.door_mark[0] in ("N", "S") for d in _DOORS)


def test_extraction_confidence_high():
    assert extraction_confidence(_DOORS) >= 0.9


def test_anchor_N101A():
    d = _BY_MARK["N101A"]
    assert _nospace(d.width) == "6'-0\""
    assert _nospace(d.height) == "8'-91/2\""
    assert d.door_material == "AL & G"
    assert "Clear Anodized" in d.door_finish
    assert d.frame_material == "AL"
    assert d.hardware_set == "AL-11"
    assert d.glass_type == "GL-3"


def test_anchor_N107B_trace_linchpin():
    d = _BY_MARK["N107B"]
    assert _nospace(d.width) == "6'-0\""
    assert _nospace(d.height) == "7'-0\""
    assert d.door_material == "WD"          # wood door  -> spec section 081416
    assert d.door_finish == "WV-1"          # wood veneer
    assert d.frame_material == "HM"         # hollow metal frame -> spec section 081113
    assert d.hardware_set == "205"          # -> door hardware section 087100
    assert d.building == "North"


def test_merged_row_recovered():
    # N105A/N105B/N106A were merged into one extracted row; all must be recovered.
    for mark in ("N105A", "N105B", "N106A"):
        assert mark in _BY_MARK, f"{mark} missing (merged-row split failed)"
        assert _BY_MARK[mark].hardware_set == "AL-09"


def test_nonrated_doors_have_none_fire_rating():
    assert _BY_MARK["N107B"].fire_rating_minutes is None