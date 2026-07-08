"""Relational models for job metadata + run manifests.

S1 is just ``takeoff_jobs``. Shredded entity tables (schedule_items / fixture_counts /
room_areas) arrive in S2.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from service.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# job lifecycle states — see docs/takeoff_service_design.md §3 and
# docs/takeoff_scaling_design.md §5 (planning/mapping/reducing added for sharded jobs)
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_PLANNING = "planning"
STATUS_MAPPING = "mapping"
STATUS_REDUCING = "reducing"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_DEAD = "dead"

# how a job is executed
MODE_SINGLE = "single"     # one process over the whole doc (S1 fast path / small sets)
MODE_SHARDED = "sharded"   # fan-out over page-range shards (ADR-002)


class TakeoffJob(Base):
    __tablename__ = "takeoff_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    # dedupe keys (enforced in S3; recorded now)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), index=True)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    config_hash: Mapped[str] = mapped_column(String(64))

    status: Mapped[str] = mapped_column(String(16), default=STATUS_QUEUED, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[dict | None] = mapped_column(JSONB)

    # object storage keys + the pipeline's run manifest
    pdf_object_key: Mapped[str] = mapped_column(String(512))
    artifact_object_key: Mapped[str | None] = mapped_column(String(512))
    manifest: Mapped[dict | None] = mapped_column(JSONB)

    entity_schema_version: Mapped[str] = mapped_column(String(16))

    # execution mode + fan-in bookkeeping (ADR-002). completed_shards is the completion
    # counter; the compare-and-set transition to shard_count triggers the reduce.
    mode: Mapped[str] = mapped_column(String(16), default=MODE_SINGLE)
    shard_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_shards: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=_now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TakeoffShard(Base):
    """One page-range unit of work for a sharded job (ADR-002). The checkpoint record:
    Postgres holds coordination/status, MinIO holds the partial payload (partial_object_key).
    """

    __tablename__ = "takeoff_shards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    shard_index: Mapped[int] = mapped_column(Integer)

    page_start: Mapped[int] = mapped_column(Integer)   # 0-based, inclusive
    page_end: Mapped[int] = mapped_column(Integer)     # 0-based, exclusive
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)

    status: Mapped[str] = mapped_column(String(16), default=STATUS_QUEUED, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    partial_object_key: Mapped[str | None] = mapped_column(String(512))
    error: Mapped[dict | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=_now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
