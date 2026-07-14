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
    reasoning_metadata: dict = field(default_factory=dict)
    kind: Literal["completed"] = "completed"


StreamEvent = TextDelta | ReasoningDelta | ToolCallStart | ToolCallDelta | Completed
