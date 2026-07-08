"""Takeoff ingestion endpoints (v1).

Submit is async: validate + persist + enqueue, then return a job id immediately. The
~5-min build never runs in this request path.
"""
from __future__ import annotations

import hashlib
import json
import uuid

from fastapi import APIRouter, Header, Response, UploadFile
from sqlalchemy import select

from service.config import settings
from service.db import session_scope
from service.errors import ApiError
from service.models import STATUS_QUEUED, TakeoffJob
from service.pipeline_adapter import ENTITY_SCHEMA_VERSION
from service.queue import get_queue
from service.schemas import IngestionCreated, JobStatus, ManifestSummary
from service import storage

router = APIRouter(prefix="/v1/takeoff/ingestions", tags=["takeoff"])

_PDF_MAGIC = b"%PDF-"
# Resolved config for S1 is always the golden default; recorded so the dedupe key + manifest
# already speak "config" before knobs are exposed (S3).
_DEFAULT_CONFIG: dict = {}


def _config_hash(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


@router.post("", status_code=202, response_model=IngestionCreated)
async def create_ingestion(
    drawings: UploadFile,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> IngestionCreated:
    data = await drawings.read()
    if len(data) == 0:
        raise ApiError(400, "empty_file", "The uploaded drawings file is empty.")
    if len(data) > settings.max_upload_bytes:
        raise ApiError(413, "file_too_large",
                       f"Drawings PDF exceeds the {settings.max_upload_bytes}-byte limit.")
    if not data.startswith(_PDF_MAGIC):
        raise ApiError(415, "not_a_pdf", "The uploaded drawings file is not a PDF.")

    content_sha256 = hashlib.sha256(data).hexdigest()
    config = dict(_DEFAULT_CONFIG)
    job_id = str(uuid.uuid4())
    pdf_key = f"uploads/{job_id}/drawings.pdf"

    storage.put_bytes(pdf_key, data, "application/pdf")

    with session_scope() as s:
        job = TakeoffJob(
            id=job_id,
            idempotency_key=idempotency_key,
            content_sha256=content_sha256,
            config=config,
            config_hash=_config_hash(config),
            status=STATUS_QUEUED,
            pdf_object_key=pdf_key,
            entity_schema_version=ENTITY_SCHEMA_VERSION,
        )
        s.add(job)

    # Enqueue the orchestrator: it plans the shard windows and either runs the single-build
    # fast path (small sets) or fans out into per-shard jobs (ADR-002).
    get_queue().enqueue(
        "service.orchestrator.plan_and_dispatch", job_id, job_timeout=settings.job_timeout_seconds
    )
    return IngestionCreated(job_id=job_id, status=STATUS_QUEUED)


def _load(job_id: str) -> TakeoffJob:
    with session_scope() as s:
        job = s.scalar(select(TakeoffJob).where(TakeoffJob.id == job_id))
        if job is None:
            raise ApiError(404, "job_not_found", f"No takeoff job with id {job_id}.")
        s.expunge(job)
        return job


@router.get("/{job_id}", response_model=JobStatus)
def get_ingestion(job_id: str) -> JobStatus:
    job = _load(job_id)
    manifest = None
    if job.manifest:
        m = job.manifest
        manifest = ManifestSummary(
            file_id=m.get("file_id"),
            checksum=m.get("checksum"),
            page_count=m.get("page_count"),
            timing=m.get("timing"),
            failure_count=len(m.get("failures", [])),
            config=m.get("config"),
        )
    return JobStatus(
        job_id=job.id,
        status=job.status,
        content_sha256=job.content_sha256,
        entity_schema_version=job.entity_schema_version,
        attempts=job.attempts,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        artifact_available=job.artifact_object_key is not None,
        manifest=manifest,
        error=job.error,
    )


@router.get("/{job_id}/artifact")
def get_artifact(job_id: str) -> Response:
    job = _load(job_id)
    if not job.artifact_object_key:
        raise ApiError(409, "artifact_not_ready",
                       f"Job {job_id} is '{job.status}'; no artifact yet.")
    body = storage.get_bytes(job.artifact_object_key)
    return Response(content=body, media_type="application/json")
