"""Unit tests for the pure projection (ADR-003 QA0). Fast — no DB, no pipeline.

Uses the committed golden report as input and checks the row mapping + the grounding
self-consistency seed (projected per-schedule counts == the pipeline's own summary).
"""
from __future__ import annotations

import json
import pathlib

import pytest

from service.takeoff.projection import project

ROOT = pathlib.Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "output" / "reports" / "schedule_items.json"


@pytest.fixture(scope="module")
def report():
    return json.loads(GOLDEN.read_text())


def test_row_counts_match_the_artifact(report):
    rows = project(report)
    assert len(rows["schedule_items"]) == len(report["items"])
    assert len(rows["room_areas"]) == len(report["room_areas"])
    assert len(rows["fixture_counts"]) == len(report["fixture_counts"])


def test_ordinal_preserves_artifact_order(report):
    rows = project(report)
    for name in ("schedule_items", "room_areas", "fixture_counts"):
        assert [r["ordinal"] for r in rows[name]] == list(range(len(rows[name])))


def test_schedule_item_mapping_carries_provenance(report):
    rows = project(report)["schedule_items"]
    src = report["items"][0]["source"]
    r0 = rows[0]
    assert r0["schedule"] == report["items"][0]["schedule"]
    assert r0["mark"] == report["items"][0]["mark"]
    assert r0["quantity_basis"] == report["items"][0]["quantity_basis"]
    assert r0["src_file_id"] == src.get("file_id")
    assert r0["src_page_index"] == src.get("page_index")


def test_fixture_count_mapping(report):
    if not report["fixture_counts"]:
        pytest.skip("golden has no fixture counts")
    r = project(report)["fixture_counts"][0]
    src = report["fixture_counts"][0]
    assert r["symbol_id"] == src["symbol_id"]
    assert r["sheet_page"] == src["sheet_page"]           # provenance
    assert r["confidence"] == src["confidence"]
    assert r["verified"] == src["verified"]
    assert r["boxes"] == src["boxes"]


def test_room_area_mapping(report):
    if not report["room_areas"]:
        pytest.skip("golden has no room areas")
    r = project(report)["room_areas"][0]
    src = report["room_areas"][0]
    assert r["room_number"] == src["room_number"]
    assert r["area_sf"] == src["area_sf"]
    assert r["confidence"] == src["confidence"]


def test_grounding_projected_counts_equal_pipeline_summary(report):
    """The self-consistency seed: per-schedule row counts == report.summary.by_schedule."""
    from collections import Counter
    rows = project(report)["schedule_items"]
    by_schedule = dict(Counter(r["schedule"] for r in rows))
    assert by_schedule == report["summary"]["by_schedule"]
    assert len(rows) == report["summary"]["total_items"]
