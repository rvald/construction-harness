"""The ONE seam between the service and the takeoff pipeline.

Nothing else in ``service/`` imports ``src`` — so if the pipeline's internals move, this
is the only file that changes. We invoke the builder and return its outputs verbatim; we
never touch the pipeline's own ``output/reports/`` write path or its pure functions.

The builder's ``report`` and ``manifest`` are the pipeline's contract: provenance and
confidence(-basis) already ride on every record, and the manifest already carries checksum,
per-phase timing, and the per-page ``failures`` ledger. We preserve both as-is.
"""
from __future__ import annotations

from pathlib import Path

# The entity/artifact contract version the service serves. Bump when the shredding schema
# or the shape we expose changes — independent of the pipeline's own versioning.
ENTITY_SCHEMA_VERSION = "1.0.0"


def run_takeoff(pdf_path: str | Path) -> tuple[dict, dict]:
    """Run the takeoff builder on one drawings PDF -> (report, manifest).

    Imported lazily so the API process (which never runs the build) does not pull PyMuPDF/
    pdfplumber, and so importing this module stays cheap. Defaults reproduce the golden.
    """
    from src.takeoff.build_schedule_items import build_schedule_items

    report, manifest = build_schedule_items(Path(pdf_path))
    return report, manifest


def extract_shard(pdf_path: str | Path, page_range: tuple[int, int]) -> list[dict]:
    """The map step (ADR-002): extract schedule items over ONE page-range window.

    Returns items as plain dicts (the same shape as the artifact's `items` and the golden),
    in the pipeline's own sorted-page order. Items are deduped WITHIN the window by the
    extractor; cross-window dedup is the reduce's job (`service.reduce.merge_partials`).

    NB: the pipeline's `extract_schedule_items` iterates `for i in page_range`, so it wants an
    iterable of page indices — a ``range``, not a ``(start, end)`` tuple.
    """
    from src.takeoff.quantity_schedules import extract_schedule_items

    items = extract_schedule_items(Path(pdf_path), page_range=range(page_range[0], page_range[1]))
    return [it.to_dict() for it in items]


def assemble_report(pdf_path: str | Path, merged_items: list[dict]) -> dict:
    """The reduce's final step (ADR-002 §5): given the merged schedule items (from the map
    shards), run Wave 2 — area harvest + fixture counts over the whole doc — and assemble the
    final artifact, reusing the pipeline's own `assemble` so the output matches the serial
    builder exactly.

    Wave 2 is fitz-only (no pdfplumber), so it is memory-light (~150 MB) regardless of page
    count — the pdfplumber cost lives entirely in the sharded map. Items are rehydrated into
    the pipeline's `ScheduleItem` dataclass (Wave 2 + assemble read attributes, not dicts).
    """
    from dataclasses import fields

    from src.models.schedule import ScheduleItem
    from src.takeoff.area_harvest import harvest_room_areas
    from src.takeoff.build_schedule_items import assemble, count_fixtures

    names = {f.name for f in fields(ScheduleItem)}
    items = [ScheduleItem(**{k: v for k, v in d.items() if k in names}) for d in merged_items]

    finish_rooms = {i.mark for i in items if i.schedule == "finish"}
    room_areas = harvest_room_areas(Path(pdf_path), finish_rooms)
    fixture_counts = count_fixtures(Path(pdf_path), items)
    return assemble(items, room_areas, finish_rooms, fixture_counts)


def find_candidate_pages(pdf_path: str | Path) -> tuple[list[int], int]:
    """The cheap planner pass (ADR-002 D3): text-gate the whole doc, return the 0-based
    candidate page indices + total page count. No pdfplumber, so it is fast (~0.018 s/page)
    and light — it never triggers the expensive table extraction. Reuses the pipeline's own
    signature gate so the planner's notion of "candidate" matches the extractor's exactly.
    """
    from src.access.document import Document
    from src.takeoff.quantity_schedules import SCHEDULE_REGISTRY, _page_matches

    doc = Document(Path(pdf_path))
    try:
        candidates = [
            i for i in range(doc.page_count)
            if any(_page_matches(doc.page(i).get_text(), s) for s in SCHEDULE_REGISTRY)
        ]
        return candidates, doc.page_count
    finally:
        doc.close()
