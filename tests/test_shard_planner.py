"""Unit tests for the shard planner (ADR-002, SC0). Pure — no pipeline, no I/O, no DB.

The two invariants under test:
  1. memory-safety   — no window exceeds max_candidates_per_shard candidates;
  2. byte-identical-safety — windows are contiguous, ordered, and cover [0, total_pages),
     so a merge in window order reproduces the serial sorted-page-order dedup.
"""
from __future__ import annotations

import pytest

from service.takeoff.planner import ShardWindow, plan_shard_windows


def _assert_covering_and_ordered(windows: list[ShardWindow], total_pages: int) -> None:
    assert windows[0].start == 0
    assert windows[-1].end == total_pages
    for a, b in zip(windows, windows[1:]):
        assert a.end == b.start          # contiguous, no gaps or overlaps
        assert a.start < a.end           # non-empty
    assert [w.index for w in windows] == list(range(len(windows)))


def test_no_candidates_is_single_window():
    assert plan_shard_windows([], 133, 30) == [ShardWindow(0, 0, 133, 0)]


def test_under_cap_is_single_window_equal_to_serial():
    # 20 candidates, cap 30 -> one window == the serial run (no fan-out).
    cands = list(range(0, 40, 2))
    out = plan_shard_windows(cands, 133, 30)
    assert out == [ShardWindow(0, 0, 133, 20)]


def test_splits_when_over_cap_and_respects_cap():
    # UCCS-like: 74 candidates spread across 133 pages, cap 30 -> 3 windows.
    cands = list(range(5, 5 + 74 * 1))          # 74 consecutive candidate pages
    total = 133
    windows = plan_shard_windows(cands, total, 30)
    _assert_covering_and_ordered(windows, total)
    assert len(windows) == 3                      # ceil(74/30)
    assert all(w.candidate_count <= 30 for w in windows)
    assert sum(w.candidate_count for w in windows) == 74


def test_boundary_falls_after_the_capth_candidate():
    cands = [1, 2, 3, 4, 5]
    windows = plan_shard_windows(cands, 10, 2)
    _assert_covering_and_ordered(windows, 10)
    # first cut after the 2nd candidate (page 2) -> [0,3); second after 4th (page 4) -> [3,5)
    assert windows[0] == ShardWindow(0, 0, 3, 2)
    assert windows[1] == ShardWindow(1, 3, 5, 2)
    assert windows[2] == ShardWindow(2, 5, 10, 1)


def test_cap_exactly_divides_candidates_no_empty_tail():
    cands = [0, 1, 2, 3]
    windows = plan_shard_windows(cands, 4, 2)
    # boundary after page 1 -> [0,2); after page 3 -> [2,4). No empty trailing window.
    assert windows == [ShardWindow(0, 0, 2, 2), ShardWindow(1, 2, 4, 2)]
    _assert_covering_and_ordered(windows, 4)


def test_dedupes_and_filters_out_of_range_candidates():
    windows = plan_shard_windows([3, 3, 3, -1, 999], 10, 30)
    assert windows == [ShardWindow(0, 0, 10, 1)]   # only page 3 is a real, unique candidate


def test_empty_document():
    assert plan_shard_windows([], 0, 30) == []


def test_invalid_args():
    with pytest.raises(ValueError):
        plan_shard_windows([], 133, 0)
    with pytest.raises(ValueError):
        plan_shard_windows([], -1, 30)
