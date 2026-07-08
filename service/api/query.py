"""Query API (ADR-003 QA1) — serve the grounded takeoff data.

Filtered-slice detail endpoints + a grounded summary. Every record carries its provenance;
the summary is only the pipeline's own rollups + exact counts over the rows. Query params are
plain (FastAPI infers them), validated manually so the same functions are trivially callable
in tests.
"""
from __future__ import annotations

import json

from fastapi import APIRouter
from sqlalchemy import func, select

from service import storage
from service.db import session_scope
from service.errors import ApiError
from service.models import (
    STATUS_SUCCEEDED, FixtureCountRow, RoomAreaRow, ScheduleItemRow, TakeoffJob,
)
from service.schemas import (
    FixtureCountOut, FixtureCountsPage, ItemOut, ItemsPage, Pagination, RoomAreaOut,
    RoomAreasPage, SourceOut, SummaryOut,
)

router = APIRouter(prefix="/v1/takeoff/ingestions", tags=["takeoff-query"])

MAX_PAGE_SIZE = 500


def _load_queryable(job_id: str) -> TakeoffJob:
    """Load a job and gate on it being queryable (terminal + successful)."""
    with session_scope() as s:
        job = s.get(TakeoffJob, job_id)
        if job is None:
            raise ApiError(404, "job_not_found", f"No takeoff job with id {job_id}.")
        if job.status != STATUS_SUCCEEDED:
            raise ApiError(409, "job_not_ready",
                           f"Job {job_id} status is '{job.status}'; no results to query yet.")
        s.expunge(job)
        return job


def _offset(page: int, page_size: int) -> int:
    if page < 1:
        raise ApiError(422, "invalid_page", "page must be >= 1")
    if not (1 <= page_size <= MAX_PAGE_SIZE):
        raise ApiError(422, "invalid_page_size", f"page_size must be 1..{MAX_PAGE_SIZE}")
    return (page - 1) * page_size


def _total_pages(total: int, page_size: int) -> int:
    return (total + page_size - 1) // page_size


def _incomplete(job: TakeoffJob) -> bool:
    return bool((job.manifest or {}).get("incomplete", False))


def _page_meta(job: TakeoffJob, page: int, page_size: int, total: int) -> dict:
    return {
        "pagination": Pagination(page=page, page_size=page_size, total=total,
                                 total_pages=_total_pages(total, page_size)),
        "job_id": job.id,
        "entity_schema_version": job.entity_schema_version,
        "incomplete": _incomplete(job),
    }


@router.get("/{job_id}/items", response_model=ItemsPage)
def get_items(job_id: str, schedule: str | None = None, mark: str | None = None,
              quantity_basis: str | None = None, shape: str | None = None,
              page: int = 1, page_size: int = 50) -> ItemsPage:
    job = _load_queryable(job_id)
    offset = _offset(page, page_size)
    filters = [ScheduleItemRow.job_id == job_id]
    if schedule is not None:
        filters.append(ScheduleItemRow.schedule == schedule)
    if mark is not None:
        filters.append(ScheduleItemRow.mark == mark)
    if quantity_basis is not None:
        filters.append(ScheduleItemRow.quantity_basis == quantity_basis)
    if shape is not None:
        filters.append(ScheduleItemRow.shape == shape)

    with session_scope() as s:
        total = s.scalar(select(func.count()).select_from(ScheduleItemRow).where(*filters))
        rows = s.scalars(select(ScheduleItemRow).where(*filters)
                         .order_by(ScheduleItemRow.ordinal).offset(offset).limit(page_size)).all()
        data = [ItemOut(schedule=r.schedule, shape=r.shape, mark=r.mark, quantity=r.quantity,
                        unit=r.unit, quantity_basis=r.quantity_basis, description=r.description,
                        attributes=r.attributes,
                        source=SourceOut(file_id=r.src_file_id, page_index=r.src_page_index))
                for r in rows]
    return ItemsPage(data=data, **_page_meta(job, page, page_size, total))


@router.get("/{job_id}/fixture-counts", response_model=FixtureCountsPage)
def get_fixture_counts(job_id: str, symbol_id: str | None = None, verified: bool | None = None,
                       min_confidence: float | None = None,
                       page: int = 1, page_size: int = 50) -> FixtureCountsPage:
    job = _load_queryable(job_id)
    offset = _offset(page, page_size)
    filters = [FixtureCountRow.job_id == job_id]
    if symbol_id is not None:
        filters.append(FixtureCountRow.symbol_id == symbol_id)
    if verified is not None:
        filters.append(FixtureCountRow.verified == verified)
    if min_confidence is not None:
        filters.append(FixtureCountRow.confidence >= min_confidence)

    with session_scope() as s:
        total = s.scalar(select(func.count()).select_from(FixtureCountRow).where(*filters))
        rows = s.scalars(select(FixtureCountRow).where(*filters)
                         .order_by(FixtureCountRow.ordinal).offset(offset).limit(page_size)).all()
        data = [FixtureCountOut(symbol_id=r.symbol_id, sheet_page=r.sheet_page, count=r.count,
                                confidence=r.confidence, source=r.source, verified=r.verified,
                                boxes=r.boxes)
                for r in rows]
    return FixtureCountsPage(data=data, **_page_meta(job, page, page_size, total))


@router.get("/{job_id}/room-areas", response_model=RoomAreasPage)
def get_room_areas(job_id: str, room_number: str | None = None,
                   min_confidence: float | None = None,
                   page: int = 1, page_size: int = 50) -> RoomAreasPage:
    job = _load_queryable(job_id)
    offset = _offset(page, page_size)
    filters = [RoomAreaRow.job_id == job_id]
    if room_number is not None:
        filters.append(RoomAreaRow.room_number == room_number)
    if min_confidence is not None:
        filters.append(RoomAreaRow.confidence >= min_confidence)

    with session_scope() as s:
        total = s.scalar(select(func.count()).select_from(RoomAreaRow).where(*filters))
        rows = s.scalars(select(RoomAreaRow).where(*filters)
                         .order_by(RoomAreaRow.ordinal).offset(offset).limit(page_size)).all()
        data = [RoomAreaOut(room_number=r.room_number, area_sf=r.area_sf, confidence=r.confidence,
                            basis=r.basis,
                            source=SourceOut(file_id=r.src_file_id, page_index=r.src_page_index))
                for r in rows]
    return RoomAreasPage(data=data, **_page_meta(job, page, page_size, total))


@router.get("/{job_id}/summary", response_model=SummaryOut)
def get_summary(job_id: str) -> SummaryOut:
    job = _load_queryable(job_id)
    report = json.loads(storage.get_bytes(job.artifact_object_key).decode("utf-8"))
    summary = report.get("summary", {})
    area = report.get("area_coverage", {})
    fcs = report.get("fixture_count_summary", {})

    with session_scope() as s:
        unverified = s.scalar(select(func.count()).select_from(FixtureCountRow)
                              .where(FixtureCountRow.job_id == job_id,
                                     FixtureCountRow.verified.is_(False)))

    manifest = job.manifest or {}
    flags = {
        "count_pending": summary.get("count_pending_items"),        # items pending plan count
        "unverified_fixture_counts": unverified,                    # exact count over rows
        "rooms_without_area": area.get("finish_rooms", 0) - area.get("rooms_with_area", 0),
    }
    return SummaryOut(job_id=job.id, status=job.status,
                      entity_schema_version=job.entity_schema_version,
                      incomplete=_incomplete(job), failed_shards=manifest.get("failed_shards", []),
                      summary=summary, area_coverage=area, fixture_count_summary=fcs, flags=flags)
