"""Fail-closed permission policy for the takeoff agent.

The agent's catalog is entirely first-party and trusted, so the policy is a simple allow-list by
tool name: the known tools run, anything else is denied. This is codex's "allow exactly the
preset's tools, deny the rest" posture. It makes the run safe headless (an unexpected tool — a
future MCP addition, or a typo — is denied by default) and it lets the agent's own control-plane
writes (plan progress, finalize_report) through, which the generic by_side_effect(write="ask")
default would otherwise turn into a deny in a headless (no-human) run.
"""
from __future__ import annotations

from src.harness.permissions.model import PermissionOutcome, PermissionRequest
from src.harness.permissions.policy import Policy


def takeoff_policy(allowed_names: set[str]) -> Policy:
    """Allow iff the tool is one of the agent's own known tools; deny everything else."""
    allowed = set(allowed_names)

    def check(req: PermissionRequest) -> PermissionOutcome:
        if req.tool_name in allowed:
            return PermissionOutcome("allow", "takeoff agent tool")
        return PermissionOutcome("deny", f"tool {req.tool_name!r} not in the takeoff allow-list")

    return check
