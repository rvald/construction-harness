"""Tests for the Tier 1 generic quantity parser (quantity_schedules).

M1 goal: prove the generic, schema-driven parser reproduces the golden door/finish
extraction row-for-row (so the additive path can't drift from the graph inputs),
and that quantity/basis are assigned correctly.
"""
from __future__ import annotations

import pathlib

import pdfplumber

from src.pipeline.phase2_schedule_parser import (
    _select_schedule_table, parse_door_schedule, parse_finish_schedule,
)
from src.pipeline.quantity_schedules import (
    BASIS_ROW_COUNT, _looks_like_tag, _num, parse_schedule,
)
from src.pipeline.schedule_resolver import (
    DOOR_SCHEMA, FINISH_SCHEMA, WINDOW_SCHEMA, select_schedule_table,
)

DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "uccs"
DRAWINGS = DATA / "drawings.pdf"
PINNEY = DATA / "pinney" / "pinney_library_drawings_and_project_manual.pdf"


def _uccs_door_table():
    with pdfplumber.open(DRAWINGS) as pdf:
        return _select_schedule_table(pdf.pages[37].extract_tables())


def _uccs_finish_tables():
    with pdfplumber.open(DRAWINGS) as pdf:
        return pdf.pages[48].extract_tables()


# --- door parity ---------------------------------------------------------

def test_door_generic_matches_golden_marks():
    golden = parse_door_schedule()
    items = parse_schedule(_uccs_door_table(), DOOR_SCHEMA)
    assert [i.mark for i in items] == [d.door_mark for d in golden]
    assert len(items) == 60                                   # golden UCCS door count


def test_door_items_are_instance_counts():
    items = parse_schedule(_uccs_door_table(), DOOR_SCHEMA)
    assert all(i.shape == "instance" for i in items)
    assert all(i.quantity == 1.0 and i.unit == "EA" for i in items)
    assert all(i.quantity_basis == BASIS_ROW_COUNT for i in items)
    # aggregate count = sum of row_count quantities
    assert sum(i.quantity for i in items) == 60


def test_door_attributes_carry_resolved_fields():
    items = {i.mark: i for i in parse_schedule(_uccs_door_table(), DOOR_SCHEMA)}
    n107b = items["N107B"]
    assert n107b.attributes.get("door_material")              # a resolved field is present
    assert n107b.source == {"schedule": "door"}


# --- finish parity -------------------------------------------------------

def test_finish_generic_matches_golden_rooms():
    golden_rooms = {f.room_number for f in parse_finish_schedule()}
    marks: set[str] = set()
    for t in _uccs_finish_tables():
        if not t or len(t[0]) < 6:
            continue
        from src.pipeline.schedule_resolver import resolve_columns
        if resolve_columns(t, FINISH_SCHEMA).coverage < 0.75:
            continue
        marks |= {i.mark for i in parse_schedule(t, FINISH_SCHEMA)}
    assert marks == golden_rooms


# --- window: catalog path (Pinney) ---------------------------------------

def _pinney_window_table():
    with pdfplumber.open(PINNEY) as pdf:
        tables = pdf.pages[89].extract_tables()               # p90, composite window schedule
    return select_schedule_table(tables, WINDOW_SCHEMA)


def test_window_table_is_discovered_by_header():
    assert _pinney_window_table() is not None                 # resolver finds it by header coverage


def test_window_items_are_catalog_count_pending():
    items = parse_schedule(_pinney_window_table(), WINDOW_SCHEMA)
    assert items, "expected window catalog rows"
    assert all(i.shape == "catalog" for i in items)
    # catalog rows carry spec/size but no instance count -> explicit unknown
    assert all(i.quantity is None and i.unit is None for i in items)
    assert all(i.quantity_basis == "unknown_plan_count" for i in items)
    marks = {i.mark for i in items}
    assert {"A", "B", "C"} <= marks                           # composite window marks


def test_window_captures_size_and_glazing_area():
    items = {i.mark: i for i in parse_schedule(_pinney_window_table(), WINDOW_SCHEMA)}
    a = items["A"]
    assert a.attributes.get("size")                           # size resolved
    assert a.attributes.get("daylight_area")                  # DAYLIGHT AREA (S.F.) resolved
    assert a.attributes.get("window_type")                    # TYPE resolved


# --- unit helpers --------------------------------------------------------

def test_looks_like_tag():
    for good in ("A", "WC-1", "L1", "GPO-2", "W12"):
        assert _looks_like_tag(good), good
    for bad in ("TYPE", "NAME", "NORTH - EAST", ""):
        assert not _looks_like_tag(bad), bad


def test_num_extracts_leading_number():
    assert _num("22.32") == 22.32
    assert _num("12 EA") == 12.0
    assert _num("n/a") is None
