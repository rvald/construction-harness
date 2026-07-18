"""Deterministic cross-tier reconciliation over a takeoff's pipeline outputs.

The verifier's core: given a job's full items / fixture counts / room areas (all from the
pipeline, fetched via the API), compute the GAPS between the tiers — catalog types with no
plan count, symbols counted on multiple sheets (double-count risk), finish rooms with no
harvested area, unverified counts. It emits gaps and flags ONLY; it never produces a new
quantity, count, area, or confidence. Catalog schedules are inferred from each item's
`shape`, so this stays decoupled from the pipeline's internal list of counted schedules.
"""
from __future__ import annotations

from collections import defaultdict

from .client import TakeoffClient

_PAGE_SIZE = 500


async def fetch_all(client: TakeoffClient, job_id: str) -> dict:
    """A job's complete grounded data: summary + every item / fixture count / room area.
    Pages through each entity so reconciliation never depends on what the model queried."""
    return {
        "summary": await client.summary(job_id),
        "items": await _fetch_pages(client.items, job_id),
        "fixture_counts": await _fetch_pages(client.fixture_counts, job_id),
        "room_areas": await _fetch_pages(client.room_areas, job_id),
    }


async def _fetch_pages(fetch, job_id: str) -> list[dict]:
    """Accumulate every row from a paginated endpoint: fetch(job_id, page=, page_size=)."""
    rows: list[dict] = []
    page = 1
    while True:
        resp = await fetch(job_id, page=page, page_size=_PAGE_SIZE)
        rows.extend(resp.get("data", []))
        if page >= resp.get("pagination", {}).get("total_pages", 1):
            break
        page += 1
    return rows


def reconcile(summary: dict, items: list[dict], counts: list[dict], areas: list[dict]) -> dict:
    """Pure cross-tier reconciliation → gaps/flags only (never a new number).

    - catalog_reconciliation: per catalog-shaped schedule, which marks (types) have a matching
      fixture-count symbol vs none (the count lives on the plans but no tag was found).
    - double_count_candidates: symbols counted on >= 2 sheets (per-sheet totals may double-count
      across overall/enlarged views; dedup is the verifier's job).
    - unverified_fixture_counts: count rows with verified == false.
    - area_gaps: finish rooms with no harvested area (the actual room list, for escalation).
    - manifest: incomplete / failed-shard signals carried from the run.
    """
    counted_symbols = {c["symbol_id"] for c in counts}

    catalog_marks: dict[str, list[str]] = defaultdict(list)
    for it in items:
        if it.get("shape") == "catalog" and it.get("mark"):
            catalog_marks[it["schedule"]].append(it["mark"])
    catalog_reconciliation = {}
    for schedule, marks in catalog_marks.items():
        without = sorted(m for m in marks if m not in counted_symbols)
        catalog_reconciliation[schedule] = {
            "types": len(marks),
            "with_counts": len(marks) - len(without),
            "without_counts": without,
        }

    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for c in counts:
        by_symbol[c["symbol_id"]].append({"page": c["sheet_page"], "count": c["count"]})
    double_count_candidates = sorted(
        ({"symbol_id": s, "candidate_total": sum(x["count"] for x in sheets),
          "sheets": sorted(sheets, key=lambda x: x["page"])}
         for s, sheets in by_symbol.items() if len(sheets) >= 2),
        key=lambda d: -d["candidate_total"],
    )

    finish_rooms = {it["mark"] for it in items if it.get("schedule") == "finish" and it.get("mark")}
    rooms_with_area = {a["room_number"] for a in areas}
    without_area = sorted(finish_rooms - rooms_with_area)

    return {
        "catalog_reconciliation": catalog_reconciliation,
        "double_count_candidates": double_count_candidates,
        "unverified_fixture_counts": sum(1 for c in counts if not c.get("verified", False)),
        "area_gaps": {
            "finish_rooms": len(finish_rooms),
            "with_area": len(finish_rooms & rooms_with_area),
            "without_area": without_area,
        },
        "manifest": {
            "incomplete": bool(summary.get("incomplete", False)),
            "failed_shards": summary.get("failed_shards", []),
        },
        "has_gaps": bool(
            any(v["without_counts"] for v in catalog_reconciliation.values())
            or without_area or double_count_candidates
        ),
    }
