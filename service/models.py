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


# job lifecycle states — see docs/takeoff_service_design.md §3
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_DEAD = "dead"


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

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=_now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
