from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class ProviderResponse:
    """Response from a provider, this could be: either text, or a tool call"""
    kind: str
    text: str | None = None
    tool_name: str | None = None
    tool_args: dict | None = None
    tool_call_id: str | None = None

class Provider(Protocol):
    def complete(self, transcript: list[dict], tools: list[dict]) -> ProviderResponse:
        """Given a transcript and a list of tools, return a response"""
        ...