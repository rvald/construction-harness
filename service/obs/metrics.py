"""Prometheus metrics (ADR-004 B3).

RED for the API request surface (in-process counters/histogram) + job/shard state as gauges
derived from Postgres at scrape time. Deriving job state from the DB (the source of truth)
sidesteps the forked-worker problem — RQ forks a child per job, so counters incremented in
the child would be lost to a parent's exporter. Per-stage latency histograms (worker-side)
are therefore left to the run manifest + structured logs; a worker exporter (multiprocess
mode) can be added later if needed.
"""
from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from sqlalchemy import func, select

from service.core.db import session_scope
from service.core.models import TakeoffJob, TakeoffShard

REQUESTS = Counter("takeoff_requests_total", "HTTP requests", ["method", "path", "status"])
REQUEST_LATENCY = Histogram("takeoff_request_duration_seconds", "HTTP request latency seconds",
                            ["method", "path"])
SUBMISSIONS = Counter("takeoff_ingestions_submitted_total",
                      "Ingestion submissions", ["created"])

JOBS = Gauge("takeoff_jobs", "Jobs by status (from the DB)", ["status"])
SHARDS = Gauge("takeoff_shards", "Shards by status (from the DB)", ["status"])


def _refresh_db_gauges() -> None:
    with session_scope() as s:
        JOBS.clear()
        for status, n in s.execute(select(TakeoffJob.status, func.count()).group_by(TakeoffJob.status)):
            JOBS.labels(status=status).set(n)
        SHARDS.clear()
        for status, n in s.execute(select(TakeoffShard.status, func.count()).group_by(TakeoffShard.status)):
            SHARDS.labels(status=status).set(n)


def render() -> tuple[bytes, str]:
    """Metrics exposition. The DB refresh is best-effort — a scrape must never error out."""
    try:
        _refresh_db_gauges()
    except Exception:
        pass
    return generate_latest(), CONTENT_TYPE_LATEST
