"""Typed request/response contracts (validated, not hand-rolled dicts)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class IngestionCreated(BaseModel):
    job_id: str
    status: str


class ManifestSummary(BaseModel):
    """The audit-relevant slice of the pipeline's run manifest."""

    file_id: str | None = None
    checksum: str | None = None
    page_count: int | None = None
    timing: dict | None = None
    failure_count: int = 0
    config: dict | None = None


class JobStatus(BaseModel):
    job_id: str
    status: str
    content_sha256: str
    entity_schema_version: str
    attempts: int
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    artifact_available: bool = False
    manifest: ManifestSummary | None = None
    error: dict | None = None
