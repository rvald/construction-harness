"""Tests for the finish schedule parser (Milestone 8)."""
from __future__ import annotations

import pathlib
import re

from src.pipeline.phase2_schedule_parser import (
    parse_applied_finish_list,
    parse_finish_schedule,
)

DRAWINGS = pathlib.Path(__file__).resolve().parents[1] / "data" / "uccs" / "drawings.pdf"

_ROOMS = parse_finish_schedule(DRAWINGS)
_APPLIED = parse_applied_finish_list(DRAWINGS)
_BY_ROOM = {r.room_number: r for r in _ROOMS}
_CODE = re.compile(r"[A-Z]{1,4}-\d+[A-Z]?")


def test_room_count():
    # Spec estimated 30-50; the real schedule covers both buildings (~65).
    assert 30 <= len(_ROOMS) <= 80


def test_all_room_numbers_north_or_south():
    assert all(r.room_number[0] in ("N", "S") for r in _ROOMS)


def test_known_room():
    r = _BY_ROOM["N102"]
    assert r.room_name == "STUDENT LIVING ROOM"
    assert r.floor_finish == "CPT-3"
    assert r.base_finish == "WB-2"


def test_rooms_have_core_finishes():
    # Floor/base/wall should be populated for the vast majority of rooms.
    core = sum(1 for r in _ROOMS if r.floor_finish and r.base_finish and r.wall_finish)
    assert core / len(_ROOMS) >= 0.85


def test_applied_list_has_key_codes():
    for code in ("CPT-1", "P-1", "ACT-1", "WB-2", "CPT-7"):
        assert code in _APPLIED, f"{code} missing from applied finish list"
    assert "PAINT" in _APPLIED["P-1"].upper()


def test_room_codes_mostly_resolve():
    used: set[str] = set()
    for r in _ROOMS:
        for f in (r.floor_finish, r.base_finish, r.wall_finish, r.ceiling_finish):
            used.update(_CODE.findall(f))
    resolved = sum(1 for c in used if c in _APPLIED)
    # Some source-level code drift exists (CONC-* vs CON-*); most should resolve.
    assert resolved / len(used) >= 0.8