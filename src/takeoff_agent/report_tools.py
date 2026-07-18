"""Verifier + reporter tools: cross_check (see the gaps) and finalize_report (grounded artifact).

finalize_report is the grounding-critical tool: it machine-copies the numeric spine from the
pipeline's own outputs plus the deterministic reconciliation, and lets the model contribute only
prose (narrative) and escalations — which are validated to reference real marks/schedules. The
model can never inject a number, and can never escalate a fictional item.
"""
from __future__ import annotations

import json

from src.harness.tools.base import Tool
from src.harness.tools.decorator import async_tool
from src.harness.tools.scratchpad import Scratchpad

from .client import TakeoffClient
from .reconcile import fetch_all, reconcile

# The closed vocabulary of escalation types the agent may raise. A finalize call whose
# escalation uses any other kind is rejected by the tool's input schema (enum, below).
ESCALATION_KINDS = [
    "uncounted_catalog_type",   # a schedule catalog type with no plan count
    "double_count_risk",        # a symbol counted on multiple sheets (dedup pending)
    "room_without_area",        # a finish room with no harvested area
    "unverified_counts",        # fixture counts not yet VLM-verified
    "manifest_failure",         # per-page extraction failure in the run manifest
    "incomplete_job",           # the job finished partial (dead shards)
    "other",                    # anything else worth a human's attention
]

_REPORT_KEY = "takeoff_report"


def _validate_escalations(escalations: list[dict], items: list[dict],
                          counts: list[dict], areas: list[dict]) -> list[str]:
    """Semantic check: every referenced schedule/mark must exist in the takeoff data, so the
    model cannot escalate a fictional item. (Shape + kind enum are enforced by the schema.)"""
    schedules = {it["schedule"] for it in items}
    marks = ({it.get("mark") for it in items}
             | {c.get("symbol_id") for c in counts}
             | {a.get("room_number") for a in areas})
    errors: list[str] = []
    for i, e in enumerate(escalations):
        sched, mark = e.get("schedule"), e.get("mark")
        if sched and sched not in schedules:
            errors.append(
                f"escalation[{i}]: unknown schedule {sched!r}. Valid schedules: {sorted(schedules)}. "
                f"(A fixture symbol or room id goes in 'mark', not 'schedule'.)")
        if mark and mark not in marks:
            errors.append(f"escalation[{i}]: mark {mark!r} not found in the takeoff data")
    return errors


def build_artifact(job_id: str, data: dict, status: dict, reconciliation: dict,
                   narrative: str, escalations: list[dict]) -> dict:
    """Assemble the deliverable. The numeric spine (summary rollups, reconciliation, provenance)
    is copied verbatim from the pipeline's outputs; only narrative + escalations are the model's."""
    summary = data["summary"]
    manifest = status.get("manifest") or {}
    return {
        "job_id": job_id,
        "status": summary.get("status"),
        "incomplete": bool(summary.get("incomplete", False)),
        "grounded_summary": {                          # machine-copied from /summary
            "summary": summary.get("summary", {}),
            "area_coverage": summary.get("area_coverage", {}),
            "fixture_count_summary": summary.get("fixture_count_summary", {}),
            "flags": summary.get("flags", {}),
        },
        "reconciliation": reconciliation,              # machine-computed (reconcile)
        "provenance": {                                # machine-copied from job status
            # content_sha256 is present for single AND sharded jobs (the sharded reduce manifest
            # omits checksum) — it is the sha256 of the same file bytes.
            "checksum": status.get("content_sha256") or manifest.get("checksum"),
            "page_count": manifest.get("page_count"),
            "entity_schema_version": summary.get("entity_schema_version"),
        },
        "narrative": narrative,                        # the model's prose
        "escalations": escalations,                    # the model's, validated above
    }


_ESCALATION_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ESCALATION_KINDS},
        "schedule": {"type": "string"},
        "mark": {"type": "string"},
        "note": {"type": "string"},
    },
    "required": ["kind", "note"],
}

_FINALIZE_SCHEMA = {
    "type": "object",
    "properties": {
        "job_id": {"type": "string"},
        "narrative": {"type": "string"},
        "escalations": {"type": "array", "items": _ESCALATION_ITEM_SCHEMA},
    },
    "required": ["job_id", "narrative", "escalations"],
}

_FINALIZE_DESCRIPTION = (
    "Assemble and persist the final grounded takeoff report.\n\n"
    "You provide only:\n"
    "  - narrative: a concise prose summary for a human reader.\n"
    "  - escalations: a list of {kind, note, schedule?, mark?} — the gaps that need attention.\n"
    "    kind must be one of: " + ", ".join(ESCALATION_KINDS) + ".\n"
    "    schedule (optional): a SCHEDULE NAME — e.g. door, finish, plumbing_fixture, "
    "lighting_fixture, camera, security_device.\n"
    "    mark (optional): the specific item id WITHIN that schedule — a room number, door mark, "
    "or fixture symbol. Do NOT put a symbol or room in the schedule field.\n"
    "    Example: a double-count of symbol L16A -> {kind: double_count_risk, "
    "schedule: lighting_fixture, mark: L16A, note: ...}. Any schedule/mark you name must appear "
    "in the takeoff data.\n\n"
    "    Escalate at the right GRANULARITY: one escalation per gap category or distinct "
    "verification task — NOT one per item. The reconciliation this tool computes already lists "
    "every uncounted type, roomless room, and double-count candidate in full; your escalations "
    "point at those and add context, they don't re-enumerate them. E.g. the 40 finish rooms "
    "without area -> ONE room_without_area escalation noting the count (mark optional), not 40. "
    "Aim for a handful of escalations, not dozens.\n\n"
    "All numbers (schedule rollups, reconciliation, provenance) are copied by the tool directly "
    "from the pipeline's outputs — do not restate or adjust them here. Run cross_check first so "
    "your escalations reflect the real gaps. Call this once, last, to finish the task."
)


def report_tools(client: TakeoffClient, scratchpad: Scratchpad) -> list[Tool]:
    """Build the verify/report tools bound to one client + scratchpad."""

    @async_tool(side_effects={"network"})
    async def cross_check(job_id: str) -> str:
        """Cross-check the takeoff tiers for a finished job and return the reconciliation gaps.

        Fetches the job's complete items, fixture counts, and room areas, then reports:
          - catalog types (fixtures) with no plan count vs. those that have one,
          - symbols counted on multiple sheets (candidate double-counts, dedup pending),
          - finish rooms with no harvested area,
          - the number of unverified fixture counts.
        These are GAPS to reconcile and escalate — not new measurements. Run this before
        finalizing, to decide what to escalate.
        """
        d = await fetch_all(client, job_id)
        return json.dumps(reconcile(d["summary"], d["items"], d["fixture_counts"], d["room_areas"]))

    async def _finalize(job_id: str, narrative: str, escalations: list[dict]) -> str:
        d = await fetch_all(client, job_id)
        status = await client.status(job_id)
        recon = reconcile(d["summary"], d["items"], d["fixture_counts"], d["room_areas"])
        errors = _validate_escalations(escalations, d["items"], d["fixture_counts"], d["room_areas"])
        if errors:
            return "cannot finalize — fix these escalations and retry: " + "; ".join(errors)
        artifact = build_artifact(job_id, d, status, recon, narrative, escalations)
        scratchpad.write(_REPORT_KEY, json.dumps(artifact, indent=2, ensure_ascii=False))
        cat_gaps = sum(len(v["without_counts"]) for v in recon["catalog_reconciliation"].values())
        return (f"report finalized and written to scratchpad[{_REPORT_KEY}]. "
                f"{len(escalations)} escalations recorded; reconciliation flagged {cat_gaps} "
                f"uncounted catalog types, {len(recon['area_gaps']['without_area'])} rooms without "
                f"area, {len(recon['double_count_candidates'])} double-count candidates.")

    finalize_report = Tool(
        name="finalize_report",
        description=_FINALIZE_DESCRIPTION,
        input_schema=_FINALIZE_SCHEMA,
        arun=_finalize,
        side_effects=frozenset({"network", "write"}),
    )

    return [cross_check, finalize_report]
