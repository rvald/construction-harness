"""Unit tests for the reduce step (ADR-002). Pure + fast — no pipeline, no I/O.

Proves the dedup semantics that make the merge byte-identical to the serial run: first-wins
on (schedule, mark), in concatenated window order, empty marks dropped.
"""
from __future__ import annotations

from service.takeoff.reduce import merge_partials


def _item(schedule, mark, page):
    return {"schedule": schedule, "mark": mark, "source": {"page_index": page}}


def test_concatenates_in_window_order_when_no_dups():
    a = [_item("door", "N101A", 5), _item("door", "N101B", 5)]
    b = [_item("finish", "R100", 60)]
    assert merge_partials([a, b]) == a + b


def test_cross_window_dedup_keeps_first_occurrence():
    # same (schedule, mark) on an earlier window (page 5) and a later window (page 90):
    # the earlier one wins, exactly as the serial global `seen` would do.
    early = [_item("plumbing_fixture", "WC-1", 5)]
    late = [_item("plumbing_fixture", "WC-1", 90)]
    merged = merge_partials([early, late])
    assert merged == early
    assert merged[0]["source"]["page_index"] == 5


def test_dedup_within_a_single_partition_too():
    part = [_item("door", "D1", 5), _item("door", "D1", 5)]
    assert merge_partials([part]) == [part[0]]


def test_empty_mark_is_dropped():
    part = [_item("door", "", 5), _item("door", "D2", 5)]
    assert merge_partials([part]) == [part[1]]


def test_empty_inputs():
    assert merge_partials([]) == []
    assert merge_partials([[], []]) == []


def test_order_is_stable_across_many_windows():
    parts = [[_item("s", f"m{i}", i)] for i in range(10)]
    merged = merge_partials(parts)
    assert [it["mark"] for it in merged] == [f"m{i}" for i in range(10)]
