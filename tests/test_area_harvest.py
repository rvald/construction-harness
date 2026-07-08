"""Tests for Tier 2 SF-label floor-area harvest (area_harvest).

M1: extraction + signature-based location on the real UCCS area/occupancy plan
(p4), using the finish schedule's rooms as the known-room set.
"""
from __future__ import annotations

import pathlib

import fitz

from src.takeoff.area_harvest import (
    harvest_room_areas, join_areas, locate_area_plans, positioned_tokens,
    room_tokens, sf_labels,
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


# --- M2: filtered join + confidence --------------------------------------

def test_join_filters_by_distance_and_magnitude():
    rooms = [("A", 0.0, 0.0), ("B", 1000.0, 0.0)]
    labels = [
        (100.0, 10.0, 0.0),        # close to A -> binds
        (44403.0, 5.0, 5.0),       # building total: exceeds max_sf -> dropped
        (300.0, 1500.0, 0.0),      # 500pt from B (> max_dist) -> dropped
    ]
    out = {r.room_number: r for r in join_areas(rooms, labels)}
    assert set(out) == {"A"}
    assert out["A"].area_sf == 100.0
    assert out["A"].confidence > 0.8              # ~10pt away of 100pt budget


def test_join_one_label_binds_to_closest_room():
    # a single label between two rooms goes to the nearer one only
    rooms = [("A", 0.0, 0.0), ("B", 60.0, 0.0)]
    labels = [(200.0, 10.0, 0.0)]
    out = {r.room_number for r in join_areas(rooms, labels)}
    assert out == {"A"}


def test_assemble_reports_area_coverage():
    from src.models.schedule import RoomArea, ScheduleItem
    from src.takeoff.build_schedule_items import assemble
    items = [
        ScheduleItem("finish", "instance", "N105", 1.0, "EA", "row_count"),
        ScheduleItem("finish", "instance", "N138", 1.0, "EA", "row_count"),
        ScheduleItem("door", "instance", "D1", 1.0, "EA", "row_count"),
    ]
    areas = [RoomArea("N105", 816.0, 0.9)]
    report = assemble(items, areas, finish_rooms={"N105", "N138"})
    assert report["area_coverage"] == {"finish_rooms": 2, "rooms_with_area": 1, "coverage": 0.5}
    assert report["room_areas"][0]["area_sf"] == 816.0


def test_harvest_room_areas_on_uccs_area_plan():
    areas = harvest_room_areas(DRAWINGS, _KNOWN_ROOMS, page_range=range(3, 4))
    by_room = {a.room_number: a for a in areas}
    assert by_room["N105"].area_sf == 816.0
    assert by_room["N138"].area_sf == 1024.0
    assert by_room["S102"].area_sf == 781.0
    assert all(0.0 <= a.confidence <= 1.0 for a in areas)
    assert all(a.source["page_index"] == 3 for a in areas)
    assert all(a.area_sf <= 20000.0 for a in areas)          # no building/zone totals
    assert set(by_room) <= _KNOWN_ROOMS                      # only real rooms
