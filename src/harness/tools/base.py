from __future__ import annotations
from dataclasses import dataclass, field
from typing import Awaitable, Literal, Callable

SideEffect = Literal["read", "write", "network", "mutate"]

@dataclass(frozen=True)
class Tool:
    """A callable exposed to the model.

    name        -- stable identifier the model calls by.
    description -- contract text the model reads. Must state scope,
                   preconditions, and side effects in plain English.
    input_schema -- JSON Schema for the arguments dict.
    run         -- the callable. Accepts kwargs matching the schema;
                   returns a string (what the model will see as the result).
    side_effects -- declared effect tags. Used by the permission layer.
    """
    name: str
    description: str
    input_schema: dict
    run: Callable[..., str] | None = None
    arun: Callable[..., Awaitable[str]] | None = None 
    side_effects: frozenset[SideEffect] = field(default_factory=frozenset)

    def schema_for_provider(self) -> dict:
        """The dict shape providers expect (Anthropic-flavored)."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
    
    def __post_init__(self) -> None:
        if self.run is None and self.arun is None:
            raise ValueError(f"tool {self.name!r}: exactly one of run/arun required")