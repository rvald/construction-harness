from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import uuid4


class StepStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    done = "done"
    blocked = "blocked"


@dataclass
class Step:
    id: str
    description: str
    status: StepStatus = StepStatus.pending
    evidence: str | None = None   # what proved the step done
    notes: str = ""

    def is_terminal(self) -> bool:
        return self.status in (StepStatus.done, StepStatus.blocked)


@dataclass
class Postcondition:
    description: str
    satisfied: bool = False
    evidence: str | None = None


@dataclass
class Plan:
    objective: str
    steps: list[Step] = field(default_factory=list)
    postconditions: list[Postcondition] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: str = field(default_factory=lambda: str(uuid4()))

    def all_steps_terminal(self) -> bool:
        return all(s.is_terminal() for s in self.steps)

    def all_postconditions_satisfied(self) -> bool:
        return all(pc.satisfied for pc in self.postconditions)

    def is_ready_to_finalize(self) -> bool:
        return self.all_steps_terminal() and self.all_postconditions_satisfied()

    def to_render(self) -> str:
        """Render the plan as a string the model can read."""
        lines = [f"# Plan: {self.objective}\n"]
        lines.append("## Steps")
        for i, s in enumerate(self.steps, start=1):
            mark = {"pending": "[ ]", "in_progress": "[.]",
                    "done": "[x]", "blocked": "[!]"}[s.status.value]
            lines.append(f"{i}. {mark} {s.description}")
            if s.evidence:
                lines.append(f"     evidence: {s.evidence}")
            if s.notes:
                lines.append(f"     notes: {s.notes}")
        lines.append("\n## Postconditions")
        for i, pc in enumerate(self.postconditions, start=1):
            mark = "[x]" if pc.satisfied else "[ ]"
            lines.append(f"{i}. {mark} {pc.description}")
            if pc.evidence:
                lines.append(f"     evidence: {pc.evidence}")
        return "\n".join(lines)
