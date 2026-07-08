"""Orchestration flow test (ADR-002 SC3b). Drives plan -> shards -> completion-counter ->
reduce against a REAL Postgres (the atomic counter is the point), with storage and the
memory-heavy pdfplumber extraction STUBBED — so it runs fast and light on a small box while
still exercising the real control flow, shard rows, counter, and lifecycle.

Requires a running Postgres reachable via TAKEOFF_DATABASE_URL (see run_orchestration_test.sh);
marked `integration`.
"""
from __future__ import annotations

import uuid

import pytest

from service import pipeline_adapter as adapter
from service import orchestrator, storage
from service.config import settings
from service.db import session_scope
from service.models import STATUS_SUCCEEDED, TakeoffJob, TakeoffShard

pytestmark = pytest.mark.integration


class _FakeQueue:
    """Executes enqueued jobs synchronously, standing in for RQ workers."""

    _DISPATCH = {
        "service.orchestrator.run_shard": lambda *a: orchestrator.run_shard(*a),
        "service.orchestrator.reduce_job": lambda *a: orchestrator.reduce_job(*a),
    }

    def enqueue(self, path, *args, **kwargs):
        return self._DISPATCH[path](*args)


def _canned_extract(_pdf, page_range):
    # Windows (cap 2 over candidates [10,20,30,40]) => [0,21) [21,41) [41,50). "D2" spans the
    # first two -> exercises cross-shard first-wins dedup; the tail window yields nothing.
    start = page_range[0]
    if start == 0:
        return [{"schedule": "door", "mark": "D1"}, {"schedule": "door", "mark": "D2"}]
    if start == 21:
        return [{"schedule": "door", "mark": "D2"}, {"schedule": "finish", "mark": "R1"}]
    return []


def _failing_middle_extract(_pdf, page_range):
    start = page_range[0]
    if start == 0:
        return [{"schedule": "door", "mark": "D1"}, {"schedule": "door", "mark": "D2"}]
    if start == 21:
        raise RuntimeError("boom: malformed page in this window")
    return []


@pytest.fixture
def stubs(monkeypatch):
    store: dict[str, bytes] = {}
    monkeypatch.setattr(storage, "download_to", lambda key, dest: None)
    monkeypatch.setattr(storage, "put_bytes", lambda k, data, ct: store.__setitem__(k, data) or k)
    monkeypatch.setattr(storage, "get_bytes", lambda k: store[k])
    monkeypatch.setattr(adapter, "find_candidate_pages", lambda pdf: ([10, 20, 30, 40], 50))
    monkeypatch.setattr(adapter, "extract_shard", _canned_extract)
    monkeypatch.setattr(adapter, "assemble_report",
                        lambda pdf, merged: {"summary": {"total_items": len(merged)}, "items": merged})
    monkeypatch.setattr(orchestrator, "get_queue", lambda: _FakeQueue())
    monkeypatch.setattr(settings, "shard_memory_budget_mb", 192)  # cap = 192 // 96 = 2
    # shredding is exercised by test_shred.py; keep the orchestration test focused on flow
    monkeypatch.setattr(orchestrator, "shred_entities", lambda *a, **k: None)
    return store


def _make_job() -> str:
    job_id = str(uuid.uuid4())
    with session_scope() as s:
        s.add(TakeoffJob(id=job_id, content_sha256="x" * 64, config={}, config_hash="c",
                         status="queued", pdf_object_key=f"uploads/{job_id}/drawings.pdf",
                         entity_schema_version=adapter.ENTITY_SCHEMA_VERSION))
    return job_id


def test_fan_out_reduces_to_a_deduped_artifact(stubs):
    import json

    job_id = _make_job()

    orchestrator.plan_and_dispatch(job_id)

    with session_scope() as s:
        job = s.get(TakeoffJob, job_id)
        assert job.mode == "sharded"
        assert job.shard_count == 3          # [0,21) [21,41) [41,50)
        assert job.completed_shards == 3     # counter tripped exactly to shard_count
        assert job.status == STATUS_SUCCEEDED
        assert job.artifact_object_key is not None
        artifact_key = job.artifact_object_key

        rows = s.query(TakeoffShard).filter_by(job_id=job_id).all()
        assert len(rows) == 3
        assert all(r.status == STATUS_SUCCEEDED for r in rows)

    # the persisted artifact merged the shards with cross-window dedup (D2 kept once)
    report = json.loads(stubs[artifact_key].decode())
    assert [it["mark"] for it in report["items"]] == ["D1", "D2", "R1"]
    assert report["summary"]["total_items"] == 3


def test_dead_shard_degrades_and_flags(stubs, monkeypatch):
    import json

    monkeypatch.setattr(adapter, "extract_shard", _failing_middle_extract)
    monkeypatch.setattr(settings, "max_shard_attempts", 1)  # fail terminally on first attempt

    job_id = _make_job()
    orchestrator.plan_and_dispatch(job_id)

    with session_scope() as s:
        job = s.get(TakeoffJob, job_id)
        # degrade-and-flag: the job SUCCEEDS with a flagged partial, it does not hang or fail
        assert job.status == STATUS_SUCCEEDED
        assert job.completed_shards == 3        # the dead shard still advanced the counter
        artifact_key = job.artifact_object_key
        manifest = job.manifest
        rows = {r.shard_index: r.status for r in s.query(TakeoffShard).filter_by(job_id=job_id)}

    assert rows == {0: "succeeded", 1: "dead", 2: "succeeded"}
    assert manifest["incomplete"] is True
    assert [f["shard_index"] for f in manifest["failed_shards"]] == [1]

    # only the surviving shards' items are in the artifact (window [21,41)'s R1 is lost)
    report = json.loads(stubs[artifact_key].decode())
    assert [it["mark"] for it in report["items"]] == ["D1", "D2"]
