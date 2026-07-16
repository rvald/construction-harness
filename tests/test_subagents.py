"""Parallel sub-agents & shared-state safety.

Drives the real spawner/parallel machinery end-to-end with a fake Provider,
proving the four properties the wiring is supposed to guarantee:

  * siblings actually run concurrently (overlap, not serial),
  * a shared write-gate keeps concurrent mutating calls from interleaving,
  * the parent's PermissionManager is inherited by sub-agents (fail-closed),
  * the delegation tools are stripped from a sub-agent's catalog (no recursion),
  * one sibling's failure doesn't cancel the rest of the batch.

Like the other loop tests, these are plain sync tests driven with asyncio.run
(the repo has no pytest-asyncio).
"""
from __future__ import annotations

import asyncio

from src.harness.permissions.manager import PermissionManager
from src.harness.permissions.model import PermissionOutcome
from src.harness.providers.events import Completed, TextDelta, ToolCallDelta, ToolCallStart
from src.harness.messages import ToolResult
from src.harness.subagents.assembly import subagent_tools
from src.harness.subagents.parallel import ParallelSpawner
from src.harness.subagents.spawner import SubagentSpawner
from src.harness.subagents.subagent import SubagentSpec
from src.harness.tools.decorator import async_tool
from src.harness.tools.selector import ToolCatalog


class ToolThenAnswerProvider:
    """Stateless fake model: if the sub-agent hasn't run a tool yet, call the
    one tool it's offered; once a tool_result is in the transcript, answer.

    Decisions come only from the transcript (not instance counters), so it's
    correct when many sub-agents share one provider concurrently.
    """

    name = "tool-then-answer"

    def __init__(self, tool_name: str, args: dict):
        self._tool_name = tool_name
        self._args = args

    async def astream(self, transcript, tools):
        if not tools:  # grace turn
            yield TextDelta(text="done")
            yield Completed(input_tokens=1, output_tokens=1)
            return
        already_ran = any(
            isinstance(b, ToolResult)
            for m in transcript.messages for b in m.blocks
        )
        if already_ran:
            yield TextDelta(text="done")
            yield Completed(input_tokens=1, output_tokens=1)
            return
        import json
        yield ToolCallStart(id="c1", name=self._tool_name)
        yield ToolCallDelta(id="c1", args_fragment=json.dumps(self._args))
        yield Completed(input_tokens=1, output_tokens=1)

    async def acomplete(self, transcript, tools):
        raise NotImplementedError


def test_siblings_run_concurrently():
    # Three sub-agents each call a read tool that parks in an await while
    # recording how many peers are inside it at once. Read tools don't take the
    # write-gate, so all three should overlap → peak concurrency 3. This is a
    # deterministic overlap check, not a flaky wall-clock one (tiktoken/BM25 per
    # sub-agent is synchronous and inflates elapsed time without meaning serial).
    state = {"active": 0, "peak": 0}

    @async_tool(side_effects={"read"})
    async def tracked_read() -> str:
        """Record peak concurrency across a yield point."""
        state["active"] += 1
        state["peak"] = max(state["peak"], state["active"])
        await asyncio.sleep(0.05)   # yield so peers can enter
        state["active"] -= 1
        return "ok"

    catalog = ToolCatalog(tools=[tracked_read])
    provider = ToolThenAnswerProvider("tracked_read", {})
    spawner = SubagentSpawner(provider=provider, catalog=catalog)
    parallel = ParallelSpawner(inner=spawner, max_parallel=3)

    specs = [
        SubagentSpec(objective=f"o{i}", output_format="text",
                     tools_allowed=["tracked_read"], max_iterations=3)
        for i in range(3)
    ]

    results = asyncio.run(parallel.spawn_all(specs, justification="parallel"))

    assert all(r.error is None for r in results), [r.error for r in results]
    assert state["peak"] == 3, f"reads did not overlap: peak concurrency {state['peak']}"


def test_write_gate_serializes_concurrent_mutations():
    # Two sub-agents run a mutating tool that reads a shared counter, awaits
    # (yielding the event loop mid-write), then writes counter+1. Without the
    # gate the read-modify-write interleaves and both land on 1; with it they
    # serialize to 1 then 2. The gate is created per-batch by ParallelSpawner.
    state = {"counter": 0}

    @async_tool(side_effects={"write"})
    async def bump() -> str:
        """Non-atomic increment with an await between read and write."""
        current = state["counter"]
        await asyncio.sleep(0.01)          # let a sibling run if it can
        state["counter"] = current + 1
        return f"counter={current + 1}"

    catalog = ToolCatalog(tools=[bump])
    provider = ToolThenAnswerProvider("bump", {})
    spawner = SubagentSpawner(provider=provider, catalog=catalog)
    parallel = ParallelSpawner(inner=spawner, max_parallel=4)

    specs = [
        SubagentSpec(objective=f"o{i}", output_format="text",
                     tools_allowed=["bump"], max_iterations=3)
        for i in range(2)
    ]

    results = asyncio.run(parallel.spawn_all(specs, justification="parallel"))
    assert all(r.error is None for r in results), [r.error for r in results]
    assert state["counter"] == 2, (
        f"write-gate failed to serialize: counter={state['counter']} (want 2)"
    )


def test_subagent_inherits_deny_permission():
    # A parent whose PermissionManager denies everything must gate sub-agent
    # tool calls too: the mutating tool never runs, so the counter stays 0.
    ran = {"n": 0}

    @async_tool(side_effects={"write"})
    async def do_write() -> str:
        """A write that should be denied before it runs."""
        ran["n"] += 1
        return "wrote"

    def deny_all(req):
        return PermissionOutcome("deny", "policy: deny all")

    catalog = ToolCatalog(tools=[do_write])
    provider = ToolThenAnswerProvider("do_write", {})
    spawner = SubagentSpawner(
        provider=provider, catalog=catalog,
        permission_manager=PermissionManager(policy=deny_all, human_prompt=None),
    )

    spec = SubagentSpec(objective="write something", output_format="text",
                        tools_allowed=["do_write"], max_iterations=3)
    result = asyncio.run(spawner.spawn(spec, justification="test"))

    assert ran["n"] == 0, "denied tool must not execute inside a sub-agent"
    assert result.error is None  # the run completes; the tool call is just denied


def test_delegation_tools_stripped_from_subagent_catalog():
    # A sub-agent that names a delegation tool in tools_allowed must not receive
    # it — recursion is blocked structurally. The provider records the tool
    # names it was offered.
    offered: list[str] = []

    @async_tool(side_effects={"read"})
    async def peek() -> str:
        """A harmless read so the sub-agent has at least one real tool."""
        return "peeked"

    class RecordingProvider:
        name = "recording"

        async def astream(self, transcript, tools):
            offered.append(tuple(t["name"] for t in tools))
            yield TextDelta(text="done")
            yield Completed(input_tokens=1, output_tokens=1)

        async def acomplete(self, transcript, tools):
            raise NotImplementedError

    provider = RecordingProvider()
    # Parent catalog holds a real tool plus the delegation tools (via factory).
    base = ToolCatalog(tools=[peek])
    deleg = subagent_tools(provider=provider, catalog=base)
    parent_catalog = ToolCatalog(tools=[peek, *deleg])

    spawner = SubagentSpawner(provider=provider, catalog=parent_catalog)
    spec = SubagentSpec(
        objective="try to recurse", output_format="text",
        tools_allowed=["peek", "spawn_subagent", "spawn_parallel_subagents"],
        max_iterations=2,
    )
    asyncio.run(spawner.spawn(spec, justification="test"))

    assert offered, "sub-agent never called the provider"
    names = offered[0]
    assert "peek" in names
    assert "spawn_subagent" not in names
    assert "spawn_parallel_subagents" not in names


def test_one_sibling_failure_does_not_cancel_the_batch():
    # A sub-agent whose only allowed tool doesn't exist in the catalog fails
    # (spawner returns an error result); its siblings still complete.
    @async_tool(side_effects={"read"})
    async def ok_tool() -> str:
        """A tool that succeeds."""
        return "ok"

    catalog = ToolCatalog(tools=[ok_tool])
    provider = ToolThenAnswerProvider("ok_tool", {})
    spawner = SubagentSpawner(provider=provider, catalog=catalog)
    parallel = ParallelSpawner(inner=spawner, max_parallel=4)

    specs = [
        SubagentSpec(objective="good", output_format="text",
                     tools_allowed=["ok_tool"], max_iterations=3),
        SubagentSpec(objective="bad", output_format="text",
                     tools_allowed=["nonexistent_tool"], max_iterations=3),
        SubagentSpec(objective="good2", output_format="text",
                     tools_allowed=["ok_tool"], max_iterations=3),
    ]
    results = asyncio.run(parallel.spawn_all(specs, justification="parallel"))

    assert len(results) == 3
    assert results[0].error is None
    assert results[1].error is not None      # the bad one failed, isolated
    assert results[2].error is None          # sibling after it still ran
