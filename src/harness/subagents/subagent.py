from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SubagentSpec:
    """What a sub-agent is told to do."""
    objective: str               # the specific task, operationally specific
    output_format: str           # how the result should be structured
    tools_allowed: list[str]     # tool names available to the sub-agent
    max_iterations: int = 20
    max_tokens: int = 50_000     # hard context budget
    system_override: str | None = None  # override parent's system prompt


@dataclass
class SubagentResult:
    """What a sub-agent returns to its parent."""
    summary: str                 # the synthesized answer
    tokens_used: int
    iterations_used: int
    error: str | None = None     # non-null if sub-agent failed
