"""Takeoff tools — the harness's capability to run and inspect a takeoff.

Thin wrappers over TakeoffClient (which speaks only the ingestion API). Each tool is
labeled side_effects={"network"}: honest (they make HTTP calls) and it auto-fences the
service's PDF-derived text as untrusted content (drawings are untrusted input). A
purpose-built permission policy allow-lists these named tools in headless mode (T3).

The drawings PDF + config are fixed for the run (the entrypoint sets them), so submit_takeoff
takes no path from the model — the agent starts the pre-configured run, then threads the
returned job_id through the other tools.
"""
from __future__ import annotations

import asyncio
import json

from src.harness.tools.base import Tool
from src.harness.tools.decorator import async_tool

from .client import TakeoffClient

# job lifecycle states that are terminal (mirrors service/core/models.py)
_TERMINAL = {"succeeded", "failed", "dead"}


def takeoff_tools(client: TakeoffClient, pdf_path: str, config: dict | None = None,
                  *, poll_interval_s: float = 5.0, max_wait_s: float = 600.0) -> list[Tool]:
    """Build the takeoff tools bound to one client + one drawings PDF."""

    @async_tool(side_effects={"network"})
    async def submit_takeoff() -> str:
        """Start the takeoff on the configured drawings PDF.

        Runs the deterministic extraction pipeline (async, ~5 minutes). Returns the job id
        and initial status. Idempotent server-side: submitting the same drawings twice
        returns the same job. Call this once to begin, then wait_for_takeoff(job_id).
        """
        return json.dumps(await client.submit(pdf_path, config=config))

    @async_tool(side_effects={"network"})
    async def wait_for_takeoff(job_id: str) -> str:
        """Wait for a takeoff job to finish, then return its final status.

        Polls until the job is terminal (succeeded / failed / dead) or a time budget is
        exhausted. Does not block other work while waiting. If it returns a non-terminal
        status, the job is still running — report that honestly rather than assuming success.
        """
        waited = 0.0
        while True:
            st = await client.status(job_id)
            if st.get("status") in _TERMINAL:
                return json.dumps(st)
            if waited >= max_wait_s:
                return json.dumps({"status": st.get("status"), "job_id": job_id,
                                   "note": f"not terminal within {max_wait_s:.0f}s; still running"})
            await asyncio.sleep(poll_interval_s)
            waited += poll_interval_s

    @async_tool(side_effects={"network"})
    async def takeoff_summary(job_id: str) -> str:
        """Grounded takeoff summary for a finished job: the pipeline's own rollups
        (schedule counts, quantity bases, area coverage, fixture-count summary) plus
        reconciliation flags. Every number is the pipeline's — never invent or adjust one.
        """
        return json.dumps(await client.summary(job_id))

    @async_tool(side_effects={"network"})
    async def takeoff_query(job_id: str, entity: str, page: int = 1, page_size: int = 50) -> str:
        """Fetch a page of takeoff records for a finished job.

        entity: one of 'items' (schedule items), 'fixture_counts', 'room_areas'.
        Returns the records with provenance. Read-only; the numbers are the pipeline's.
        """
        fetch = {"items": client.items, "fixture_counts": client.fixture_counts,
                 "room_areas": client.room_areas}.get(entity)
        if fetch is None:
            return f"unknown entity {entity!r}; use 'items', 'fixture_counts', or 'room_areas'"
        return json.dumps(await fetch(job_id, page=page, page_size=page_size))

    return [submit_takeoff, wait_for_takeoff, takeoff_summary, takeoff_query]
