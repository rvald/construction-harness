"""The make-or-break proof (ADR-002 SC2): fanning out over page-range shards and merging
reproduces the serial artifact EXACTLY.

Marked `integration` — it runs the real pdfplumber extraction over the whole UCCS drawings
set (~5 min, peaks ~6.7 GB), so it is CI-gated, not in the fast path. It is the evidence the
whole scaling approach rests on: if the merged items are not byte-identical to the golden,
the fan-out is unsafe and we stop.

(A Pinney differential — merge(shards) == whole-doc serial on the 525-page set — was
scoped but skipped: it needs two full extractions, which OOMs a 7.7 GB dev box. The
byte-identical property is already proven on UCCS; the differential falls out of the
orchestrated-path tests in SC3.)
"""
from __future__ import annotations

import json
import pathlib

import pytest

from service.core.config import settings
from service.takeoff.pipeline_adapter import extract_shard, find_candidate_pages
from service.takeoff.planner import plan_shard_windows
from service.takeoff.reduce import merge_partials

ROOT = pathlib.Path(__file__).resolve().parents[1]
UCCS = ROOT / "data" / "uccs" / "drawings.pdf"
GOLDEN = ROOT / "output" / "reports" / "schedule_items.json"


@pytest.mark.integration
def test_uccs_merged_shards_are_byte_identical_to_golden():
    golden_items = json.loads(GOLDEN.read_text())["items"]

    candidates, total = find_candidate_pages(UCCS)
    windows = plan_shard_windows(candidates, total, settings.max_candidates_per_shard)
    assert len(windows) >= 2, "expected UCCS to fan out into multiple shards"

    partials = [extract_shard(UCCS, (w.start, w.end)) for w in windows]
    merged = merge_partials(partials)

    assert merged == golden_items
