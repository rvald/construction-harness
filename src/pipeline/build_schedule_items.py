"""Tier 1 — schedule_items.json artifact builder (M4).

Runs the signature-gated quantity driver over a drawings file and writes the
unified quantity view: every schedule row as a ScheduleItem, plus a summary of
reported metrics (counts by schedule, by quantity basis, known-quantity total).

This is a STANDALONE artifact: it does not touch output/reports/validation_report.json
(the golden traceability report). Keeping the two separate means the ~min-long
table scan never slows the graph/gates run, and the golden stays byte-identical.

Run:  python -m src.pipeline.build_schedule_items
"""
from __future__ import annotations

import json
import pathlib

from src.pipeline.quantity_schedules import extract_schedule_items, summarize

_DEFAULT_PDF = pathlib.Path(__file__).resolve().parents[2] / "data" / "uccs" / "drawings.pdf"
_OUT = pathlib.Path(__file__).resolve().parents[2] / "output" / "reports" / "schedule_items.json"


def build_schedule_items(drawings_path=_DEFAULT_PDF, page_range=None) -> dict:
    """Extract schedule items from a drawings file and return {summary, items}."""
    items = extract_schedule_items(drawings_path, page_range=page_range)
    return {"summary": summarize(items), "items": [it.to_dict() for it in items]}


if __name__ == "__main__":
    report = build_schedule_items()
    print("schedule item summary:")
    print(json.dumps(report["summary"], indent=2))
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nwrote {_OUT}  ({report['summary']['total_items']} items)")
