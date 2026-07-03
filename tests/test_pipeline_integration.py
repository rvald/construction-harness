"""Integration tests for the map-driven pipeline (Document Locator, M6/M7).

M6 — the pipeline runs off DISCOVERED pages (no hardcoded indices) and UCCS
behavior is unchanged: all gates still pass and the Door N107B trace still resolves.

M7 — on Pinney (combined, drawings-first, different firm) the pipeline runs without
crashing: it locates the manual TOC and parses real divisions from it, directly
fixing the original 'silent 0 divisions' failure, while honestly flagging the
differently-formatted schedules as absent.
"""
from __future__ import annotations

import pathlib

from src.pipeline.build_document_map import build_document_map
from src.pipeline.phase2_spec_parser import parse_spec_toc
from src.pipeline.phase5_graph_builder import build_graph
from src.validation.gates import run_all

DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "uccs"
DRAWINGS = DATA / "drawings.pdf"
MANUAL = DATA / "project_manual.pdf"
PINNEY = DATA / "pinney" / "pinney_library_drawings_and_project_manual.pdf"


# --- M6: UCCS unchanged, now driven by the map -------------------------------

def test_uccs_all_gates_pass_via_map():
    assert run_all(MANUAL, DRAWINGS)["all_gates_passed"] is True


def test_uccs_door_trace_still_resolves_via_map():
    kg = build_graph(MANUAL, DRAWINGS)
    assert "door:N107B" in kg.g
    rels = {r for _, r, _ in kg._out("door:N107B")}
    assert "FRAME_SPECIFIED_IN" in rels and "DOOR_SPECIFIED_IN" in rels


# --- M7: Pinney runs, TOC parses, gaps flagged -------------------------------

def test_pinney_toc_parses_from_located_page():
    dm = build_document_map([PINNEY])
    toc_art = dm.locate("spec_toc")
    assert toc_art.found

    old = parse_spec_toc(PINNEY)                                   # scan from page 0
    located = parse_spec_toc(PINNEY, start_page=toc_art.pages[0].page_index)

    # Original bug: on this drawings-first PDF the front-of-document scan finds
    # nothing and silently reports an empty manual.
    assert old.total_sections == 0
    # Locator fix: pointed at the located TOC page, divisions are recovered.
    assert len(located.divisions) >= 15
    assert len(located.divisions) > len(old.divisions)
    # Note: located.total_sections is still 0 — Pinney's section-line grammar
    # differs from UCCS. That's the DEFERRED field-level generalization, not a
    # locator concern: this phase's job (find the manual TOC) is done.


def test_pinney_flags_absent_schedules_without_crashing():
    dm = build_document_map([PINNEY])
    assert dm.completeness["score"] < 1.0
    assert set(dm.completeness["missing"]) == {"drawing_index", "door_schedule", "finish_schedule"}
