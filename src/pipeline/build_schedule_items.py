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

from src.models.schedule import CountResult, RoomArea, ScheduleItem
from src.pipeline.area_harvest import harvest_room_areas
from src.pipeline.fixture_counts import extract_counts, summarize_counts
from src.pipeline.quantity_schedules import extract_schedule_items, summarize

_DEFAULT_PDF = pathlib.Path(__file__).resolve().parents[2] / "data" / "uccs" / "drawings.pdf"
_OUT = pathlib.Path(__file__).resolve().parents[2] / "output" / "reports" / "schedule_items.json"


def area_coverage(room_areas: list[RoomArea], finish_rooms: set[str]) -> dict:
    """How many finish rooms got a harvested area (Tier 2 is deliberately partial)."""
    with_area = {a.room_number for a in room_areas}
    n = len(finish_rooms)
    return {
        "finish_rooms": n,
        "rooms_with_area": len(with_area & finish_rooms),
        "coverage": round(len(with_area & finish_rooms) / n, 3) if n else 0.0,
    }


def assemble(items: list[ScheduleItem], room_areas: list[RoomArea], finish_rooms: set[str],
             fixture_counts: list[CountResult] | None = None) -> dict:
    """Assemble the artifact dict from already-computed parts (pure — unit-testable)."""
    fixture_counts = fixture_counts or []
    return {
        "summary": summarize(items),
        "area_coverage": area_coverage(room_areas, finish_rooms),
        "fixture_count_summary": summarize_counts(fixture_counts),
        "items": [it.to_dict() for it in items],
        "room_areas": [a.to_dict() for a in room_areas],
        "fixture_counts": [c.to_dict() for c in fixture_counts],
    }


# catalog schedules whose tags get counted on the plans (each is text-tagged there)
_COUNTED_CATALOGS = ("plumbing_fixture", "lighting_fixture")


def count_fixtures(drawings_path, items, page_range=None) -> list[CountResult]:
    """Count each counted-catalog schedule's tags on the plans. The catalog and the
    schedule's own page(s) come from the extracted schedule items, so the fixture
    SCHEDULE sheet is excluded from the plan scan (it scatters the same tags)."""
    counts: list[CountResult] = []
    for kind in _COUNTED_CATALOGS:
        cat = [i for i in items if i.schedule == kind]
        if not cat:
            continue
        tags = [i.mark for i in cat]
        schedule_pages = {i.source.get("page_index") for i in cat if "page_index" in i.source}
        counts += extract_counts(drawings_path, tags, page_range=page_range,
                                 exclude_pages=schedule_pages)
    return counts


def build_schedule_items(drawings_path=_DEFAULT_PDF, page_range=None) -> dict:
    """Extract schedule items + harvest floor areas + count fixture tags -> the artifact.

    Floor areas join only to the finish schedule's rooms; fixture counts are per-sheet
    candidates over the plumbing + lighting catalogs (deduped total pending verification)."""
    items = extract_schedule_items(drawings_path, page_range=page_range)
    finish_rooms = {i.mark for i in items if i.schedule == "finish"}
    room_areas = harvest_room_areas(drawings_path, finish_rooms, page_range=page_range)
    fixture_counts = count_fixtures(drawings_path, items, page_range=page_range)
    return assemble(items, room_areas, finish_rooms, fixture_counts)


if __name__ == "__main__":
    report = build_schedule_items()
    print("schedule item summary:")
    print(json.dumps(report["summary"], indent=2))
    print("area coverage:")
    print(json.dumps(report["area_coverage"], indent=2))
    print("fixture count summary:")
    print(json.dumps(report["fixture_count_summary"], indent=2))
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nwrote {_OUT}  ({report['summary']['total_items']} items, "
          f"{len(report['room_areas'])} room areas, {len(report['fixture_counts'])} fixture counts)")
