"""Minimal serialization base for our dataclass models (offline stand-in for pydantic).

Provides the dict / JSON round-tripping that pydantic's BaseModel would give us.
Swapping these dataclasses back to pydantic later is mechanical: the field names
and shapes match the Build Spec's model definitions.
"""
from __future__ import annotations

import dataclasses
import json
from typing import Any


class JsonModel:
    """Mixin for @dataclass models: dict/JSON serialization + basic reconstruction."""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)  # type: ignore[arg-type]

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        return cls(**data)  # type: ignore[call-arg]