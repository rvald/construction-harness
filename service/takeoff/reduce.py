"""The reduce step (ADR-002 §5) — pure, no pipeline import, no I/O.

Merge the per-shard partials (each a list of item dicts, already in sorted-page order and
deduped within its window) into the global item list. This is a LIGHT reduce: concatenate
the partials in window order, then apply first-wins dedup on `(schedule, mark)`.

Because shard windows are contiguous and ordered (see `service.takeoff.planner`), concatenating them
reproduces the serial builder's whole-document page order, and a single `seen` set gives the
same first-wins result as the serial extractor's global dedup. The dedup rule mirrors
`extract_schedule_items` exactly: an item with an empty `mark`, or a `(schedule, mark)` seen
earlier, is dropped. This is what makes the merged artifact byte-identical to the golden
(ADR-002 D5).
"""
from __future__ import annotations


def merge_partials(partials: list[list[dict]]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for part in partials:                       # partials are in window (page) order
        for it in part:
            key = (it["schedule"], it["mark"])
            if not it["mark"] or key in seen:
                continue
            seen.add(key)
            out.append(it)
    return out
