"""Typed request/response contracts (validated, not hand-rolled dicts)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TakeoffConfigIn(BaseModel):
    """Optional per-run knobs on submit — mirrors the pipeline's TakeoffConfig constraints.
    Omitted fields resolve to the golden defaults; the resolved (normalized) dict is what we
    store and fold into config_hash, so 'omit config' and 'pass the defaults' dedupe alike."""

    model_config = ConfigDict(extra="forbid")

    render_dpi: int = Field(default=100, ge=1)
    spread_threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    min_tags: int = Field(default=3, ge=1)
    page_range: tuple[int, int] | None = Field(default=None)

    @model_validator(mode="after")
    def _check_page_range(self) -> "TakeoffConfigIn":
        if self.page_range is not None:
            start, end = self.page_range
            if start < 0 or start >= end:
                raise ValueError(f"page_range must be 0 <= start < end, got {self.page_range!r}")
        return self


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
