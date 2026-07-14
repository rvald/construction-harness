from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Decision = Literal["allow", "deny", "ask"]


@dataclass(frozen=True)
class PermissionRequest:
    tool_name: str
    args: dict
    side_effects: frozenset[str]


@dataclass(frozen=True)
class PermissionOutcome:
    decision: Decision
    reason: str = ""
    remember_for_session: bool = False
