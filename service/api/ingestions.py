"""Takeoff ingestion endpoints (v1).

Submit is async: validate + persist + enqueue, then return a job id immediately. The
~5-min build never runs in this request path.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid

from fastapi import APIRouter, Form, Header, Request, Response, UploadFile
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from service.config import settings
from service.db import session_scope
from service.errors import ApiError
from service.models import STATUS_DEAD, STATUS_FAILED, STATUS_QUEUED, TakeoffJob
from service.pipeline_adapter import ENTITY_SCHEMA_VERSION
from service.queue import get_queue
from service.schemas import IngestionCreated, JobStatus, ManifestSummary, TakeoffConfigIn
from service import metrics, storage

router = APIRouter(prefix="/v1/takeoff/ingestions", tags=["takeoff"])
log = logging.getLogger("takeoff.api")

_PDF_MAGIC = b"%PDF-"
_CHUNK = 1 << 20   # 1 MiB


def _hash_and_validate(fileobj, max_bytes: int) -> tuple[str, int]:
    """Stream the (already spooled) upload once: sha256 + size + PDF magic, in bounded memory.
    Leaves fileobj rewound to 0 for the subsequent streamed upload. Sync — run in a threadpool."""
    sha = hashlib.sha256()
    total = 0
    head = b""
    fileobj.seek(0)
    while True:
        chunk = fileobj.read(_CHUNK)
        if not chunk:
            break
        if not head:
            head = chunk[:5]
        total += len(chunk)
        if total > max_bytes:
            raise ApiError(413, "file_too_large",
                           f"Drawings PDF exceeds the {max_bytes}-byte limit.")
        sha.update(chunk)
    fileobj.seek(0)
    if total == 0:
        raise ApiError(400, "empty_file", "The uploaded drawings file is empty.")
    if not head.startswith(_PDF_MAGIC):
        raise ApiError(415, "not_a_pdf", "The uploaded drawings file is not a PDF.")
    return sha.hexdigest(), total


def _config_hash(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def _resolve_config(config_json: str | None) -> dict:
    """Parse + validate the optional config form field into a NORMALIZED dict (defaults
    filled), so 'omit config' and 'pass the defaults' produce the same stored config +
    config_hash (dedup-stable)."""
    if config_json is None:
        return TakeoffConfigIn().model_dump()
    try:
        parsed = json.loads(config_json)
    except json.JSONDecodeError:
        raise ApiError(422, "invalid_config", "config must be valid JSON.")
    try:
        return TakeoffConfigIn(**parsed).model_dump()
    except (ValidationError, TypeError) as e:
        raise ApiError(422, "invalid_config", f"config failed validation: {e}")


def _find_existing(s, idempotency_key: str | None, sha: str, cfg_hash: str) -> TakeoffJob | None:
    """Return a job this submit should dedupe onto, or None. Raises 409 if an Idempotency-Key
    is reused with a different request."""
    if idempotency_key:
        j = s.scalar(select(TakeoffJob).where(TakeoffJob.idempotency_key == idempotency_key))
        if j is not None:
            if j.content_sha256 == sha and j.config_hash == cfg_hash:
                return j
            raise ApiError(409, "idempotency_key_conflict",
                           "Idempotency-Key was reused with different content or config.")
    # work dedup: an ACTIVE (non-failed/dead) job with identical content + config
    return s.scalar(
        select(TakeoffJob).where(
            TakeoffJob.content_sha256 == sha, TakeoffJob.config_hash == cfg_hash,
            TakeoffJob.status.notin_([STATUS_FAILED, STATUS_DEAD]))
        .order_by(TakeoffJob.created_at.desc()))


def _submit(content_sha256: str, fileobj, resolved_config: dict,
            idempotency_key: str | None) -> tuple[str, str, bool]:
    """Dedupe-or-create. Returns (job_id, status, created). Streams the upload + enqueues only
    for a genuinely new job; the partial unique indexes make the create race-safe. Sync (does
    blocking DB + S3 I/O) — run in a threadpool."""
    cfg_hash = _config_hash(resolved_config)

    with session_scope() as s:
        existing = _find_existing(s, idempotency_key, content_sha256, cfg_hash)
        if existing is not None:
            return existing.id, existing.status, False

    job_id = str(uuid.uuid4())
    pdf_key = f"uploads/{job_id}/drawings.pdf"
    try:
        with session_scope() as s:
            s.add(TakeoffJob(
                id=job_id, idempotency_key=idempotency_key, content_sha256=content_sha256,
                config=resolved_config, config_hash=cfg_hash, status=STATUS_QUEUED,
                pdf_object_key=pdf_key, entity_schema_version=ENTITY_SCHEMA_VERSION))
    except IntegrityError:
        # concurrent identical submit won the unique index — dedupe onto it
        with session_scope() as s:
            existing = _find_existing(s, idempotency_key, content_sha256, cfg_hash)
            if existing is None:
                raise
            return existing.id, existing.status, False

    # only a new job streams its PDF + enqueues (worker never runs before the object exists)
    fileobj.seek(0)
    storage.upload_fileobj(pdf_key, fileobj, "application/pdf")
    get_queue().enqueue("service.orchestrator.plan_and_dispatch", job_id,
                        job_timeout=settings.job_timeout_seconds)
    return job_id, STATUS_QUEUED, True


@router.post("", status_code=202, response_model=IngestionCreated)
async def create_ingestion(
    drawings: UploadFile,
    request: Request,
    response: Response,
    config: str | None = Form(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> IngestionCreated:
    # Stream the (spooled) upload — hash + validate + upload without loading it into memory.
    # Blocking file/S3 I/O runs in a threadpool so the event loop stays free.
    content_sha256, _size = await run_in_threadpool(
        _hash_and_validate, drawings.file, settings.max_upload_bytes)
    resolved_config = _resolve_config(config)
    job_id, status, created = await run_in_threadpool(
        _submit, content_sha256, drawings.file, resolved_config, idempotency_key)
    response.status_code = 202 if created else 200   # 200 signals a dedupe hit, not a new job
    metrics.SUBMISSIONS.labels(created=str(created)).inc()
    # correlate the client request to the async job; every downstream log carries job_id
    log.info("takeoff.submit", extra={"job_id": job_id,
                                      "request_id": getattr(request.state, "request_id", "-"),
                                      "created": created})
    return IngestionCreated(job_id=job_id, status=status)


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
    m = job.manifest or {}
    manifest = None
    if m:
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
        mode=job.mode,
        shard_count=job.shard_count,
        incomplete=bool(m.get("incomplete", False)),
        failed_shards=m.get("failed_shards", []),
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
