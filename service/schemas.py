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


class SourceOut(BaseModel):
    """Provenance: which file + page a value came from."""
    file_id: str | None = None
    page_index: int | None = None


class ItemOut(BaseModel):
    schedule: str
    shape: str
    mark: str
    quantity: float | None = None
    unit: str | None = None
    quantity_basis: str            # the honesty field (no numeric confidence on items)
    description: str = ""
    attributes: dict = {}
    source: SourceOut


class RoomAreaOut(BaseModel):
    room_number: str
    area_sf: float
    confidence: float
    basis: str
    source: SourceOut


class FixtureCountOut(BaseModel):
    symbol_id: str
    sheet_page: int                # 1-indexed page — the provenance
    count: int
    confidence: float
    source: str
    verified: bool
    boxes: list = []


class Pagination(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int


class _Page(BaseModel):
    pagination: Pagination
    job_id: str
    entity_schema_version: str
    incomplete: bool = False


class ItemsPage(_Page):
    data: list[ItemOut]


class RoomAreasPage(_Page):
    data: list[RoomAreaOut]


class FixtureCountsPage(_Page):
    data: list[FixtureCountOut]


class SummaryOut(BaseModel):
    """The grounded 'key information' bundle — pipeline rollups + exact-rollup flags only."""
    job_id: str
    status: str
    entity_schema_version: str
    incomplete: bool = False
    failed_shards: list = []
    summary: dict = {}                 # report.summary (pipeline's own rollup)
    area_coverage: dict = {}
    fixture_count_summary: dict = {}
    flags: dict = {}


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
