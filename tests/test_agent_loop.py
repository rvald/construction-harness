"""Agent loop & termination behavior.

Covers the three termination guarantees the loop must uphold:
  * cross-turn loop detection actually fires (state persists across the fresh
    registry each turn builds),
  * the iteration cap comes from the `max_iterations` argument, not a constant,
  * hitting a bound returns partial state with a `stop_reason` — it never raises.

The loop is async; the repo has no pytest-asyncio, so we drive it with
`asyncio.run()` inside plain sync tests, matching the other async tests here.
"""
from __future__ import annotations

import asyncio

from src.harness.agent import _EXHAUSTED_MARKER, AgentRunResult, arun
from src.harness.providers.events import (
    Completed,
    TextDelta,
    ToolCallDelta,
    ToolCallStart,
)
from src.harness.tools.decorator import tool
from src.harness.tools.registry import MAX_REPEAT_CALLS
from src.harness.tools.selector import ToolCatalog


def _echo_tool(counter: dict):
    """A tool whose body increments `counter['n']` each time it actually runs,
    so a test can distinguish executed calls from guard-short-circuited ones."""

    @tool(side_effects={"read"})
    def echo(x: str) -> str:
        """Echo x back to the caller."""
        counter["n"] += 1
        return f"echo:{x}"

    return echo


class LoopingProvider:
    """A model that never stops: requests echo(x='same') identically forever."""

    name = "looping"

    async def astream(self, transcript, tools):
        if not tools:  # grace turn: no tools offered, so a real model answers
            yield TextDelta(text="forced wrap-up")
            yield Completed(input_tokens=3, output_tokens=2)
            return
        yield ToolCallStart(id="call", name="echo")
        yield ToolCallDelta(id="call", args_fragment='{"x": "same"}')
        yield Completed(input_tokens=5, output_tokens=2)

    async def acomplete(self, transcript, tools):  # not used by the loop
        raise NotImplementedError


class DistinctToolProvider:
    """Requests echo with a fresh argument each turn, so the loop guard never
    fires — isolates the iteration-cap behavior from loop detection."""

    name = "distinct"

    def __init__(self):
        self._n = 0

    async def astream(self, transcript, tools):
        if not tools:  # grace turn: wrap up in text
            yield TextDelta(text="forced wrap-up")
            yield Completed(input_tokens=3, output_tokens=2)
            return
        self._n += 1
        cid = f"call_{self._n}"
        yield ToolCallStart(id=cid, name="echo")
        yield ToolCallDelta(id=cid, args_fragment=f'{{"x": "v{self._n}"}}')
        yield Completed(input_tokens=5, output_tokens=2)

    async def acomplete(self, transcript, tools):
        raise NotImplementedError


class TextProvider:
    """Answers immediately with text and no tool call — a clean completion."""

    name = "text"

    async def astream(self, transcript, tools):
        yield TextDelta(text="the answer is 42")
        yield Completed(input_tokens=5, output_tokens=2)

    async def acomplete(self, transcript, tools):
        raise NotImplementedError


def test_cross_turn_loop_guard_caps_tool_executions():
    # A model repeating the identical call every turn must trip the loop guard
    # *across* turns. The guard fires on the MAX_REPEAT_CALLS-th identical call,
    # short-circuiting before the body — so the body runs one fewer time.
    counter = {"n": 0}
    catalog = ToolCatalog(tools=[_echo_tool(counter)])

    result = asyncio.run(
        arun(
            provider=LoopingProvider(),
            catalog=catalog,
            user_message="loop",
            pinned_tools={"echo"},
        )
    )

    assert counter["n"] == MAX_REPEAT_CALLS - 1
    assert isinstance(result, AgentRunResult)
    assert result.stop_reason == "max_iterations"


def test_max_iterations_returns_not_raises():
    # Exhaustion is an outcome, not an exception: partial state comes back.
    counter = {"n": 0}
    catalog = ToolCatalog(tools=[_echo_tool(counter)])

    result = asyncio.run(
        arun(
            provider=DistinctToolProvider(),
            catalog=catalog,
            user_message="go",
            pinned_tools={"echo"},
            max_iterations=3,
        )
    )

    assert result.stop_reason == "max_iterations"
    assert result.iterations_used == 3
    assert counter["n"] == 3            # one distinct tool call per turn
    assert len(result.transcript) > 0   # transcript preserved, not discarded


def test_max_iterations_param_is_enforced():
    # The cap comes from the argument, not the MAX_ITERATIONS module constant.
    counter = {"n": 0}
    catalog = ToolCatalog(tools=[_echo_tool(counter)])

    result = asyncio.run(
        arun(
            provider=DistinctToolProvider(),
            catalog=catalog,
            user_message="go",
            pinned_tools={"echo"},
            max_iterations=2,
        )
    )

    assert result.iterations_used == 2
    assert counter["n"] == 2


def test_normal_completion_reports_completed():
    catalog = ToolCatalog(tools=[_echo_tool({"n": 0})])

    result = asyncio.run(
        arun(
            provider=TextProvider(),
            catalog=catalog,
            user_message="what is the answer?",
            pinned_tools={"echo"},
        )
    )

    assert result.stop_reason == "completed"
    assert result.summary == "the answer is 42"
    assert result.iterations_used == 1


def test_deadline_stops_gracefully_without_running_a_turn():
    # A deadline already in the past (negative offset, so the boundary is
    # deterministic with no clock race) stops the loop before it calls the
    # provider, returning stop_reason='deadline'.
    counter = {"n": 0}
    catalog = ToolCatalog(tools=[_echo_tool(counter)])

    result = asyncio.run(
        arun(
            provider=LoopingProvider(),
            catalog=catalog,
            user_message="go",
            pinned_tools={"echo"},
            deadline_s=-1.0,
        )
    )

    assert result.stop_reason == "deadline"
    assert counter["n"] == 0
    assert result.iterations_used == 0


class RecordingProvider:
    """Records how many tools it was offered on each call. Requests a tool
    every turn until tools are stripped, then wraps up in text."""

    name = "recording"

    def __init__(self):
        self._n = 0
        self.tool_counts: list[int] = []

    async def astream(self, transcript, tools):
        self.tool_counts.append(len(tools))
        if not tools:
            yield TextDelta(text="wrapped up")
            yield Completed(input_tokens=3, output_tokens=2)
            return
        self._n += 1
        cid = f"call_{self._n}"
        yield ToolCallStart(id=cid, name="echo")
        yield ToolCallDelta(id=cid, args_fragment=f'{{"x": "v{self._n}"}}')
        yield Completed(input_tokens=5, output_tokens=2)

    async def acomplete(self, transcript, tools):
        raise NotImplementedError


class GraceExplodesProvider:
    """Burns the budget, then raises on the tool-stripped grace turn — models
    a wrap-up call that itself fails (e.g. context overflow)."""

    name = "grace-explodes"

    def __init__(self):
        self._n = 0

    async def astream(self, transcript, tools):
        if not tools:
            raise RuntimeError("model exploded on wrap-up")
        self._n += 1
        cid = f"call_{self._n}"
        yield ToolCallStart(id=cid, name="echo")
        yield ToolCallDelta(id=cid, args_fragment=f'{{"x": "v{self._n}"}}')
        yield Completed(input_tokens=5, output_tokens=2)

    async def acomplete(self, transcript, tools):
        raise NotImplementedError


def test_grace_turn_returns_real_summary():
    # On exhaustion the model gets one tool-stripped turn to synthesize an
    # answer; that answer is returned as the summary, not the bare marker.
    counter = {"n": 0}
    catalog = ToolCatalog(tools=[_echo_tool(counter)])

    result = asyncio.run(
        arun(
            provider=DistinctToolProvider(),
            catalog=catalog,
            user_message="go",
            pinned_tools={"echo"},
            max_iterations=3,
        )
    )

    assert result.stop_reason == "max_iterations"
    assert result.summary == "forced wrap-up"   # real answer, not the marker
    assert counter["n"] == 3                     # grace turn dispatched no tool


def test_grace_turn_calls_provider_with_tools_stripped():
    # The enforcement is the empty tool list: the final (grace) call must be
    # offered zero tools, while every budget-burning turn had tools available.
    provider = RecordingProvider()
    catalog = ToolCatalog(tools=[_echo_tool({"n": 0})])

    result = asyncio.run(
        arun(
            provider=provider,
            catalog=catalog,
            user_message="go",
            pinned_tools={"echo"},
            max_iterations=2,
        )
    )

    assert result.stop_reason == "max_iterations"
    assert provider.tool_counts[-1] == 0            # grace turn: tools stripped
    assert all(n > 0 for n in provider.tool_counts[:-1])  # burn turns had tools


def test_grace_turn_failure_falls_back_without_raising():
    # A grace turn that fails must not reintroduce an exception on the
    # termination path — it falls back to the marker summary.
    counter = {"n": 0}
    catalog = ToolCatalog(tools=[_echo_tool(counter)])

    result = asyncio.run(
        arun(
            provider=GraceExplodesProvider(),
            catalog=catalog,
            user_message="go",
            pinned_tools={"echo"},
            max_iterations=2,
        )
    )

    assert isinstance(result, AgentRunResult)
    assert result.stop_reason == "max_iterations"
    assert result.summary == _EXHAUSTED_MARKER
