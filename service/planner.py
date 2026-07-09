"""Shard planning (ADR-002, SC0) — pure, no I/O, no pipeline import.

Given the candidate pages (from a cheap text-gate pass) and the total page count, split
the document into shard windows. A shard window is a **contiguous, ordered, non-overlapping**
half-open page range `[start, end)`; the windows together cover `[0, total_pages)`.

Two invariants make this both memory-safe and byte-identical-safe:
  * each window holds at most `max_candidates_per_shard` candidate pages -> bounded peak
    memory (peak ~= mb_per_candidate * candidates_in_window);
  * windows are contiguous and in page order, so extracting them independently and merging
    in window order reproduces the serial builder's sorted-page-order, first-wins dedup
    (ADR-002 D5). This is why we cut sequentially, NOT arbitrary bin-packing.

When the whole document fits under the cap, this returns a single window == the serial run,
so "single vs sharded" needs no separate threshold: the memory budget IS the threshold.
"""
from __future__ import annotations

from typing import NamedTuple


class ShardWindow(NamedTuple):
    index: int
    start: int   # 0-based, inclusive
    end: int     # 0-based, exclusive
    candidate_count: int


def plan_shard_windows(
    candidate_pages: list[int],
    total_pages: int,
    max_candidates_per_shard: int,
    page_start: int = 0,
    page_end: int | None = None,
) -> list[ShardWindow]:
    """Windows cover `[page_start, page_end or total_pages)`. A submit-time page_range bounds
    the whole job to that window (only candidates inside it are considered/covered)."""
    if total_pages < 0:
        raise ValueError(f"total_pages must be >= 0, got {total_pages}")
    if max_candidates_per_shard < 1:
        raise ValueError(f"max_candidates_per_shard must be >= 1, got {max_candidates_per_shard}")

    lo = max(page_start, 0)
    hi = min(total_pages if page_end is None else page_end, total_pages)
    if lo >= hi:
        return []
    cands = sorted(set(p for p in candidate_pages if lo <= p < hi))

    # No candidates (or all fit in one shard): a single window == the serial run over [lo,hi).
    if len(cands) <= max_candidates_per_shard:
        return [ShardWindow(0, lo, hi, len(cands))]

    # Cut a boundary right AFTER every `cap`-th candidate; the tail runs to hi.
    boundaries: list[int] = []
    count = 0
    for page in cands:
        count += 1
        if count == max_candidates_per_shard:
            boundaries.append(page + 1)
            count = 0

    edges = [lo, *boundaries, hi]
    windows: list[ShardWindow] = []
    for start, end in zip(edges, edges[1:]):
        if start >= end:
            continue  # a boundary landing exactly on hi collapses the empty tail
        n = sum(1 for p in cands if start <= p < end)
        windows.append(ShardWindow(len(windows), start, end, n))
    return windows
