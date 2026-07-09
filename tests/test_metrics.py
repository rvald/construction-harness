"""B3 tests (ADR-004): Prometheus metrics."""
from __future__ import annotations

import uuid

import pytest
from prometheus_client import generate_latest

from service import metrics
from service.db import session_scope
from service.models import TakeoffJob
from service.pipeline_adapter import ENTITY_SCHEMA_VERSION


def test_metric_families_exposed():
    metrics.SUBMISSIONS.labels(created="True").inc()
    metrics.REQUESTS.labels("POST", "/v1/takeoff/ingestions", 202).inc()
    metrics.REQUEST_LATENCY.labels("GET", "/v1/takeoff/ingestions/{job_id}").observe(0.01)
    text = generate_latest().decode()
    assert "takeoff_ingestions_submitted_total" in text
    assert "takeoff_requests_total" in text
    assert "takeoff_request_duration_seconds" in text
    assert "takeoff_jobs" in text and "takeoff_shards" in text


def test_render_is_scrape_safe_without_db(monkeypatch):
    # a DB failure during refresh must not break the scrape
    def _boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(metrics, "_refresh_db_gauges", _boom)
    body, ctype = metrics.render()
    assert b"takeoff_requests_total" in body and "text/plain" in ctype


@pytest.mark.integration
def test_job_gauges_reflect_db():
    def _mk(status):
        with session_scope() as s:
            s.add(TakeoffJob(id=str(uuid.uuid4()),
                             content_sha256=uuid.uuid4().hex + uuid.uuid4().hex, config={},
                             config_hash=uuid.uuid4().hex, status=status, pdf_object_key="k",
                             entity_schema_version=ENTITY_SCHEMA_VERSION))
    _mk("succeeded")
    _mk("failed")
    metrics._refresh_db_gauges()
    assert metrics.JOBS.labels(status="succeeded")._value.get() >= 1
    assert metrics.JOBS.labels(status="failed")._value.get() >= 1
