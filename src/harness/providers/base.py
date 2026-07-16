from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol

from ..messages import MALFORMED_ARGS_KEY, Transcript
from .events import StreamEvent

import json
from ..providers.events import (
    Completed, ReasoningDelta, TextDelta, ToolCallDelta, ToolCallStart,
)


@dataclass(frozen=True)
class ToolCallRef:
    """One tool invocation carried in a ProviderResponse.

    Separate from `messages.ToolCall` because `ProviderResponse` is the
    pre-transcript handoff shape; `ToolCall` is the in-transcript block
    (with a `kind` discriminator). The loop constructs one in-transcript
    ToolCall from each ToolCallRef when it commits the assistant message.
    """
    id: str
    name: str
    args: dict


@dataclass(frozen=True)
class ProviderResponse:
    text: str | None = None
    tool_calls: tuple[ToolCallRef, ...] = ()
    reasoning_text: str | None = None
    reasoning_metadata: dict = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    # Anthropic-only: cached prompt tokens, reported separately from
    # input_tokens (see providers.events.Completed). True prompt size is
    # input_tokens + these two; used by the loop as a context-accounting floor.
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    @property
    def is_tool_call(self) -> bool:
        return len(self.tool_calls) > 0

    @property
    def is_final(self) -> bool:
        return self.text is not None and not self.tool_calls

    # Back-compat shortcuts into tool_calls[0]. The book's earlier chapters
    # talked about a single tool call per turn; those shortcuts keep that
    # prose honest for the common single-call case. Migrate to iterating
    # `tool_calls` for the batched case.

    @property
    def tool_call_id(self) -> str | None:
        return self.tool_calls[0].id if self.tool_calls else None

    @property
    def tool_name(self) -> str | None:
        return self.tool_calls[0].name if self.tool_calls else None

    @property
    def tool_args(self) -> dict | None:
        return self.tool_calls[0].args if self.tool_calls else None


class Provider(Protocol):
    name: str

    def astream(
        self, transcript: Transcript, tools: list[dict]
    ) -> AsyncIterator[StreamEvent]:
        ...

    async def acomplete(
        self, transcript: Transcript, tools: list[dict]
    ) -> ProviderResponse:
        ...

async def accumulate(stream: AsyncIterator[StreamEvent]) -> ProviderResponse:
    """Collect a stream into one ProviderResponse — handles batched tool calls."""
    text_parts: list[str] = []
    reasoning_parts: list[str] = []

    # Keyed by tool id, values {"name": str, "args_buffer": str}. We also
    # remember arrival order so batched calls come out in the order the
    # provider emitted them, not dict-iteration order.
    tool_entries: dict[str, dict] = {}
    tool_ids_in_order: list[str] = []
    last_opened_id: str | None = None
    orphan_counter = 0

    input_tokens = 0
    output_tokens = 0
    reasoning_tokens = 0
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0
    reasoning_metadata: dict = {}

    async for event in stream:
        match event:
            case TextDelta(text=t):
                text_parts.append(t)
            case ReasoningDelta(text=t):
                reasoning_parts.append(t)
            case ToolCallStart(id=i, name=n):
                entry_id = i or f"_orphan_{orphan_counter}"
                if not i:
                    orphan_counter += 1
                if entry_id not in tool_entries:
                    tool_entries[entry_id] = {"name": n, "args_buffer": ""}
                    tool_ids_in_order.append(entry_id)
                else:
                    tool_entries[entry_id]["name"] = n
                last_opened_id = entry_id
            case ToolCallDelta(id=i, args_fragment=frag):
                # Fragments reference their parent tool_id. Fall back to
                # the last-opened id if omitted; synthesize an orphan if
                # a fragment arrives before any Start — never drop data.
                target_id = i or last_opened_id
                if target_id is None:
                    target_id = f"_orphan_{orphan_counter}"
                    orphan_counter += 1
                if target_id not in tool_entries:
                    tool_entries[target_id] = {"name": "", "args_buffer": ""}
                    tool_ids_in_order.append(target_id)
                    last_opened_id = target_id
                tool_entries[target_id]["args_buffer"] += frag
            case Completed(input_tokens=it, output_tokens=ot,
                        reasoning_tokens=rt,
                        cache_read_input_tokens=crt,
                        cache_creation_input_tokens=cct,
                        reasoning_metadata=rmeta):
                input_tokens, output_tokens = it, ot
                reasoning_tokens = rt
                cache_read_input_tokens = crt
                cache_creation_input_tokens = cct
                reasoning_metadata = dict(rmeta)

    reasoning_text = "".join(reasoning_parts) if reasoning_parts else None

    tool_calls: list[ToolCallRef] = []
    for tid in tool_ids_in_order:
        entry = tool_entries[tid]
        try:
            args = json.loads(entry["args_buffer"]) if entry["args_buffer"] else {}
        except json.JSONDecodeError:
            # Parse failed here — the only layer that knows it was a JSON error.
            # Stash the raw buffer under a sentinel so the registry emits a
            # parse-specific message next turn, not a schema error that has lost
            # the fact that this was malformed JSON in the first place.
            args = {MALFORMED_ARGS_KEY: entry["args_buffer"]}
        tool_calls.append(ToolCallRef(id=tid, name=entry["name"], args=args))

    if tool_calls:
        return ProviderResponse(
            tool_calls=tuple(tool_calls),
            reasoning_text=reasoning_text,
            reasoning_metadata=reasoning_metadata,
            input_tokens=input_tokens, output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
        )
    return ProviderResponse(
        text="".join(text_parts),
        reasoning_text=reasoning_text,
        reasoning_metadata=reasoning_metadata,
        input_tokens=input_tokens, output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
    )