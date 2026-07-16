from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class TextDelta:
    text: str
    kind: Literal["text_delta"] = "text_delta"


@dataclass(frozen=True)
class ReasoningDelta:
    """A fragment of model-internal reasoning (Chapter 3's `ReasoningBlock`).

    Emitted by reasoning-enabled providers alongside TextDelta; the loop
    accumulates them into `ProviderResponse.reasoning_text`.
    """
    text: str
    kind: Literal["reasoning_delta"] = "reasoning_delta"


@dataclass(frozen=True)
class ToolCallStart:
    id: str
    name: str
    kind: Literal["tool_call_start"] = "tool_call_start"


@dataclass(frozen=True)
class ToolCallDelta:
    id: str
    args_fragment: str  # partial JSON, accumulated by the loop
    kind: Literal["tool_call_delta"] = "tool_call_delta"


@dataclass(frozen=True)
class Completed:
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int = 0
    # Anthropic reports cached prompt tokens in separate usage fields — they are
    # NOT included in input_tokens (which is the uncached remainder only). Carry
    # them so the loop can reconstruct true prompt size (input + these two).
    # OpenAI's input_tokens is already the full count, so it leaves these at 0.
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    reasoning_metadata: dict = field(default_factory=dict)
    kind: Literal["completed"] = "completed"


StreamEvent = TextDelta | ReasoningDelta | ToolCallStart | ToolCallDelta | Completed
