"""Compaction boundary-safety: the transcript stays a valid tool-pair stream.

Both provider APIs 400 if a tool_result has no matching tool_call. Three guards
uphold that invariant:
  * the summarizer snaps its cut so it never orphans a kept tool_result,
  * a send-time pass drops any orphan that slips through anyway,
  * the accountant treats real provider usage as a floor under its estimate.

The summarizer is async; the repo has no pytest-asyncio, so we drive it with
`asyncio.run()` inside plain sync tests, matching the other async tests here.
"""
from __future__ import annotations

import asyncio

from src.harness.messages import Message, ToolCall, ToolResult, Transcript
from src.harness.context.summarizer import summarize_prefix
from src.harness.context.masking import drop_orphan_tool_results
from src.harness.context.accountant import ContextAccountant, ContextBudget
from src.harness.providers.anthropic import _block_to_anthropic
from src.harness.providers.base import ProviderResponse, accumulate
from src.harness.providers.events import Completed, TextDelta


class _FakeProvider:
    """Returns a canned summary; never touches the network."""

    async def acomplete(self, transcript, tools):
        return ProviderResponse(text="SUMMARY", tool_calls=(),
                                input_tokens=10, output_tokens=5)


def _orphaned_tool_use_ids(t: Transcript) -> list[str]:
    """tool_use_ids referenced by a tool_result with no preceding tool_use,
    measured through the real Anthropic serializer — exactly what would 400."""
    seen: set[str] = set()
    orphans: list[str] = []
    for m in t.messages:
        for block in m.blocks:
            aj = _block_to_anthropic(block)
            if aj["type"] == "tool_use":
                seen.add(aj["id"])
            elif aj["type"] == "tool_result" and aj["tool_use_id"] not in seen:
                orphans.append(aj["tool_use_id"])
    return orphans


def _tool_loop_transcript() -> Transcript:
    """A pure tool-loop: after the initial user turn, everything is alternating
    assistant(tool_call) / user(tool_result) pairs — the interior has no safe
    plain-user boundary to land on."""
    t = Transcript(system="sys")
    t.append(Message.user_text("start"))
    for cid in ("A", "B", "C"):
        t.append(Message(role="assistant", blocks=[ToolCall(id=cid, name="f", args={})]))
        t.append(Message.tool_result(ToolResult(call_id=cid, content=f"res {cid}")))
    t.append(Message.user_text("next"))
    return t


def test_summarizer_never_orphans_at_a_hostile_boundary():
    # keep_recent_turns=4 puts the naive cut between tool_call B and its result.
    t = _tool_loop_transcript()
    assert _orphaned_tool_use_ids(t) == []

    result = asyncio.run(summarize_prefix(t, _FakeProvider(), keep_recent_turns=4))
    assert result is not None
    # The invariant holds and the kept region opens on an assistant turn, never
    # a dangling tool_result.
    assert _orphaned_tool_use_ids(t) == []
    first_kept_after_summary = t.messages[2]
    assert not any(isinstance(b, ToolResult) for b in first_kept_after_summary.blocks)


def test_summarizer_returns_none_when_snap_empties_the_prefix():
    # Only one call/result pair between the anchors; snapping back leaves nothing
    # to summarize, so it must no-op rather than emit an empty summary.
    t = Transcript(system="sys")
    t.append(Message.user_text("start"))
    t.append(Message(role="assistant", blocks=[ToolCall(id="A", name="f", args={})]))
    t.append(Message.tool_result(ToolResult(call_id="A", content="res A")))
    t.append(Message.user_text("next"))
    assert asyncio.run(summarize_prefix(t, _FakeProvider(), keep_recent_turns=2)) is None


def test_drop_orphan_tool_results_repairs_and_reports():
    t = Transcript(system="sys")
    t.append(Message.user_text("start"))
    t.append(Message.tool_result(ToolResult(call_id="GONE", content="orphan")))
    t.append(Message(role="assistant", blocks=[ToolCall(id="D", name="f", args={})]))
    t.append(Message.tool_result(ToolResult(call_id="D", content="res D")))

    dropped = drop_orphan_tool_results(t)
    assert dropped == 1
    assert _orphaned_tool_use_ids(t) == []
    # The message that held only the orphan is gone; the valid pair survives.
    assert len(t.messages) == 3


def test_drop_orphan_tool_results_is_a_noop_on_a_clean_transcript():
    t = _tool_loop_transcript()
    messages_before = t.messages
    assert drop_orphan_tool_results(t) == 0
    # Same list object — array stays byte-identical so the prompt cache holds.
    assert t.messages is messages_before


def test_real_input_tokens_floor_trips_compaction_when_estimate_undercounts():
    acc = ContextAccountant(
        budget=ContextBudget(window_size=1000, headroom=100, red_threshold=0.80)
    )
    t = Transcript(system="hi")
    t.append(Message.user_text("tiny"))

    assert acc.snapshot(t).state == "green"
    # Provider reported 850 real input tokens; the floor lifts us into red even
    # though tiktoken sees almost nothing.
    assert acc.snapshot(t, last_real_input_tokens=850).state == "red"


def test_real_input_tokens_floor_never_lowers_the_estimate():
    acc = ContextAccountant(budget=ContextBudget(window_size=1000, headroom=100))
    t = Transcript(system="x" * 4000)  # estimate already large
    est = acc.snapshot(t).total_used
    # A small real count must not shrink an already-large estimate.
    assert acc.snapshot(t, last_real_input_tokens=1).total_used == est


def test_accumulate_carries_cache_tokens_so_the_floor_is_true_prompt_size():
    # Under Anthropic caching, input_tokens is only the uncached tail; the loop's
    # floor must add the cache_* fields back to see true occupancy.
    async def _stream():
        yield TextDelta(text="hi")
        yield Completed(input_tokens=100, output_tokens=5,
                        cache_read_input_tokens=700,
                        cache_creation_input_tokens=50)

    resp = asyncio.run(accumulate(_stream()))
    assert resp.input_tokens == 100
    assert resp.cache_read_input_tokens == 700
    assert resp.cache_creation_input_tokens == 50
    # This mirrors the loop's floor computation in arun.
    floor = (resp.input_tokens + resp.cache_read_input_tokens
             + resp.cache_creation_input_tokens)
    assert floor == 850


def test_accumulate_defaults_cache_tokens_to_zero_for_non_caching_providers():
    # OpenAI's input_tokens is already the full count — a Completed with no
    # cache fields must leave the floor equal to input_tokens.
    async def _stream():
        yield Completed(input_tokens=850, output_tokens=5)

    resp = asyncio.run(accumulate(_stream()))
    assert resp.cache_read_input_tokens == 0
    assert resp.cache_creation_input_tokens == 0
    floor = (resp.input_tokens + resp.cache_read_input_tokens
             + resp.cache_creation_input_tokens)
    assert floor == 850
