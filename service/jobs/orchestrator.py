"""Fan-out orchestration for large sets (ADR-002 SC3).

Three queue jobs form the scatter-gather:

  plan_and_dispatch(job_id)  -> plan windows; small set => single build; else create shard
                                rows + enqueue run_shard x K.
  run_shard(job_id, i)       -> extract one window -> partial to MinIO -> mark shard done ->
                                atomically bump the completion counter -> the shard that
                                trips it to shard_count enqueues the reduce (D8).
  reduce_job(job_id)         -> load partials in shard order -> merge -> assemble -> artifact.

The heavy pdfplumber cost is confined to run_shard (one bounded window, <= the memory budget);
plan and reduce are fitz-only and light. Only pipeline_adapter touches the pipeline; the
adapter/storage/queue calls go through module attributes so tests can stub them.
"""
from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from rq import Retry
from sqlalchemy import select, update

from service.takeoff import pipeline_adapter as adapter
from service.clients import storage
from service.core.config import settings
from service.core.db import session_scope
from service.core.models import (
    MODE_SHARDED, MODE_SINGLE, STATUS_DEAD, STATUS_FAILED, STATUS_MAPPING, STATUS_PLANNING,
    STATUS_REDUCING, STATUS_RUNNING, STATUS_SUCCEEDED, TakeoffJob, TakeoffShard,
)
from service.takeoff.planner import plan_shard_windows
from service.takeoff.projection import shred_entities
from service.clients.queue import get_queue
from service.takeoff.reduce import merge_partials

log = logging.getLogger("takeoff.orchestrator")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _partial_key(job_id: str, shard_index: int) -> str:
    return f"shards/{job_id}/{shard_index}.json"


def _artifact_key(job_id: str) -> str:
    return f"artifacts/{job_id}/schedule_items.json"


def _download_pdf(pdf_key: str, tmp: str) -> Path:
    local = Path(tmp) / "drawings.pdf"
    storage.download_to(pdf_key, local)
    return local


def _get_shard(session, job_id: str, shard_index: int) -> TakeoffShard:
    return session.scalar(
        select(TakeoffShard).where(
            TakeoffShard.job_id == job_id, TakeoffShard.shard_index == shard_index
        )
    )


def plan_and_dispatch(job_id: str) -> str:
    """Entry point the API enqueues. Decides single vs sharded and fans out."""
    with session_scope() as s:
        job = s.get(TakeoffJob, job_id)
        job.status = STATUS_PLANNING
        job.started_at = _now()
        pdf_key = job.pdf_object_key
        config = job.config or {}

    with tempfile.TemporaryDirectory(prefix=f"plan-{job_id}-") as tmp:
        local = _download_pdf(pdf_key, tmp)
        candidates, total = adapter.find_candidate_pages(local)
    pr = config.get("page_range")   # optional submit-time window bounds the whole job
    page_start, page_end = (pr[0], pr[1]) if pr else (0, None)
    windows = plan_shard_windows(candidates, total, settings.max_candidates_per_shard,
                                 page_start=page_start, page_end=page_end)
    log.info("takeoff.plan", extra={"job_id": job_id, "pages": total,
                                    "candidates": len(candidates), "shards": len(windows)})

    # Single window == the serial run: hand off to the S1 builder (no fan-out overhead).
    if len(windows) <= 1:
        with session_scope() as s:
            s.get(TakeoffJob, job_id).mode = MODE_SINGLE
        from service.jobs.worker import process_job
        return process_job(job_id)

    with session_scope() as s:
        job = s.get(TakeoffJob, job_id)
        job.mode = MODE_SHARDED
        job.shard_count = len(windows)
        job.status = STATUS_MAPPING
        for w in windows:
            s.add(TakeoffShard(job_id=job_id, shard_index=w.index,
                               page_start=w.start, page_end=w.end,
                               candidate_count=w.candidate_count))

    q = get_queue()
    retries = max(settings.max_shard_attempts - 1, 0)
    enqueue_kwargs = {"job_timeout": settings.job_timeout_seconds}
    if retries > 0:  # RQ's Retry requires max >= 1; omit it when no retries are configured
        enqueue_kwargs["retry"] = Retry(max=retries, interval=settings.shard_retry_backoff_seconds)
    for w in windows:
        q.enqueue("service.jobs.orchestrator.run_shard", job_id, w.index, **enqueue_kwargs)
    return STATUS_MAPPING


def run_shard(job_id: str, shard_index: int) -> str:
    """The map: extract one window, persist its partial, checkpoint, trip the counter."""
    with session_scope() as s:
        shard = _get_shard(s, job_id, shard_index)
        shard.status = STATUS_RUNNING
        shard.attempts += 1
        shard.started_at = _now()
        attempt_no = shard.attempts
        page_range = (shard.page_start, shard.page_end)
        pdf_key = s.get(TakeoffJob, job_id).pdf_object_key

    try:
        with tempfile.TemporaryDirectory(prefix=f"shard-{job_id}-{shard_index}-") as tmp:
            local = _download_pdf(pdf_key, tmp)
            partial = adapter.extract_shard(local, page_range)
        key = _partial_key(job_id, shard_index)
        storage.put_bytes(key, json.dumps(partial, ensure_ascii=False).encode("utf-8"),
                          "application/json")
    except Exception as exc:
        terminal = attempt_no >= settings.max_shard_attempts
        with session_scope() as s:
            shard = _get_shard(s, job_id, shard_index)
            shard.status = STATUS_DEAD if terminal else STATUS_FAILED
            shard.finished_at = _now() if terminal else None
            shard.error = {"type": type(exc).__name__, "message": str(exc)[:2000]}
        log.exception("takeoff.shard.failed",
                      extra={"job_id": job_id, "shard": shard_index,
                             "attempt": attempt_no, "terminal": terminal})
        if not terminal:
            raise  # let RQ retry with backoff
        # Terminal: don't hang the job — count this shard as finished and let the reduce run
        # on the survivors (degrade-and-flag).
        _finalize_shard(job_id)
        return STATUS_DEAD

    with session_scope() as s:
        shard = _get_shard(s, job_id, shard_index)
        shard.status = STATUS_SUCCEEDED
        shard.finished_at = _now()
        shard.partial_object_key = key

    _finalize_shard(job_id)
    return STATUS_SUCCEEDED


def _finalize_shard(job_id: str) -> None:
    """Atomic terminal counter (D8): one UPDATE ... RETURNING per finished shard (succeeded
    OR dead). The row that reads completed_shards == shard_count is the single one that
    enqueues the reduce — so a dead shard advances the counter too and the job never hangs."""
    with session_scope() as s:
        finished, total = s.execute(
            update(TakeoffJob)
            .where(TakeoffJob.id == job_id)
            .values(completed_shards=TakeoffJob.completed_shards + 1)
            .returning(TakeoffJob.completed_shards, TakeoffJob.shard_count)
        ).one()
    if finished == total:
        get_queue().enqueue("service.jobs.orchestrator.reduce_job", job_id,
                            job_timeout=settings.job_timeout_seconds)


def reduce_job(job_id: str) -> str:
    """The reduce: merge partials in shard order, assemble, persist the artifact."""
    with session_scope() as s:
        job = s.get(TakeoffJob, job_id)
        job.status = STATUS_REDUCING
        pdf_key = job.pdf_object_key
        config = job.config or {}
        shard_count = job.shard_count
        shards = s.scalars(
            select(TakeoffShard).where(TakeoffShard.job_id == job_id)
            .order_by(TakeoffShard.shard_index)
        ).all()
        # Only succeeded shards have a partial; dead shards are flagged, not merged.
        partial_keys = [sh.partial_object_key for sh in shards
                        if sh.status == STATUS_SUCCEEDED and sh.partial_object_key]
        failed_shards = [{"shard_index": sh.shard_index,
                          "page_range": [sh.page_start, sh.page_end],
                          "error": sh.error}
                         for sh in shards if sh.status == STATUS_DEAD]

    partials = [json.loads(storage.get_bytes(k).decode("utf-8")) for k in partial_keys]
    merged = merge_partials(partials)

    with tempfile.TemporaryDirectory(prefix=f"reduce-{job_id}-") as tmp:
        local = _download_pdf(pdf_key, tmp)
        report = adapter.assemble_report(local, merged, config=config)

    art_key = _artifact_key(job_id)
    storage.put_bytes(art_key, json.dumps(report, ensure_ascii=False).encode("utf-8"),
                      "application/json")
    manifest = {"mode": MODE_SHARDED, "shard_count": shard_count,
                "shards_merged": len(partial_keys),
                "total_items": report.get("summary", {}).get("total_items"),
                "incomplete": bool(failed_shards),
                "failed_shards": failed_shards}

    with session_scope() as s:
        job = s.get(TakeoffJob, job_id)
        # Degrade-and-flag: the job SUCCEEDS with a partial, incomplete-flagged artifact
        # rather than failing outright when some shards died.
        job.status = STATUS_SUCCEEDED
        job.finished_at = _now()
        job.artifact_object_key = art_key
        job.manifest = manifest
        job.entity_schema_version = adapter.ENTITY_SCHEMA_VERSION
        shred_entities(s, job_id, report)   # project the artifact into queryable rows (ADR-003)
    log.info("takeoff.reduce.done",
             extra={"job_id": job_id, "shards_merged": len(partial_keys),
                    "incomplete": bool(failed_shards)})
    return STATUS_SUCCEEDED
