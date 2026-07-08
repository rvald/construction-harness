"""Tests for the artifact locator + document map (Document Locator, M4/M5).

Two kinds of assertion:
  * UCCS regression — the locator must rediscover the pages the parsers currently
    hardcode (0-based): TOC run 4-8, index 1, door 37, finish 48, abbrev 5. This
    proves discovery is CORRECT, not that we reintroduced constants.
  * Pinney generalization — its schedules use different wording/rotation, so they
    must come back `absent` (flagged), never a crash or a silent wrong page.
"""
from __future__ import annotations

import pathlib

from src.models.document_map import STATUS_ABSENT, STATUS_FOUND
from src.pipeline.build_document_map import build_document_map

DATA = pathlib.Path(__file__).resolve().parents[2] / "data" / "uccs"
DRAWINGS = DATA / "drawings.pdf"
MANUAL = DATA / "project_manual.pdf"
PINNEY = pathlib.Path(__file__).resolve().parents[2] / "data" / "pinney" / "pinney_library_drawings_and_project_manual.pdf"

_UCCS = build_document_map([DRAWINGS, MANUAL])
_PINNEY = build_document_map([PINNEY])


# --- UCCS regression: rediscover the currently-hardcoded pages ---------------

def test_uccs_spec_toc_run():
    art = _UCCS.locate("spec_toc")
    assert art.status == STATUS_FOUND
    assert art.page_indices == [4, 5, 6, 7, 8]        # PDF pages 5-9


def test_uccs_drawing_index_page():
    art = _UCCS.locate("drawing_index")
    assert art.status == STATUS_FOUND
    assert art.page_indices == [1]                    # PDF page 2


def test_uccs_door_schedule_page():
    art = _UCCS.locate("door_schedule")
    assert art.status == STATUS_FOUND
    assert art.page_indices == [37]                   # PDF page 38 (A9.3.1)


def test_uccs_finish_schedule_page():
    art = _UCCS.locate("finish_schedule")
    assert art.status == STATUS_FOUND
    assert art.page_indices == [48]                   # PDF page 49 (AF2.4), not 34


def test_uccs_abbreviations_page():
    art = _UCCS.locate("abbreviations")
    assert art.status == STATUS_FOUND
    assert art.page_indices == [5]                    # PDF page 6 (A0.1)


def test_uccs_all_located_in_the_right_file():
    assert _UCCS.locate("spec_toc").pages[0].file_id == "project_manual"
    assert _UCCS.locate("door_schedule").pages[0].file_id == "drawings"


def test_uccs_completeness_perfect():
    assert _UCCS.completeness["score"] == 1.0
    assert _UCCS.completeness["missing"] == []


# --- Pinney generalization: degrade + flag, never crash or silent-wrong ------

def test_pinney_toc_found_in_manual_block():
    art = _PINNEY.locate("spec_toc")
    assert art.status == STATUS_FOUND
    # TOC of the specs sits inside the big manual block (pages 97-505), not page 1.
    assert all(97 <= i <= 505 for i in art.page_indices)


def test_pinney_door_schedule_detected_via_coverage():
    # Softened detection (M3): Pinney's 16-col door schedule is now recognized by
    # header coverage, where the old exactly-14-col signature rejected it.
    art = _PINNEY.locate("door_schedule")
    assert art.status == STATUS_FOUND
    assert art.page_indices == [88]


def test_pinney_remaining_schedules_absent_not_crashed():
    # No room-finish schedule exists in Pinney, and its index doesn't match yet.
    for name in ("drawing_index", "finish_schedule"):
        art = _PINNEY.locate(name)
        assert art.status == STATUS_ABSENT
        assert art.pages == []


def test_pinney_completeness_reports_the_gaps():
    comp = _PINNEY.completeness
    assert comp["score"] < 1.0
    assert set(comp["missing"]) == {"drawing_index", "finish_schedule"}
    assert comp["not_applicable"] == []               # both regions exist, so nothing is N/A
