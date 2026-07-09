"""Query API contract tests (ADR-003 QA1). Drives the endpoint functions directly against
real Postgres (rows shredded from the golden report) with the summary's blob read stubbed.
Marked integration (needs TAKEOFF_DATABASE_URL); memory-light (no pipeline).

The headline assertion is the grounding self-consistency invariant: the summary's aggregates
equal the counts the detail endpoints return.
"""
from __future__ import annotations

import json
import pathlib
import uuid

import pytest

from service import storage
from service.api import query
from service.db import session_scope
from service.errors import ApiError
from service.models import STATUS_QUEUED, TakeoffJob
from service.pipeline_adapter import ENTITY_SCHEMA_VERSION
from service.projection import shred_entities

pytestmark = pytest.mark.integration

ROOT = pathlib.Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "output" / "reports" / "schedule_items.json"


@pytest.fixture(scope="module")
def report():
    return json.loads(GOLDEN.read_text())


@pytest.fixture
def job(report, monkeypatch):
    """A succeeded job with the golden report shredded in; summary blob read stubbed."""
    job_id = str(uuid.uuid4())
    with session_scope() as s:
        s.add(TakeoffJob(id=job_id, content_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
                         config={}, config_hash=uuid.uuid4().hex,
                         status="succeeded", pdf_object_key=f"uploads/{job_id}/drawings.pdf",
                         artifact_object_key=f"artifacts/{job_id}/schedule_items.json",
                         entity_schema_version=ENTITY_SCHEMA_VERSION))
        shred_entities(s, job_id, report)
    monkeypatch.setattr(storage, "get_bytes",
                        lambda key: json.dumps(report).encode("utf-8"))
    return job_id


def test_summary_matches_detail_counts(job, report):
    """Grounding invariant: summary rollups == what the detail endpoints return."""
    summary = query.get_summary(job)
    all_items = query.get_items(job, page_size=500)
    assert summary.summary["total_items"] == all_items.pagination.total

    # per-schedule too
    for schedule, n in report["summary"]["by_schedule"].items():
        page = query.get_items(job, schedule=schedule, page_size=500)
        assert page.pagination.total == n
        assert all(r.schedule == schedule for r in page.data)


def test_records_carry_provenance(job):
    r = query.get_items(job, page_size=1).data[0]
    assert r.source.page_index is not None      # citable back to a source page
    assert r.quantity_basis                      # honesty field present


def test_pagination(job, report):
    total = len(report["items"])
    p1 = query.get_items(job, page=1, page_size=10)
    assert len(p1.data) == min(10, total)
    assert p1.pagination.total == total
    assert p1.pagination.total_pages == (total + 9) // 10
    # page 2 is disjoint from page 1 (ordered by ordinal)
    p2 = query.get_items(job, page=2, page_size=10)
    assert [r.mark for r in p1.data] != [r.mark for r in p2.data]


def test_fixture_count_and_room_filters(job):
    unverified = query.get_fixture_counts(job, verified=False, page_size=500)
    assert all(r.verified is False for r in unverified.data)

    # low-confidence rooms to review
    lo = query.get_room_areas(job, min_confidence=0.0, page_size=500)
    hi = query.get_room_areas(job, min_confidence=0.9, page_size=500)
    assert lo.pagination.total >= hi.pagination.total
    assert all(r.confidence >= 0.9 for r in hi.data)


def test_invalid_pagination_rejected(job):
    with pytest.raises(ApiError):
        query.get_items(job, page=0)
    with pytest.raises(ApiError):
        query.get_items(job, page_size=99999)


def test_state_gating_non_terminal_job():
    job_id = str(uuid.uuid4())
    with session_scope() as s:
        s.add(TakeoffJob(id=job_id, content_sha256="x" * 64, config={}, config_hash="c",
                         status=STATUS_QUEUED, pdf_object_key="k",
                         entity_schema_version=ENTITY_SCHEMA_VERSION))
    with pytest.raises(ApiError) as ei:
        query.get_items(job_id)
    assert ei.value.status_code == 409
