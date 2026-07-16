# src/harness/providers/anthropic.py
from __future__ import annotations

import os
from typing import Any, AsyncIterator

from .retry import RetryPolicy

from ..messages import (
    Block, Message, ReasoningBlock, TextBlock, ToolCall, ToolResult, Transcript,
)
from .events import (
    Completed, ReasoningDelta, StreamEvent,
    TextDelta, ToolCallDelta, ToolCallStart,
)
from .base import Provider, ProviderResponse, accumulate


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-4-6",
                 client: Any | None = None,
                 enable_thinking: bool = False,
                 thinking_budget_tokens: int = 2000,
                 max_tokens: int = 4096,
                 enable_prompt_cache: bool = True) -> None:
        self.model = model
        self.enable_thinking = enable_thinking
        self.thinking_budget_tokens = thinking_budget_tokens
        self.max_tokens = max_tokens
        self.enable_prompt_cache = enable_prompt_cache
        if client is None:
            from anthropic import AsyncAnthropic  # external SDK
            client = AsyncAnthropic()
        self._client = client

    async def astream(
        self, transcript: Transcript, tools: list[dict]
    ):
        
        retry = RetryPolicy()
        
        async def open_stream():
            kwargs: dict = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "messages": [_to_anthropic(m, self.enable_thinking)
                              for m in transcript.messages],
                "tools": _cached_tools(tools) if self.enable_prompt_cache else tools,
            }
            if transcript.system:
                kwargs["system"] = (
                    _cached_system(transcript.system)
                    if self.enable_prompt_cache else transcript.system
                )
            if self.enable_thinking:
                kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": self.thinking_budget_tokens,
                }
            return await self._client.messages.stream(**kwargs)
       
        # Parallel tool use stays on (Anthropic's default). `accumulate`
        # handles the batch; the loop dispatches each call sequentially.

        stream_cm = await retry.run(open_stream)

        current_tool_id: str | None = None
        async with stream_cm as stream:
            async for raw in stream:
                event = _translate(raw, current_tool_id)
                if isinstance(event, ToolCallStart):
                    current_tool_id = event.id
                if event is not None:
                    yield event

            final = await stream.get_final_message()
            yield Completed(
                input_tokens=final.usage.input_tokens,
                output_tokens=final.usage.output_tokens,
            )

    async def acomplete(self, transcript, tools):
        return await accumulate(self.astream(transcript, tools))


# Anthropic caches the request prefix (tools → system → messages) only up to
# an explicit `cache_control` breakpoint. Marking the last tool caches the whole
# tools array; marking system caches tools+system — the largest always-stable
# chunk of a tool-using turn. Two breakpoints give a shorter-prefix fallback hit
# if system ever changes but tools don't; both are well within Anthropic's limit
# of four. The prefix only stays cacheable if it's byte-stable across turns —
# that's what ToolCatalog.for_turn guarantees for a fits-in-budget catalog.
_CACHE_CONTROL = {"type": "ephemeral"}


def _cached_tools(tools: list[dict]) -> list[dict]:
    """Copy `tools`, marking the last one as a cache breakpoint. Copies so the
    caller's provider-neutral schemas are never mutated."""
    if not tools:
        return tools
    out = [dict(t) for t in tools]
    out[-1] = {**out[-1], "cache_control": _CACHE_CONTROL}
    return out


def _cached_system(system: str) -> list[dict]:
    """Render the system prompt as a single text block carrying a cache
    breakpoint (a bare string can't hold cache_control)."""
    return [{"type": "text", "text": system, "cache_control": _CACHE_CONTROL}]


def _to_anthropic(message: Message, keep_reasoning: bool) -> dict:
    # Drop ReasoningBlocks when thinking isn't enabled — the API rejects
    # `thinking` blocks without the feature turned on. With thinking on,
    # reasoning (including its signature) must round-trip.
    content: list[dict] = []
    for block in message.blocks:
        if isinstance(block, ReasoningBlock) and not keep_reasoning:
            continue
        content.append(_block_to_anthropic(block))
    return {"role": message.role, "content": content}


def _block_to_anthropic(block: Block) -> dict:
    match block:
        case TextBlock(text=t):
            return {"type": "text", "text": t}
        case ToolCall(id=i, name=n, args=a):
            return {"type": "tool_use", "id": i, "name": n, "input": a}
        case ToolResult(call_id=i, content=c, is_error=err):
            return {"type": "tool_result", "tool_use_id": i,
                    "content": c, "is_error": err}
        case ReasoningBlock(text=t, metadata=meta):
            out: dict[str, Any] = {"type": "thinking", "thinking": t}
            if (sig := meta.get("signature")) is not None:
                out["signature"] = sig  # required on round-trip
            return out


def _translate(raw: Any, current_tool_id: str | None) -> StreamEvent | None:
    t = raw.type
    if t == "content_block_start" and raw.content_block.type == "tool_use":
        return ToolCallStart(id=raw.content_block.id, name=raw.content_block.name)
    if t == "content_block_delta":
        d = raw.delta
        if d.type == "text_delta":
            return TextDelta(text=d.text)
        if d.type == "thinking_delta":
            return ReasoningDelta(text=d.thinking)
        if d.type == "signature_delta":
            return None  # the signature lands on the final message, not a stream event
        if d.type == "input_json_delta":
            return ToolCallDelta(id=current_tool_id or "",
                                 args_fragment=d.partial_json)
    return None
