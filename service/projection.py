"""Project the takeoff artifact into queryable entity rows (ADR-003 QA0).

`project` is pure — a report dict in, row dicts out (with `ordinal` preserving the artifact's
order). `shred_entities` writes them idempotently (delete-then-insert per job) and is called
from both terminal paths (single build + sharded reduce), so every completed job populates
identical rows. The blob stays canonical; these rows are a rebuildable projection of it.

Every field here is either extracted straight from a pipeline record or its provenance —
nothing derived or interpretive (the grounding rule, ADR-003 §2).
"""
from __future__ import annotations

from service.models import FixtureCountRow, RoomAreaRow, ScheduleItemRow


def _item_row(ordinal: int, d: dict) -> dict:
    src = d.get("source") or {}
    return {
        "ordinal": ordinal,
        "schedule": d["schedule"],
        "shape": d["shape"],
        "mark": d["mark"],
        "quantity": d.get("quantity"),
        "unit": d.get("unit"),
        "quantity_basis": d["quantity_basis"],
        "description": d.get("description", ""),
        "attributes": d.get("attributes") or {},
        "src_file_id": src.get("file_id"),
        "src_page_index": src.get("page_index"),
    }


def _area_row(ordinal: int, d: dict) -> dict:
    src = d.get("source") or {}
    return {
        "ordinal": ordinal,
        "room_number": d["room_number"],
        "area_sf": d["area_sf"],
        "confidence": d["confidence"],
        "basis": d.get("basis", ""),
        "src_file_id": src.get("file_id"),
        "src_page_index": src.get("page_index"),
    }


def _count_row(ordinal: int, d: dict) -> dict:
    # CountResult provenance is the (1-indexed) sheet_page; `source` is a kind string.
    return {
        "ordinal": ordinal,
        "symbol_id": d["symbol_id"],
        "sheet_page": d["sheet_page"],
        "count": d["count"],
        "confidence": d["confidence"],
        "source": d.get("source", "text_tag"),
        "verified": d.get("verified", False),
        "boxes": d.get("boxes") or [],
    }


def project(report: dict) -> dict[str, list[dict]]:
    """Pure transform: report -> {schedule_items, room_areas, fixture_counts} row dicts."""
    return {
        "schedule_items": [_item_row(i, d) for i, d in enumerate(report.get("items", []))],
        "room_areas": [_area_row(i, d) for i, d in enumerate(report.get("room_areas", []))],
        "fixture_counts": [_count_row(i, d) for i, d in enumerate(report.get("fixture_counts", []))],
    }


def shred_entities(session, job_id: str, report: dict) -> dict[str, int]:
    """Idempotently replace `job_id`'s entity rows with the projection of `report`.
    Returns the per-table row counts. Runs inside the caller's transaction."""
    rows = project(report)
    for model in (ScheduleItemRow, RoomAreaRow, FixtureCountRow):
        session.query(model).filter_by(job_id=job_id).delete()
    session.add_all(ScheduleItemRow(job_id=job_id, **r) for r in rows["schedule_items"])
    session.add_all(RoomAreaRow(job_id=job_id, **r) for r in rows["room_areas"])
    session.add_all(FixtureCountRow(job_id=job_id, **r) for r in rows["fixture_counts"])
    return {k: len(v) for k, v in rows.items()}
