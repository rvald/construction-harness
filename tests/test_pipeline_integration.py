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

from src.models.document_map import STATUS_FOUND
from src.pipeline.build_document_map import build_document_map
from src.pipeline.phase2_schedule_parser import parse_door_schedule
from src.pipeline.phase2_spec_parser import parse_spec_toc
from src.pipeline.phase5_graph_builder import build_graph
from src.validation.gates import run_all

DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "uccs"
DRAWINGS = DATA / "drawings.pdf"
MANUAL = DATA / "project_manual.pdf"
PINNEY = pathlib.Path(__file__).resolve().parents[1] / "data" / "pinney" / "pinney_library_drawings_and_project_manual.pdf"


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
    # Grammar generalization: Pinney's section lines ("03 30 00 TITLE", no SECTION
    # keyword, no dash) now parse too — the manual is genuinely readable, not just
    # located. (Was 0 sections before the generalized SECTION_RE.)
    assert located.total_sections >= 80
    div_08 = next(d for d in located.divisions if d["number"] == "08")
    assert any(s["number"] == "081113" for s in div_08["sections"])


def test_pinney_door_schedule_extracts_end_to_end():
    # Located → columns resolved by header → rows found via discovered grammar.
    dm = build_document_map([PINNEY])
    art = dm.locate("door_schedule")
    assert art.status == STATUS_FOUND
    doors = parse_door_schedule(PINNEY, page_index=art.pages[0].page_index)
    assert len(doors) >= 50                                  # ~91 real doors (was 0 before)
    assert not all(d.door_mark[:1] in ("N", "S") for d in doors)   # Pinney's own mark grammar
    assert sum(1 for d in doors if d.door_material) >= 40          # header-resolved fields populated


def test_pinney_flags_remaining_gaps_without_crashing():
    dm = build_document_map([PINNEY])
    assert dm.completeness["score"] < 1.0
    # door_schedule now resolves; index + finish remain genuine gaps.
    assert set(dm.completeness["missing"]) == {"drawing_index", "finish_schedule"}
