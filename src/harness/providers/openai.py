from __future__ import annotations

import json
from typing import Any, AsyncIterator, Literal


from ..messages import (
    Block, Message, ReasoningBlock, TextBlock, ToolCall, ToolResult, Transcript,
)

from .events import (
    Completed, ReasoningDelta, StreamEvent,
    TextDelta, ToolCallDelta, ToolCallStart,
)
from .base import Provider, ProviderResponse, accumulate


ReasoningEffort = Literal["minimal", "low", "medium", "high"]


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self, model: str = "gpt-5-nano",
                 client: Any | None = None,
                 max_output_tokens: int = 4096,
                 reasoning_effort: ReasoningEffort | None = None) -> None:
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.reasoning_effort = reasoning_effort
        if client is None:
            from openai import AsyncOpenAI  # external SDK
            client = AsyncOpenAI()
        self._client = client

    async def astream(
        self, transcript: Transcript, tools: list[dict]
    ) -> AsyncIterator[StreamEvent]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "input": [i for m in transcript.messages for i in _to_responses_input(m)],
            "max_output_tokens": self.max_output_tokens,
            "stream": True,
        }
        if transcript.system:
            kwargs["instructions"] = transcript.system
        if tools:
            kwargs["tools"] = [_tool_to_responses(t) for t in tools]
            # Parallel tool calls stay on (matches Anthropic §5.4 above).
        if self.reasoning_effort is not None:
            kwargs["reasoning"] = {"effort": self.reasoning_effort}
            kwargs["include"] = ["reasoning.encrypted_content"]
            kwargs["store"] = False  # we manage state locally; see §3.4

        stream = await self._client.responses.create(**kwargs)

        # item_id → call_id for function_call items (argument deltas reference
        # the item_id but dispatch uses call_id).
        call_ids_by_item: dict[str, str] = {}
        # Reasoning items we capture for round-trip replay (Chapter 3 §3.4).
        reasoning_item_meta: dict[str, dict] = {}

        input_tokens = 0
        output_tokens = 0
        reasoning_tokens = 0

        async for event in stream:
            et = getattr(event, "type", None)

            if et == "response.output_text.delta":
                delta = getattr(event, "delta", "") or ""
                if delta:
                    yield TextDelta(text=delta)

            elif et == "response.reasoning_summary_text.delta":
                delta = getattr(event, "delta", "") or ""
                if delta:
                    yield ReasoningDelta(text=delta)

            elif et == "response.output_item.added":
                item = getattr(event, "item", None)
                if item is None:
                    continue
                item_type = getattr(item, "type", None)
                if item_type == "function_call":
                    call_id = getattr(item, "call_id", None) or getattr(item, "id", "")
                    item_id = getattr(item, "id", "") or call_id
                    name = getattr(item, "name", "") or ""
                    if item_id:
                        call_ids_by_item[item_id] = call_id
                    yield ToolCallStart(id=call_id, name=name)
                elif item_type == "reasoning":
                    rid = getattr(item, "id", "") or ""
                    if rid:
                        reasoning_item_meta.setdefault(rid, {"id": rid})

            elif et == "response.function_call_arguments.delta":
                delta = getattr(event, "delta", "") or ""
                if delta:
                    item_id = getattr(event, "item_id", "") or ""
                    call_id = call_ids_by_item.get(item_id, item_id)
                    yield ToolCallDelta(id=call_id, args_fragment=delta)

            elif et == "response.output_item.done":
                # Reasoning items carry their `encrypted_content` here — we
                # stash it so the next turn can replay the reasoning item.
                item = getattr(event, "item", None)
                if item is None or getattr(item, "type", None) != "reasoning":
                    continue
                rid = getattr(item, "id", "") or ""
                enc = getattr(item, "encrypted_content", None)
                if rid:
                    entry = reasoning_item_meta.setdefault(rid, {"id": rid})
                    if enc:
                        entry["encrypted_content"] = enc

            elif et == "response.completed":
                response = getattr(event, "response", None)
                usage = getattr(response, "usage", None) if response else None
                if usage is not None:
                    input_tokens = getattr(usage, "input_tokens", 0) or 0
                    output_tokens = getattr(usage, "output_tokens", 0) or 0
                    details = getattr(usage, "output_tokens_details", None)
                    if details is not None:
                        reasoning_tokens = (
                            getattr(details, "reasoning_tokens", 0) or 0
                        )

        yield Completed(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            reasoning_metadata=(
                {"openai_items": list(reasoning_item_meta.values())}
                if reasoning_item_meta else {}
            ),
        )

    async def acomplete(self, transcript, tools):
        return await accumulate(self.astream(transcript, tools))


def _tool_to_responses(tool: dict) -> dict:
    # Our canonical tool shape is Anthropic-flavoured: {name, description, input_schema}.
    # Responses flattens function tools: {type, name, description, parameters}.
    return {
        "type": "function",
        "name": tool["name"],
        "description": tool.get("description", ""),
        "parameters": tool.get("input_schema", tool.get("parameters", {})),
    }


def _to_responses_input(message: Message) -> list[dict]:
    # Tool results become function_call_output items (no role — typed directly).
    if any(isinstance(b, ToolResult) for b in message.blocks):
        return [
            {"type": "function_call_output", "call_id": b.call_id, "output": b.content}
            for b in message.blocks if isinstance(b, ToolResult)
        ]

    # Reasoning items get replayed to Responses so chain-of-thought carries
    # across turns. We stashed the opaque `id` + `encrypted_content` in
    # metadata on the way in; if the metadata is missing (e.g. the
    # ReasoningBlock came from Anthropic, or reasoning wasn't enabled on
    # the provider that produced it), we skip — Responses won't accept a
    # raw text reasoning item.
    items: list[dict] = []
    for b in message.blocks:
        if isinstance(b, ReasoningBlock):
            for spec in b.metadata.get("openai_items") or []:
                item: dict[str, Any] = {
                    "type": "reasoning",
                    "summary": spec.get("summary") or [],
                }
                if rid := spec.get("id"):
                    item["id"] = rid
                if enc := spec.get("encrypted_content"):
                    item["encrypted_content"] = enc
                items.append(item)

    # Assistant tool calls become function_call items.
    if any(isinstance(b, ToolCall) for b in message.blocks):
        for b in message.blocks:
            if isinstance(b, ToolCall):
                items.append({
                    "type": "function_call",
                    "call_id": b.id,
                    "name": b.name,
                    "arguments": json.dumps(b.args),
                })
        return items

    # Plain text keeps its role/content shape.
    text = "\n".join(b.text for b in message.blocks if isinstance(b, TextBlock))
    return [{"role": message.role, "content": text}]

