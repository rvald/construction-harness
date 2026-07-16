from __future__ import annotations

import asyncio, logging
from time import monotonic
from typing import Callable, Literal

from .messages import Message, TextBlock, Transcript, ToolCall, ToolResult
from .providers.base import Provider, ProviderResponse, accumulate
from .providers.events import StreamEvent, TextDelta
from .tools.registry import ToolRegistry

from .context.accountant import ContextAccountant, ContextSnapshot
from .context.compactor import Compactor
from .context.masking import drop_orphan_tool_results
from .tools.selector import ToolCatalog, query_from_transcript
from .permissions.manager import PermissionManager
from dataclasses import dataclass

log = logging.getLogger(__name__)

MAX_ITERATIONS = 20

# Injected on budget exhaustion for a final tool-stripped "grace turn": the
# model gets one chance to synthesize the work it already did into an answer,
# instead of being cut off one step short with its last tool results unread.
GRACE_NUDGE = (
    "You have reached your step budget and cannot call any more tools. "
    "Using only the information already gathered above, give your best final "
    "answer now. If you could not fully complete the task, say so plainly and "
    "report what you did determine — do not fabricate."
)
_EXHAUSTED_MARKER = "[stopped: reached max_iterations without a final answer]"
# A "final" turn with no tool call and empty text is an absence, not an answer.
# Returning "" with stop_reason="completed" would report success to a headless
# worker that has no human to notice the blank — so we surface it explicitly.
_EMPTY_MARKER = "[stopped: model returned an empty final response]"


@dataclass
class AgentRunResult:
    summary: str               # the final answer text (was arun's bare return)
    tokens_used: int           # input + output across all turns
    iterations_used: int       # how many turns the loop took
    transcript: Transcript     # full record — useful for logs / debugging
    # Why the loop stopped. "completed" = model produced a final answer;
    # "empty_response" = it stopped with no tool call and no text (an absence,
    # not an answer); the others are bounded-loop terminations, not errors.
    stop_reason: Literal[
        "completed", "max_iterations", "deadline", "empty_response"
    ] = "completed"


async def arun(
    provider: Provider,
    catalog: ToolCatalog,
    user_message: str,
    transcript: Transcript | None = None,
    system: str | None = None,
    on_event: Callable[[StreamEvent], None] | None = None,
    on_tool_call: Callable[[ToolCall], None] | None = None,
    on_tool_result: Callable[[ToolResult], None] | None = None,
    on_snapshot: Callable[[ContextSnapshot], None] | None = None,
    accountant: ContextAccountant | None = None,
    compactor: Compactor | None = None,
    pinned_tools: set[str] | None = None,
    tools_per_turn: int = 7,
    permission_manager: PermissionManager | None = None,
    write_gate: asyncio.Lock | None = None,
    max_iterations: int = MAX_ITERATIONS,
    deadline_s: float | None = None,
) -> AgentRunResult:
    if transcript is None:
        transcript = Transcript(system=system)
    transcript.append(Message.user_text(user_message))
    accountant = accountant or ContextAccountant()
    compactor = compactor or Compactor(accountant, provider)

    # The accountant is stateless (it re-measures context size per snapshot and
    # keeps no running total), so accumulate provider-reported cost here.
    tokens_used = 0

    # Previous turn's real input-token count, fed into the accountant as a floor
    # under its tiktoken estimate (see ContextSnapshot.real_input_tokens). None
    # until the first turn completes.
    last_input_tokens: int | None = None

    # Loop-detection history is run-scoped: it must outlive the fresh registry
    # the loop builds each turn (below), or cross-turn repeats go unseen.
    call_history: list[tuple[str, str]] = []

    # Optional wall-clock bound for headless runs with no human to interrupt.
    # Checked between turns, so a single turn may overrun by its own duration.
    deadline = monotonic() + deadline_s if deadline_s is not None else None

    for iteration in range(max_iterations):
        if deadline is not None and monotonic() > deadline:
            return AgentRunResult(
                summary=_last_assistant_text(transcript)
                or "[stopped: wall-clock deadline reached]",
                tokens_used=tokens_used,
                iterations_used=iteration,
                transcript=transcript,
                stop_reason="deadline",
            )
        # Tools for this turn. A catalog that fits the budget goes out whole,
        # in a stable order, so the tools prefix stays byte-identical turn to
        # turn (prompt cache holds; no tool vanishes mid-plan). Only an
        # over-budget catalog falls back to per-turn BM25 selection.
        query = query_from_transcript(transcript)
        selected = catalog.for_turn(query, k=tools_per_turn,
                                    must_include=pinned_tools)
        # A long-lived manager and the loop-detection history are threaded into
        # each turn's fresh registry so their state survives across turns.
        registry = ToolRegistry(tools=selected,
                                permission_manager=permission_manager,
                                call_history=call_history,
                                write_gate=write_gate)

        snapshot = accountant.snapshot(transcript, tools=registry.schemas(),
                                       last_real_input_tokens=last_input_tokens)
        if on_snapshot is not None:
            on_snapshot(snapshot)
        
        if snapshot.state == "red":
            result = await compactor.compact_if_needed(transcript, registry.schemas())
            log.info("compacted: masked=%d, summarized_turns=%d, new_state=%s",
                     result.masking_tokens_freed,
                     result.summarization_turns_replaced,
                     result.final_state)
            # Re-snapshot so observers see the post-compaction state
            # in the same iteration. Otherwise the last visible frame
            # is red and the compaction's effect is invisible — which
            # matters if the next turn is the one that returns a final
            # answer (there's no iteration after that to re-fire).
            if on_snapshot is not None:
                on_snapshot(accountant.snapshot(
                    transcript, tools=registry.schemas(),
                    last_real_input_tokens=last_input_tokens))


        partial_text: list[str] = []
        try:
            response = await _one_turn(
                provider, registry, transcript, partial_text, on_event,
            )
        except asyncio.CancelledError:
            if partial_text:
                transcript.append(Message.assistant_text(
                    "".join(partial_text) + " [interrupted]"
                ))
            raise

        tokens_used += response.input_tokens + response.output_tokens
        # True prompt size, not just the uncached remainder: under Anthropic
        # prompt caching, input_tokens excludes the cached prefix (reported in
        # the cache_* fields). Summing them keeps the accountant floor honest.
        last_input_tokens = (
            response.input_tokens
            + response.cache_read_input_tokens
            + response.cache_creation_input_tokens
        )

        if response.is_final:
            transcript.append(Message.from_assistant_response(response))
            # `accumulate` always sets text to a string, so an empty/whitespace
            # final means the model produced nothing usable. Surface that as its
            # own outcome instead of returning a blank "completed" answer.
            if not (response.text or "").strip():
                return AgentRunResult(
                    summary=_EMPTY_MARKER,
                    tokens_used=tokens_used,
                    iterations_used=iteration + 1,
                    transcript=transcript,
                    stop_reason="empty_response",
                )
            return AgentRunResult(
                summary=response.text or "",
                tokens_used=tokens_used,
                iterations_used=iteration + 1,
                transcript=transcript,
                stop_reason="completed",
            )

        # Tool calls: commit the assistant turn (one message, N ToolCall
        # blocks), then dispatch each call in arrival order. One tool_result
        # message per call, matching Chapter 3's convention.
        transcript.append(Message.from_assistant_response(response))
        for ref in response.tool_calls:
            call = ToolCall(id=ref.id, name=ref.name, args=dict(ref.args))
            if on_tool_call is not None:
                on_tool_call(call)

            result = await registry.dispatch(call.name, call.args, call.id)
            transcript.append(Message.tool_result(result))
            if on_tool_result is not None:
                on_tool_result(result)

    # Budget exhausted. Rather than cut the model off one step short, give it
    # one final tool-stripped "grace turn" to synthesize an answer. The empty
    # registry means the provider is called with no tools, so the model *must*
    # produce text — that guarantees a single-shot wrap-up, not another turn.
    #
    # Best-effort: this must never turn a graceful termination back into a
    # crash, so any failure falls back to the marker summary.
    transcript.append(Message.user_text(GRACE_NUDGE))
    partial_text: list[str] = []
    summary = _EXHAUSTED_MARKER
    try:
        response = await _one_turn(
            provider, ToolRegistry(), transcript, partial_text, on_event,
        )
        tokens_used += response.input_tokens + response.output_tokens
        transcript.append(Message.from_assistant_response(response))
        summary = response.text or _EXHAUSTED_MARKER
    except asyncio.CancelledError:
        if partial_text:
            transcript.append(Message.assistant_text(
                "".join(partial_text) + " [interrupted]"
            ))
        raise
    except Exception:
        log.warning("grace turn failed; returning best-effort marker",
                    exc_info=True)
        summary = _last_assistant_text(transcript) or _EXHAUSTED_MARKER

    return AgentRunResult(
        summary=summary,
        tokens_used=tokens_used,
        iterations_used=max_iterations,
        transcript=transcript,
        stop_reason="max_iterations",
    )


def run(*args, **kwargs) -> str:
    """Sync wrapper for scripts and tests."""
    return asyncio.run(arun(*args, **kwargs))


def _last_assistant_text(transcript: Transcript) -> str | None:
    """The most recent assistant text block, if any — a best-effort partial
    answer when the loop stops without producing a clean final response."""
    for message in reversed(transcript.messages):
        if message.role != "assistant":
            continue
        for block in reversed(message.blocks):
            if isinstance(block, TextBlock):
                return block.text
    return None


async def _one_turn(
    provider: Provider,
    registry: ToolRegistry,
    transcript: Transcript,
    partial_text: list[str],
    on_event: Callable[[StreamEvent], None] | None,
) -> ProviderResponse:
    """Run one provider turn; push text deltas into `partial_text` as we go.

    On CancelledError, whatever was accumulated so far is still in
    `partial_text` — the caller can flush it into the transcript.
    """
    # Last line of defense before every send: an orphaned tool_result (a result
    # whose tool_call was dropped) 400s both providers. The summarizer snaps its
    # cut to avoid this, so a hit here means an upstream mutation is buggy — repair
    # and log rather than send a request we know will fail.
    dropped = drop_orphan_tool_results(transcript)
    if dropped:
        log.warning("dropped %d orphan tool_result(s) before send", dropped)

    stream = provider.astream(transcript, registry.schemas())

    async def forward():
        async for event in stream:
            if on_event is not None:
                on_event(event)
            if isinstance(event, TextDelta):
                partial_text.append(event.text)
            yield event

    return await accumulate(forward())
