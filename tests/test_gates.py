"""Tests for validation gates and reporting (Milestone 12)."""
from __future__ import annotations

import pathlib

from src.validation.gates import run_all

_BASE = pathlib.Path(__file__).resolve().parents[1] / "data" / "uccs"
_REPORT = run_all(_BASE / "project_manual.pdf", _BASE / "drawings.pdf")


def _gate(name: str) -> dict:
    return next(g for g in _REPORT["gates"] if g["name"] == name)


def test_all_gates_pass():
    assert _REPORT["all_gates_passed"] is True


def test_report_structure():
    for key in ("gates", "graph_stats", "connection_rates", "unresolved", "confidence"):
        assert key in _REPORT


def test_phase2_gates_present_and_pass():
    for name in ("toc_section_count", "all_divisions_present", "door_schedule_size",
                 "finish_schedule_size", "abbreviation_list_size"):
        assert _gate(name)["passed"]


def test_phase3_sheet_and_page_verification():
    assert _gate("sheet_count")["metric"] == 133
    assert _gate("sample_page_numbers_verified")["passed"]


def test_phase5_resolution_rates():
    assert _REPORT["connection_rates"]["door_to_spec"] == 1.0
    assert _REPORT["connection_rates"]["room_to_finish"] >= 0.9


def test_no_isolated_element_nodes():
    assert _gate("element_connectivity")["passed"]


def test_domain_rules_pass():
    for name in ("doors_have_hardware_set", "doors_have_frame_material", "rooms_have_floor_finish"):
        assert _gate(name)["passed"]


def test_unresolved_inventory_populated():
    u = _REPORT["unresolved"]
    assert u["orphan_spec_count"] > 0          # unreferenced specs are surfaced
    assert len(u["missing_connections"]) >= 1  # unresolvable finish codes surfaced
    assert u["orphan_doors"] == []             # but no orphan doors