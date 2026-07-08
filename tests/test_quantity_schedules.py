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
from src.models.schedule import ScheduleItem
from src.takeoff.quantity_schedules import (
    BASIS_ROW_COUNT, _looks_like_tag, _num, extract_schedule_items, parse_page,
    parse_schedule, summarize,
)
from src.pipeline.schedule_resolver import (
    DOOR_SCHEMA, FINISH_SCHEMA, LIGHTING_FIXTURE_SCHEMA, PLUMBING_FIXTURE_SCHEMA,
    WINDOW_SCHEMA, select_schedule_table,
)

DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "uccs"
DRAWINGS = DATA / "drawings.pdf"
# Pinney lives under data/ (not data/uccs/) since the "move pinney dir" reorg.
PINNEY = pathlib.Path(__file__).resolve().parents[1] / "data" / "pinney" / "pinney_library_drawings_and_project_manual.pdf"


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


# --- plumbing fixture: catalog path (UCCS) -------------------------------

def _uccs_plumbing_table():
    with pdfplumber.open(DRAWINGS) as pdf:
        return select_schedule_table(pdf.pages[58].extract_tables(), PLUMBING_FIXTURE_SCHEMA)


def test_plumbing_table_discovered():
    assert _uccs_plumbing_table() is not None


def test_plumbing_items_are_catalog_with_descriptions():
    items = {i.mark: i for i in parse_schedule(_uccs_plumbing_table(), PLUMBING_FIXTURE_SCHEMA)}
    assert {"L-1", "MS-1"} <= set(items)                      # fixture tags resolved
    assert all(i.shape == "catalog" for i in items.values())
    assert items["MS-1"].description                          # DESCRIPTION carried onto the item
    # UCCS plumbing schedule has no real takeoff-count column -> count-pending
    assert all(i.quantity is None and i.quantity_basis == "unknown_plan_count"
               for i in items.values())


# --- lighting fixture catalog (A1 fan-out) -------------------------------

def test_lighting_fixture_catalog():
    with pdfplumber.open(DRAWINGS) as pdf:
        table = select_schedule_table(pdf.pages[105].extract_tables(), LIGHTING_FIXTURE_SCHEMA)
    items = parse_schedule(table, LIGHTING_FIXTURE_SCHEMA)          # E7.1 lighting fixture schedule
    marks = {i.mark for i in items}
    assert {"L2A", "L20K"} <= marks                                # header "TYPE" -> fixture_tag
    assert all(i.shape == "catalog" for i in items)


# --- security: instance-schedule counting (free-form device IDs) ---------

def test_security_camera_and_device_counts():
    from src.takeoff.quantity_schedules import extract_schedule_items
    items = extract_schedule_items(DRAWINGS, page_range=range(128, 130))    # p129 security schedules
    cams = [i for i in items if i.schedule == "camera"]
    devs = [i for i in items if i.schedule == "security_device"]
    assert len(cams) == 13 and len(devs) == 5                # direct row counts
    assert cams[0].shape == "instance" and cams[0].quantity == 1.0
    assert cams[0].quantity_basis == "row_count"
    assert cams[0].mark.startswith("C-")                    # free-form device number
    assert devs[0].mark.startswith(("ACP", "NVR", "PS"))


# --- M4 driver: multi-table, signature-gated extraction, summary ---------

def test_parse_page_captures_multiple_tables():
    # The plumbing schedule spans several tables on the page; parse_page aggregates
    # all that resolve, so both water closets (WC-1) and sinks (KS-1) are captured.
    with pdfplumber.open(DRAWINGS) as pdf:
        tables = pdf.pages[58].extract_tables()
    items = parse_page(tables, PLUMBING_FIXTURE_SCHEMA, {"schedule": "plumbing_fixture"})
    marks = {i.mark for i in items}
    assert {"WC-1", "KS-1"} <= marks                          # from different tables on the page


def test_extract_driver_finds_and_tags_source():
    # Signature gate + pdfplumber parse over just the plumbing page (fast, 1 page).
    items = extract_schedule_items(DRAWINGS, page_range=range(58, 59))
    assert items and all(i.schedule == "plumbing_fixture" for i in items)
    assert all(i.source["page_index"] == 58 for i in items)   # provenance recorded
    assert all(i.source["file_id"] == "drawings" for i in items)
    assert all(i.quantity_basis == "unknown_plan_count" for i in items)


def test_summarize_reports_metrics():
    items = [
        ScheduleItem("door", "instance", "D1", 1.0, "EA", BASIS_ROW_COUNT),
        ScheduleItem("door", "instance", "D2", 1.0, "EA", BASIS_ROW_COUNT),
        ScheduleItem("plumbing_fixture", "catalog", "WC-1", None, None, "unknown_plan_count"),
    ]
    s = summarize(items)
    assert s["total_items"] == 3
    assert s["by_schedule"] == {"door": 2, "plumbing_fixture": 1}
    assert s["known_quantity_total"] == 2.0                    # catalog item excluded
    assert s["count_pending_items"] == 1


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
