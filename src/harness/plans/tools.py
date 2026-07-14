from __future__ import annotations

from dataclasses import dataclass

from ..tools.base import Tool
from ..tools.decorator import tool
from .model import Plan, Postcondition, Step, StepStatus


@dataclass
class PlanHolder:
    """Wraps a mutable Plan so tools can mutate it through a shared reference."""
    plan: Plan | None = None

    def require(self) -> Plan:
        if self.plan is None:
            raise RuntimeError("no active plan")
        return self.plan


def plan_tools(holder: PlanHolder) -> list[Tool]:

    @tool(side_effects={"write"})
    def plan_create(objective: str, steps: list[str],
                     postconditions: list[str]) -> str:
        """Create or replace the plan for this session.

        objective: one-sentence description of what you're trying to
                   accomplish.
        steps: ordered list of step descriptions. Each is a specific
               actionable item, not a vague intent.
        postconditions: list of conditions that must be true when you
                        declare the task complete. Examples: "file X
                        exists and contains Y"; "tests in module Z pass".

        Call this once at the start of any non-trivial task, before
        beginning work. If the plan is wrong mid-task, call this again
        to replace it — the harness records the rewrite.
        """
        holder.plan = Plan(
            objective=objective,
            steps=[Step(id=f"s{i}", description=d) for i, d in enumerate(steps)],
            postconditions=[Postcondition(description=d) for d in postconditions],
        )
        return f"plan created with {len(steps)} steps and {len(postconditions)} postconditions"

    @tool(side_effects={"read"})
    def plan_show() -> str:
        """Display the current plan with its step and postcondition status.

        Use this any time you want to re-orient — especially after long
        sub-tasks or compaction. The plan is durable; compaction won't
        lose it.
        """
        return holder.require().to_render()

    @tool(side_effects={"write"})
    def step_update(step_number: int, status: str, evidence: str = "",
                     notes: str = "") -> str:
        """Update a step's status.

        step_number: 1-based index from `plan_show`.
        status: one of 'pending', 'in_progress', 'done', 'blocked'.
        evidence: required for 'done'. One-sentence proof of completion
                  (reference to a tool result, a scratchpad key, etc.).
        notes: optional free text.
        """
        plan = holder.require()
        if step_number < 1 or step_number > len(plan.steps):
            return f"step_number {step_number} out of range (1..{len(plan.steps)})"
        try:
            new_status = StepStatus(status)
        except ValueError:
            return f"invalid status {status!r}; use pending/in_progress/done/blocked"
        if new_status == StepStatus.done and not evidence:
            return ("error: marking a step 'done' requires evidence. Describe "
                    "what proved the step complete (e.g., 'wrote file and "
                    "read it back; content matches').")
        s = plan.steps[step_number - 1]
        plan.steps[step_number - 1] = Step(
            id=s.id, description=s.description,
            status=new_status, evidence=evidence or None,
            notes=notes,
        )
        return f"step {step_number} → {status}"

    @tool(side_effects={"write"})
    def postcondition_verify(postcondition_number: int, evidence: str) -> str:
        """Mark a postcondition as verified.

        postcondition_number: 1-based index.
        evidence: required. Concrete proof the postcondition holds.

        This is what the harness checks before letting you declare the
        task complete. Do not verify a postcondition without evidence.
        """
        plan = holder.require()
        if postcondition_number < 1 or postcondition_number > len(plan.postconditions):
            return (f"postcondition_number {postcondition_number} out of range "
                    f"(1..{len(plan.postconditions)})")
        if not evidence:
            return "error: evidence is required to verify a postcondition"
        pc = plan.postconditions[postcondition_number - 1]
        plan.postconditions[postcondition_number - 1] = Postcondition(
            description=pc.description, satisfied=True, evidence=evidence,
        )
        return f"postcondition {postcondition_number} verified"

    return [plan_create, plan_show, step_update, postcondition_verify]
