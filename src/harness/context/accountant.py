from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Literal

import tiktoken
from ..messages import (
    Block, Message, ReasoningBlock, TextBlock, ToolCall, ToolResult, Transcript
)

Component = Literal["system", "tools", "history", "retrieved", "headroom"]

@dataclass
class ContextBudget:
    window_size: int = 200_000
    headroom: int = 4096
    yellow_threshold: float = 0.60
    red_threshold: float = 0.80

    @property
    def usable(self) -> int:
        return self.window_size - self.headroom
    
@dataclass
class ContextSnapshot:
    totals: dict[Component, int] = field(default_factory=dict)
    budget: ContextBudget = field(default_factory=ContextBudget)

    @property
    def total_used(self) -> int:
        return sum(v for k, v in self.totals.items() if k != "headroom")

    @property
    def utilization(self) -> float:
        return self.total_used / max(self.budget.usable, 1) 
    
    @property
    def state(self) -> Literal["green", "yellow", "red"]:
        u = self.utilization
        if u >= self.budget.red_threshold:
            return "red"
        if u >= self.budget.yellow_threshold:
            return "yellow"
        return "green"
    

class ContextAccountant:
    """Counts tokens per component across a transcript."""

    def __init__(self, encoding_name: str = "cl100k_base",
                 budget: ContextBudget | None = None) -> None:
        self._enc = tiktoken.get_encoding(encoding_name)
        self.budget = budget or ContextBudget()

    def snapshot(
        self,
        transcript: Transcript,
        tools: list[dict] | None = None,
        retrieved: list[str] | None = None,
    ) -> ContextSnapshot:
        totals: dict[Component, int] = {
            "system": self._count_text(transcript.system or ""),
            "tools": sum(self._count_text(json.dumps(t)) for t in (tools or [])),
            "history": sum(self._count_message(m) for m in transcript.messages),
            "retrieved": sum(self._count_text(r) for r in (retrieved or [])),
            "headroom": self.budget.headroom,
        }
        return ContextSnapshot(totals=totals, budget=self.budget)

    def _count_text(self, s: str) -> int:
            return len(self._enc.encode(s))

    def _count_message(self, m: Message) -> int:
        # message overhead is ~4 tokens per message in most providers' formats
        total = 4
        for block in m.blocks:
            total += self._count_block(block)
        return total

    def _count_block(self, block: Block) -> int:
        match block:
            case TextBlock(text=t):
                return self._count_text(t)
            case ToolCall(name=n, args=a):
                return self._count_text(n) + self._count_text(json.dumps(a)) + 6
            case ToolResult(content=c):
                return self._count_text(c) + 4
            case ReasoningBlock(text=t):
                # Only present when an adapter preserves reasoning on the
                # transcript (Anthropic thinking + tools, or explicit
                # consumer choice). Weight is the text body; the opaque
                # signature / encrypted_content in metadata is negligible.
                return self._count_text(t)
            case _:
                # Defensive fallthrough: new block types added later should
                # be undercounted (not crash the measurement component).
                return 0