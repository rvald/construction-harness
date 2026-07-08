"""Proof of the reduce's second half (ADR-002 SC3): assembling the final artifact from the
merged items reproduces the serial builder's artifact exactly.

Fed the (already-proven) golden items as the "merged" input, `assemble_report` must
reproduce the WHOLE golden schedule_items.json — summary, area_coverage, room_areas,
fixture_counts, and all. Composed with SC2 (merge(shards) == golden items), this proves the
full sharded artifact == golden without ever running the pdfplumber map (which OOMs a small
box). Wave 2 is fitz-only, so this is memory-light (~150 MB) and fast (~5 s).
"""
from __future__ import annotations

import json
import pathlib

import pytest

from service.pipeline_adapter import assemble_report

ROOT = pathlib.Path(__file__).resolve().parents[1]
UCCS = ROOT / "data" / "uccs" / "drawings.pdf"
GOLDEN = ROOT / "output" / "reports" / "schedule_items.json"


@pytest.mark.integration
def test_assemble_report_from_merged_items_reproduces_golden():
    golden = json.loads(GOLDEN.read_text())
    report = assemble_report(UCCS, golden["items"])
    assert report == golden
