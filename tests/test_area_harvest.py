"""Tests for Tier 2 SF-label floor-area harvest (area_harvest).

M1: extraction + signature-based location on the real UCCS area/occupancy plan
(p4), using the finish schedule's rooms as the known-room set.
"""
from __future__ import annotations

import pathlib

import fitz

from src.pipeline.area_harvest import (
    locate_area_plans, positioned_tokens, room_tokens, sf_labels,
)
from src.pipeline.phase2_schedule_parser import parse_finish_schedule

DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "uccs"
DRAWINGS = DATA / "drawings.pdf"

_KNOWN_ROOMS = {f.room_number for f in parse_finish_schedule()}


def _tokens(page_index: int):
    with fitz.open(DRAWINGS) as doc:
        return positioned_tokens(doc[page_index])


def test_sf_labels_extracted_from_area_plan():
    labels = sf_labels(_tokens(3))                    # p4 = occupancy/area plan
    areas = {a for a, _, _ in labels}
    assert len(labels) >= 8
    assert {816.0, 1024.0, 781.0} <= areas            # measured per-room SF labels


def test_room_tokens_intersect_known_rooms():
    rooms = {r for r, _, _ in room_tokens(_tokens(3), _KNOWN_ROOMS)}
    assert {"N105", "N138", "S102"} <= rooms
    assert rooms <= _KNOWN_ROOMS                       # never invents a room


def test_locate_area_plans_picks_the_area_sheet():
    # p4 (index 3) has SF labels + rooms; p15 (index 14) has rooms but no SF labels.
    pages = [(3, _tokens(3)), (14, _tokens(14))]
    assert locate_area_plans(pages, _KNOWN_ROOMS) == [3]
