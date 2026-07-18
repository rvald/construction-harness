"""The pre-seeded takeoff plan — the mandatory postconditions the completion gate enforces.

Pure takeoff content built from the harness's generic Plan/Postcondition primitives. The harness
loop enforces whatever plan is in the holder without knowing anything about takeoff. There are no
steps: the system prompt carries the work sequence, and the postconditions are the gate. The
entrypoint seeds this into the PlanHolder so the postconditions are fixed (the model verifies them
but cannot author or weaken them — plan_create is not exposed to it).
"""
from __future__ import annotations

from src.harness.plans.model import Plan, Postcondition

_POSTCONDITIONS = [
    "The takeoff job reached a terminal state and its results were retrieved (summary read).",
    "The tiers were cross-checked: uncounted catalog types, double-count risks, and rooms "
    "without area were identified.",
    "A grounded report was finalized — every number pipeline-traceable and all gaps recorded "
    "as escalations.",
]


def takeoff_plan() -> Plan:
    """The fixed plan for a single-drawings takeoff: the postconditions the gate enforces."""
    return Plan(
        objective="Produce a grounded, reconciled schedule_items takeoff for one drawings PDF.",
        steps=[],
        postconditions=[Postcondition(description=d) for d in _POSTCONDITIONS],
    )
