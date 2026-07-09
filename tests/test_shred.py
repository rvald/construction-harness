"""Integration test for shred_entities (ADR-003 QA0). Writes the golden report's rows into
real Postgres and checks counts, provenance, idempotency, and the grounding invariant
(shredded row counts == the pipeline's own summary). Requires TAKEOFF_DATABASE_URL; marked
integration. No pipeline / pdfplumber — memory-light.
"""
from __future__ import annotations

import json
import pathlib
import uuid

import pytest

from service.db import session_scope
from service.models import (
    FixtureCountRow, RoomAreaRow, ScheduleItemRow, TakeoffJob,
)
from service.pipeline_adapter import ENTITY_SCHEMA_VERSION
from service.projection import shred_entities

pytestmark = pytest.mark.integration

ROOT = pathlib.Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "output" / "reports" / "schedule_items.json"


def _make_job() -> str:
    job_id = str(uuid.uuid4())
    with session_scope() as s:
        s.add(TakeoffJob(id=job_id, content_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
                         config={}, config_hash=uuid.uuid4().hex,
                         status="succeeded", pdf_object_key=f"uploads/{job_id}/drawings.pdf",
                         entity_schema_version=ENTITY_SCHEMA_VERSION))
    return job_id


def _counts(s, job_id):
    return (
        s.query(ScheduleItemRow).filter_by(job_id=job_id).count(),
        s.query(RoomAreaRow).filter_by(job_id=job_id).count(),
        s.query(FixtureCountRow).filter_by(job_id=job_id).count(),
    )


def test_shred_persists_grounded_rows_and_is_idempotent():
    report = json.loads(GOLDEN.read_text())
    job_id = _make_job()

    with session_scope() as s:
        shred_entities(s, job_id, report)

    with session_scope() as s:
        items, areas, counts = _counts(s, job_id)
        assert items == len(report["items"])
        assert areas == len(report["room_areas"])
        assert counts == len(report["fixture_counts"])

        # grounding: shredded schedule-item counts == the pipeline's own summary
        assert items == report["summary"]["total_items"]
        from collections import Counter
        by_schedule = dict(Counter(
            r.schedule for r in s.query(ScheduleItemRow).filter_by(job_id=job_id)))
        assert by_schedule == report["summary"]["by_schedule"]

        # provenance survived to the row
        first = (s.query(ScheduleItemRow).filter_by(job_id=job_id)
                 .order_by(ScheduleItemRow.ordinal).first())
        assert first.src_page_index == report["items"][0]["source"].get("page_index")

    # idempotent: re-shred does not double the rows
    with session_scope() as s:
        shred_entities(s, job_id, report)
    with session_scope() as s:
        assert _counts(s, job_id) == (len(report["items"]),
                                      len(report["room_areas"]),
                                      len(report["fixture_counts"]))
