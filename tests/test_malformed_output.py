"""Malformed-output recovery.

The model is a stochastic generator, so the seam where its stream becomes typed
values (`accumulate` running json.loads) can fail. The error the harness returns
there is not a log line — it goes straight back to the model as the next turn's
prompt, so it must name the real fault. These tests pin two failures that were
verified broken before this change:

  * malformed tool-call JSON produced a *misleading* error (a schema
    "required property" complaint, or a leaked `_raw`/sentinel TypeError),
  * an empty final turn was returned as a blank "completed" answer — success
    with no content, invisible to a headless worker.

Async loop, no pytest-asyncio: driven with asyncio.run() like the sibling tests.
"""
from __future__ import annotations

import asyncio

from src.harness.agent import _EMPTY_MARKER, arun
from src.harness.messages import MALFORMED_ARGS_KEY
from src.harness.providers.base import accumulate
from src.harness.providers.events import (
    Completed,
    TextDelta,
    ToolCallDelta,
    ToolCallStart,
)
from src.harness.tools.decorator import tool
from src.harness.tools.registry import ToolRegistry
from src.harness.tools.selector import ToolCatalog


def _echo_tool(counter: dict):
    """Tool with a *required* arg; bumps counter['n'] only when the body runs."""

    @tool(side_effects={"read"})
    def echo(x: str) -> str:
        """Echo x back to the caller."""
        counter["n"] += 1
        return f"echo:{x}"

    return echo


def _ping_tool(counter: dict):
    """Tool with an *optional* arg — the case where a leaked sentinel used to
    sail through validation and blow up as an unexpected-kwarg TypeError."""

    @tool(side_effects={"read"})
    def ping(note: str = "hi") -> str:
        """Ping, with an optional note."""
        counter["n"] += 1
        return f"pong:{note}"

    return ping


# --- accumulate: a truncated args buffer becomes the sentinel, never a crash ---

def test_truncated_json_is_stashed_under_the_sentinel():
    async def stream():
        yield ToolCallStart(id="c1", name="echo")
        yield ToolCallDelta(id="c1", args_fragment='{"x": "abc')  # cut off
        yield Completed(input_tokens=1, output_tokens=1)

    resp = asyncio.run(accumulate(stream()))
    ref = resp.tool_calls[0]
    assert ref.args == {MALFORMED_ARGS_KEY: '{"x": "abc'}


# --- dispatch: the model-facing message names the real fault (bad JSON) ---

def test_malformed_args_required_field_reports_json_not_schema_error():
    counter = {"n": 0}
    reg = ToolRegistry(tools=[_echo_tool(counter)])

    res = asyncio.run(
        reg.dispatch("echo", {MALFORMED_ARGS_KEY: '{"x": "abc'}, "c1")
    )

    assert res.is_error
    assert "not valid JSON" in res.content
    assert "required property" not in res.content   # the old misdiagnosis
    assert counter["n"] == 0                         # body never ran


def test_malformed_args_optional_field_does_not_leak_sentinel():
    # The regression: with no required field the sentinel used to pass schema
    # validation and reach run(**args), surfacing as a TypeError about `_raw`.
    counter = {"n": 0}
    reg = ToolRegistry(tools=[_ping_tool(counter)])

    res = asyncio.run(
        reg.dispatch("ping", {MALFORMED_ARGS_KEY: '{"note": "hi'}, "c1")
    )

    assert res.is_error
    assert "not valid JSON" in res.content
    assert "TypeError" not in res.content
    assert MALFORMED_ARGS_KEY not in res.content     # sentinel never exposed
    assert counter["n"] == 0


# --- loop: the model sees the error and recovers on the next turn ---

class MalformedThenAnswerProvider:
    """Turn 1: a tool call with truncated JSON args. Turn 2: having seen the
    parse error in the transcript, the model answers with text."""

    name = "malformed-then-answer"

    def __init__(self):
        self._n = 0

    async def astream(self, transcript, tools):
        self._n += 1
        if self._n == 1:
            yield ToolCallStart(id="c1", name="echo")
            yield ToolCallDelta(id="c1", args_fragment='{"x": "abc')  # truncated
            yield Completed(input_tokens=5, output_tokens=2)
        else:
            yield TextDelta(text="recovered")
            yield Completed(input_tokens=5, output_tokens=2)

    async def acomplete(self, transcript, tools):
        raise NotImplementedError


def test_malformed_call_surfaces_error_then_model_recovers():
    counter = {"n": 0}
    catalog = ToolCatalog(tools=[_echo_tool(counter)])

    result = asyncio.run(
        arun(
            provider=MalformedThenAnswerProvider(),
            catalog=catalog,
            user_message="go",
            pinned_tools={"echo"},
        )
    )

    assert result.stop_reason == "completed"
    assert result.summary == "recovered"
    assert counter["n"] == 0   # the malformed call was intercepted, never run

    # The parse error is actually in the transcript the model saw next turn.
    tool_results = [
        b.content
        for m in result.transcript.messages
        for b in m.blocks
        if getattr(b, "kind", None) == "tool_result"
    ]
    assert any("not valid JSON" in c for c in tool_results)


# --- loop: an empty final turn is surfaced, not returned as a blank success ---

class EmptyProvider:
    """Ends the turn with no tool call and no text — an absence, not an answer."""

    name = "empty"

    async def astream(self, transcript, tools):
        yield Completed(input_tokens=1, output_tokens=1)

    async def acomplete(self, transcript, tools):
        raise NotImplementedError


def test_empty_final_response_is_surfaced_not_silently_completed():
    catalog = ToolCatalog(tools=[_echo_tool({"n": 0})])

    result = asyncio.run(
        arun(
            provider=EmptyProvider(),
            catalog=catalog,
            user_message="go",
            pinned_tools={"echo"},
        )
    )

    assert result.stop_reason == "empty_response"   # not "completed"
    assert result.summary == _EMPTY_MARKER
    assert result.iterations_used == 1
