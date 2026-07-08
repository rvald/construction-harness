"""Tier 1 — schedule_items.json artifact builder (M4).

Runs the signature-gated quantity driver over a drawings file and writes the
unified quantity view: every schedule row as a ScheduleItem, plus a summary of
reported metrics (counts by schedule, by quantity basis, known-quantity total).

This is a STANDALONE artifact: it does not touch output/reports/validation_report.json
(the golden traceability report). Keeping the two separate means the ~min-long
table scan never slows the graph/gates run, and the golden stays byte-identical.

Run:  python -m src.takeoff.build_schedule_items
"""
from __future__ import annotations

import json
import pathlib
import time

from src.access.document import using_document
from src.models.schedule import CountResult, RoomArea, ScheduleItem
from src.takeoff.area_harvest import harvest_room_areas
from src.takeoff.fixture_counts import extract_counts, summarize_counts
from src.takeoff.quantity_schedules import extract_schedule_items, summarize

_DEFAULT_PDF = pathlib.Path(__file__).resolve().parents[2] / "data" / "uccs" / "drawings.pdf"
_OUT = pathlib.Path(__file__).resolve().parents[2] / "output" / "reports" / "schedule_items.json"
_MANIFEST_OUT = _OUT.with_name("schedule_items.manifest.json")


def _timed(timings: dict, name: str, fn):
    """Run fn(), record its wall-clock under `name`, return its result."""
    t = time.perf_counter()
    result = fn()
    timings[name] = round(time.perf_counter() - t, 3)
    return result


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


def count_fixtures(source, items, page_range=None) -> list[CountResult]:
    """Count each counted-catalog schedule's tags on the plans. `source` is a path OR the
    coordinator's shared Document (both extract_counts calls thread the same doc, so the
    plumbing + lighting scans reuse one page cache). The catalog and the schedule's own
    page(s) come from the extracted schedule items, so the fixture SCHEDULE sheet is
    excluded from the plan scan (it scatters the same tags)."""
    with using_document(source) as doc:
        counts: list[CountResult] = []
        for kind in _COUNTED_CATALOGS:
            cat = [i for i in items if i.schedule == kind]
            if not cat:
                continue
            tags = [i.mark for i in cat]
            schedule_pages = {i.source.get("page_index") for i in cat if "page_index" in i.source}
            counts += extract_counts(doc, tags, page_range=page_range, exclude_pages=schedule_pages)
        return counts


def build_schedule_items(source=_DEFAULT_PDF, *, config=None, page_range=None) -> tuple[dict, dict]:
    """Extract schedule items + harvest floor areas + count fixture tags -> (report, manifest).

    Opens ONE Document and threads it into all three consumers, so the drawings PDF is
    scanned once (shared page cache) instead of four times. Floor areas join only to the
    finish schedule's rooms; fixture counts are per-sheet candidates over the plumbing +
    lighting catalogs (deduped total pending verification). The manifest (checksum/timing/
    failures) is returned separately so it can ride in a sibling file — the report itself
    stays deterministic and diffable."""
    timings: dict = {}
    with using_document(source, config=config) as doc:
        items = _timed(timings, "schedules", lambda: extract_schedule_items(doc, page_range=page_range))
        finish_rooms = {i.mark for i in items if i.schedule == "finish"}
        room_areas = _timed(timings, "areas",
                            lambda: harvest_room_areas(doc, finish_rooms, page_range=page_range))
        fixture_counts = _timed(timings, "counts",
                               lambda: count_fixtures(doc, items, page_range=page_range))
        report = assemble(items, room_areas, finish_rooms, fixture_counts)
        manifest = {
            "file_id": doc.file_id,
            "checksum": doc.checksum,
            "page_count": doc.page_count,
            "config": doc.config.model_dump(),
            "timing": timings,
            "failures": doc.failures,
        }
    return report, manifest


if __name__ == "__main__":
    report, manifest = build_schedule_items()
    print("schedule item summary:")
    print(json.dumps(report["summary"], indent=2))
    print("area coverage:")
    print(json.dumps(report["area_coverage"], indent=2))
    print("fixture count summary:")
    print(json.dumps(report["fixture_count_summary"], indent=2))
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    _MANIFEST_OUT.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"\nwrote {_OUT}  ({report['summary']['total_items']} items, "
          f"{len(report['room_areas'])} room areas, {len(report['fixture_counts'])} fixture counts)")
    print(f"wrote {_MANIFEST_OUT}  (timing={manifest['timing']}, failures={len(manifest['failures'])})")
