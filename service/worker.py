"""RQ worker task: run one takeoff build to completion.

Lifecycle: mark running -> download the PDF to scratch -> invoke the pipeline via the
adapter -> store the artifact blob + manifest -> mark succeeded. Any failure marks the job
``failed`` with a sanitized error and re-raises so RQ records the failure (dead-lettering
and retries are hardened in S4). Logs are structured and keyed by ``job_id`` — never the
document's contents.
"""
from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from service.db import session_scope
from service.models import STATUS_FAILED, STATUS_RUNNING, STATUS_SUCCEEDED, TakeoffJob
from service.pipeline_adapter import ENTITY_SCHEMA_VERSION, run_takeoff
from service.projection import shred_entities
from service import storage

log = logging.getLogger("takeoff.worker")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def process_job(job_id: str) -> str:
    """Entry point enqueued on the RQ queue. Returns the terminal status."""
    with session_scope() as s:
        job = s.get(TakeoffJob, job_id)
        if job is None:
            log.error("job not found", extra={"job_id": job_id})
            raise RuntimeError(f"job {job_id} not found")
        job.status = STATUS_RUNNING
        job.attempts += 1
        job.started_at = _now()
        pdf_key = job.pdf_object_key
        config = job.config
    log.info("takeoff.start", extra={"job_id": job_id, "pdf_key": pdf_key})

    try:
        with tempfile.TemporaryDirectory(prefix=f"takeoff-{job_id}-") as tmp:
            local_pdf = Path(tmp) / "drawings.pdf"
            storage.download_to(pdf_key, local_pdf)

            report, manifest = run_takeoff(local_pdf, config=config)

            artifact_key = f"artifacts/{job_id}/schedule_items.json"
            storage.put_bytes(
                artifact_key,
                json.dumps(report, ensure_ascii=False).encode("utf-8"),
                "application/json",
            )
    except Exception as exc:  # degrade: record + surface, never swallow
        with session_scope() as s:
            job = s.get(TakeoffJob, job_id)
            job.status = STATUS_FAILED
            job.finished_at = _now()
            job.error = {"type": type(exc).__name__, "message": str(exc)[:2000]}
        log.exception("takeoff.failed", extra={"job_id": job_id})
        raise

    with session_scope() as s:
        job = s.get(TakeoffJob, job_id)
        job.status = STATUS_SUCCEEDED
        job.finished_at = _now()
        job.artifact_object_key = artifact_key
        job.manifest = manifest
        job.entity_schema_version = ENTITY_SCHEMA_VERSION
        shred_entities(s, job_id, report)   # project the artifact into queryable rows (ADR-003)
    log.info(
        "takeoff.done",
        extra={"job_id": job_id, "timing": manifest.get("timing"),
               "failures": len(manifest.get("failures", []))},
    )
    return STATUS_SUCCEEDED
