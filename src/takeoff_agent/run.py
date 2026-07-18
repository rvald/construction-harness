"""Entrypoint: run the takeoff agent over one drawings PDF (T3 complete).

A pre-seeded plan makes the flow mandatory: submit -> wait -> summary -> cross_check ->
finalize_report, gated by the harness completion gate (the model can't declare done until every
postcondition is verified). A fail-closed allow-list permission policy lets exactly the agent's
own tools run and denies anything else. finalize_report writes the grounded artifact to a per-run
scratchpad; this entrypoint saves it to output/agent_reports/<job_id>.json.

Usage:
  python -m src.takeoff_agent.run <drawings.pdf> [start end]

  <drawings.pdf>   path to the drawings PDF
  [start end]      optional 0-based page range for fast iteration (e.g. 40 60)

Requires the takeoff service reachable at TAKEOFF_API_BASE_URL (default http://localhost:8089).
Provider via PROVIDER env (anthropic default; needs the matching API key).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from src.harness.agent import arun
from src.harness.messages import ToolCall, ToolResult
from src.harness.permissions.manager import PermissionManager
from src.harness.plans.tools import PlanHolder, plan_tools
from src.harness.providers.anthropic import AnthropicProvider
from src.harness.providers.openai import OpenAIProvider
from src.harness.providers.events import TextDelta
from src.harness.tools.scratchpad import Scratchpad
from src.harness.tools.selector import ToolCatalog

from .client import TakeoffClient
from .plan import takeoff_plan
from .policy import takeoff_policy
from .report_tools import report_tools
from .tools import takeoff_tools

_SYSTEM = """You are a construction takeoff orchestrator. A drawings PDF is already configured \
for this run; you do not choose files.

Follow the active plan (call plan_show to see it). The task has FOUR tool steps and is NOT \
complete until you finalize:
  1. submit_takeoff, then wait_for_takeoff(job_id) until the job finishes.
  2. takeoff_summary(job_id) to read the grounded results.
  3. cross_check(job_id) to reconcile the tiers and see the gaps.
  4. finalize_report(job_id, narrative, escalations) — REQUIRED and always last. Provide only \
prose + escalations; the tool copies every number from the pipeline itself.

Bookkeeping (the run cannot end without it):
  - After finalize_report succeeds, call postcondition_verify for EACH of the plan's \
postconditions (call plan_show to see them), citing concrete evidence.
  - Do NOT end your turn until finalize_report has run and every postcondition is verified. \
Never end with an empty message.

Honesty:
  - Every quantity, count, area, and confidence comes from the tools. NEVER invent, estimate, or \
adjust a number. Report exactly what the tools contain; escalate anything missing, unverified, \
or partial. If a job did not fully succeed, say so plainly.
"""

_PROVIDERS = {"anthropic": AnthropicProvider, "openai": OpenAIProvider}
_KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}


def _print_hooks():
    def on_event(event):
        if isinstance(event, TextDelta):
            print(event.text, end="", flush=True)

    def on_tool_call(call: ToolCall) -> None:
        print(f"\n  ⚙ {call.name}({json.dumps(call.args)})", flush=True)

    def on_tool_result(result: ToolResult) -> None:
        marker = "✗" if result.is_error else "→"
        preview = result.content.strip().replace("\n", " ")
        print(f"\n  {marker} {preview[:157] + '...' if len(preview) > 160 else preview}\n", flush=True)

    return on_event, on_tool_call, on_tool_result


def _save_report(scratchpad: Scratchpad) -> None:
    """Persist the grounded artifact finalize wrote (if any) to a durable, job-keyed file."""
    try:
        report = json.loads(scratchpad.read("takeoff_report"))
    except KeyError:
        print("\n[no finalized report was produced this run]")
        return
    out = Path("output/agent_reports") / f"{report['job_id']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\n[grounded report → {out}  ({len(report.get('escalations', []))} escalations)]")


async def main(pdf_path: str, config: dict | None) -> None:
    provider_name = os.environ.get("PROVIDER", "anthropic")
    key = _KEY_ENV.get(provider_name)
    if key and not os.environ.get(key):
        sys.exit(f"error: PROVIDER={provider_name} requires {key} to be set.")
    provider = _PROVIDERS[provider_name]()
    on_event, on_tool_call, on_tool_result = _print_hooks()
    scratchpad = Scratchpad(root=tempfile.mkdtemp(prefix="takeoff-agent-"))

    # Pre-seed the fixed plan; expose plan_show + postcondition_verify only — the model can see
    # and verify the postconditions but cannot author or weaken them (no plan_create), and there
    # are no steps to update (the postconditions are the gate).
    holder = PlanHolder(plan=takeoff_plan())
    plan_progress_tools = [t for t in plan_tools(holder)
                           if t.name in ("plan_show", "postcondition_verify")]

    async with TakeoffClient() as client:
        tools = (takeoff_tools(client, pdf_path, config)
                 + report_tools(client, scratchpad)
                 + plan_progress_tools)
        # Fail-closed allow-list: exactly the agent's own tools may run; anything else is denied.
        # human_prompt=None makes it headless-safe (no interactive fallback).
        permissions = PermissionManager(
            policy=takeoff_policy({t.name for t in tools}), human_prompt=None)
        result = await arun(
            provider,
            ToolCatalog(tools=tools),
            "Run a takeoff on the configured drawings PDF, reconcile the tiers, and finalize a grounded report.",
            system=_SYSTEM,
            on_event=on_event, on_tool_call=on_tool_call, on_tool_result=on_tool_result,
            tools_per_turn=len(tools),        # send the whole (small) catalog every turn — stable prefix
            permission_manager=permissions,   # fail-closed allow-list (T3d)
            plan_holder=holder,               # completion gate enforces the pre-seeded postconditions
            max_iterations=30,                # plan progress + verify calls add turns; give headroom
            deadline_s=900,                   # covers the ~5-min build + the reasoning turns
        )
    _save_report(scratchpad)
    print(f"\n[done — stop_reason={result.stop_reason}, "
          f"iterations={result.iterations_used}, tokens={result.tokens_used}]")


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) not in (1, 3):
        sys.exit("usage: python -m src.takeoff_agent.run <drawings.pdf> [start end]")
    cfg = {"page_range": [int(args[1]), int(args[2])]} if len(args) == 3 else None
    asyncio.run(main(args[0], cfg))
