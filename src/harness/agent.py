from __future__ import annotations

import asyncio
from typing import Callable

from .messages import Message, Transcript, ToolCall, ToolResult
from .providers.base import Provider, ProviderResponse, accumulate
from .providers.events import StreamEvent, TextDelta
from .tools.registry import ToolRegistry


MAX_ITERATIONS = 20


async def arun(
    provider: Provider,
    registry: ToolRegistry,
    user_message: str,
    transcript: Transcript | None = None,
    system: str | None = None,
    on_event: Callable[[StreamEvent], None] | None = None,
    on_tool_call: Callable[[ToolCall], None] | None = None,
    on_tool_result: Callable[[ToolResult], None] | None = None,
) -> str:
    if transcript is None:
        transcript = Transcript(system=system)
    transcript.append(Message.user_text(user_message))

    for _ in range(MAX_ITERATIONS):
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

            result = registry.dispatch(call.name, call.args, call.id)
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
