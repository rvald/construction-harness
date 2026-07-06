"""Tests for the header-driven schedule resolver (Schedule Resolver, M1).

Runs against the real extracted tables:
  * UCCS door (14-col, ALL CAPS)   — must reproduce the current positional mapping.
  * Pinney door (16-col, mixed case, grouped, explicit Location) — generalization.
  * UCCS finish (7-col)            — must reproduce its positional mapping.
"""
from __future__ import annotations

import pathlib

import pdfplumber

from src.pipeline.phase2_schedule_parser import _clean, _select_schedule_table
from src.pipeline.schedule_resolver import (
    DOOR_SCHEMA, FINISH_SCHEMA, normalize, resolve_columns,
)

DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "uccs"
DRAWINGS = DATA / "drawings.pdf"
PINNEY = DATA / "pinney" / "pinney_library_drawings_and_project_manual.pdf"


def _uccs_door_table():
    with pdfplumber.open(DRAWINGS) as pdf:
        return _select_schedule_table(pdf.pages[37].extract_tables())


def _pinney_door_table():
    with pdfplumber.open(PINNEY) as pdf:
        tabs = [t for t in pdf.pages[88].extract_tables() if t]
    return max(tabs, key=lambda t: len(t[0]))


def _uccs_finish_table():
    with pdfplumber.open(DRAWINGS) as pdf:
        tabs = pdf.pages[48].extract_tables()
    for t in tabs:
        if t and len(t[0]) == 7:
            header = " ".join(_clean(c) for row in t[:3] for c in row).upper()
            if "ROOM FINISH SCHEDULE" in header:
                return t
    raise AssertionError("UCCS finish table not found")


_UCCS_DOOR = resolve_columns(_uccs_door_table(), DOOR_SCHEMA)
_PINNEY_DOOR = resolve_columns(_pinney_door_table(), DOOR_SCHEMA)
_UCCS_FINISH = resolve_columns(_uccs_finish_table(), FINISH_SCHEMA)


def test_normalize():
    assert normalize("FIRE RATING (MINUTES)") == "fire rating minutes"
    assert normalize("Frame Elevatio") == "frame elevatio"


def test_uccs_door_reproduces_positional_mapping():
    expected = {
        0: "door_mark", 1: "fire_rating_minutes", 2: "width", 3: "height",
        4: "door_elevation_type", 5: "door_material", 6: "door_finish",
        7: "frame_elevation_type", 8: "frame_material", 9: "frame_finish",
        10: "hardware_set", 11: "glass_film", 12: "glass_type", 13: "special_notes",
    }
    assert _UCCS_DOOR.mapping == expected
    assert _UCCS_DOOR.data_start == 3
    assert _UCCS_DOOR.coverage == 1.0


def test_pinney_door_resolves_core_and_location():
    by_field = _PINNEY_DOOR.by_field
    for f in ("door_mark", "width", "height", "door_material", "door_elevation_type",
              "frame_material", "fire_rating_minutes"):
        assert f in by_field, f
    assert "location" in by_field                 # Pinney has an explicit Location column
    assert _PINNEY_DOOR.coverage == 1.0


def test_pinney_door_group_disambiguation():
    by_field = _PINNEY_DOOR.by_field
    # door vs frame material resolve to *different* columns via group composition
    assert by_field["door_material"] != by_field["frame_material"]


def test_uccs_finish_reproduces_positional_mapping():
    expected = {
        0: "room_number", 1: "room_name", 2: "floor_finish", 3: "base_finish",
        4: "wall_finish", 5: "ceiling_finish", 6: "comments",
    }
    assert _UCCS_FINISH.mapping == expected
    assert _UCCS_FINISH.coverage == 1.0
