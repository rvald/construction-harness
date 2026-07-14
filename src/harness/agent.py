from __future__ import annotations

import asyncio, logging
from typing import Callable

from .messages import Message, Transcript, ToolCall, ToolResult
from .providers.base import Provider, ProviderResponse, accumulate
from .providers.events import StreamEvent, TextDelta
from .tools.registry import ToolRegistry

from .context.accountant import ContextAccountant, ContextSnapshot
from .context.compactor import Compactor
from .tools.selector import ToolCatalog, query_from_transcript

log = logging.getLogger(__name__)

MAX_ITERATIONS = 20


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
) -> str:
    if transcript is None:
        transcript = Transcript(system=system)
    transcript.append(Message.user_text(user_message))
    accountant = accountant or ContextAccountant() 
    compactor = compactor or Compactor(accountant, provider)   

    for _ in range(MAX_ITERATIONS):
        # Select tools for this turn.
        query = query_from_transcript(transcript)
        selected = catalog.select(query, k=tools_per_turn,
                                   must_include=pinned_tools)
        registry = ToolRegistry(tools=selected)

        snapshot = accountant.snapshot(transcript, tools=registry.schemas())
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
                on_snapshot(accountant.snapshot(transcript, tools=registry.schemas()))


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

        if response.is_final:
            transcript.append(Message.from_assistant_response(response))
            return response.text or ""

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

    raise RuntimeError(f"agent did not finish in {MAX_ITERATIONS} iterations")


def run(*args, **kwargs) -> str:
    """Sync wrapper for scripts and tests."""
    return asyncio.run(arun(*args, **kwargs))


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
    stream = provider.astream(transcript, registry.schemas())

    async def forward():
        async for event in stream:
            if on_event is not None:
                on_event(event)
            if isinstance(event, TextDelta):
                partial_text.append(event.text)
            yield event

    return await accumulate(forward())
