from __future__ import annotations

import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from .base import Tool

from ..messages import Transcript, TextBlock, ToolCall


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


@dataclass
class ToolCatalog:
    """A catalog of tools, with a BM25 index over names + descriptions."""

    tools: list[Tool]

    def __post_init__(self) -> None:
        self._tokenized = [
            _tokenize(f"{t.name} {t.description}") for t in self.tools
        ]
        # BM25Okapi divides by the corpus size, so an empty tool list raises
        # ZeroDivisionError. A catalog with no tools is a valid (degenerate)
        # state — e.g. a sub-agent whose allowed set is empty — so guard it.
        self._bm25 = BM25Okapi(self._tokenized) if self._tokenized else None
        self._by_name = {t.name: t for t in self.tools}

    def select(self, query: str, k: int = 7, must_include: set[str] | None = None) -> list[Tool]:
        """Return up to k tools most relevant to the query.

        must_include: tool names that must appear in the result regardless
        of score — typically "core" tools the agent always has.
        """
        must_include = must_include or set()
        pinned = [self._by_name[n] for n in must_include if n in self._by_name]

        if self._bm25 is None:
            return pinned  # empty catalog: nothing to rank

        scores = self._bm25.get_scores(_tokenize(query))
        ranked = sorted(enumerate(scores), key=lambda x: -x[1])

        remaining_slots = max(0, k - len(pinned))
        picks: list[Tool] = list(pinned)
        seen = {t.name for t in pinned}
        for i, score in ranked:
            if remaining_slots <= 0:
                break
            tool = self.tools[i]
            if tool.name in seen:
                continue
            if score <= 0:
                continue
            picks.append(tool)
            seen.add(tool.name)
            remaining_slots -= 1

        return picks

    def for_turn(
        self, query: str, k: int, must_include: set[str] | None = None
    ) -> list[Tool]:
        """The tools to expose this turn.

        A catalog that fits the budget goes out whole, in stable insertion
        order, so the serialized `tools` prefix stays byte-identical across
        turns — the provider's prompt cache holds, and no tool can vanish
        out from under a plan (the "tool cliff"). Only a catalog too large
        to send whole falls back to BM25 selection, which necessarily churns
        the prefix. See select() for the ranking used in that case.
        """
        if len(self.tools) <= k:
            return list(self.tools)
        return self.select(query, k=k, must_include=must_include)

    def get(self, name: str) -> Tool | None:
        return self._by_name.get(name)

    def all_names(self) -> list[str]:
        return list(self._by_name.keys())
    
def query_from_transcript(transcript: Transcript) -> str:
    """Derive a search query from the transcript: user intent plus recent activity."""
    parts: list[str] = []
    # first user message is the anchor
    if transcript.messages:
        first = transcript.messages[0]
        for b in first.blocks:
            if isinstance(b, TextBlock):
                parts.append(b.text)
    # last 3 assistant blocks (text or tool calls) for current focus
    recent = [m for m in transcript.messages[-6:] if m.role == "assistant"]
    for m in recent:
        for b in m.blocks:
            if isinstance(b, TextBlock):
                parts.append(b.text[:500])
            elif isinstance(b, ToolCall):
                parts.append(f"{b.name} {list(b.args.keys())}")
    return " ".join(parts)