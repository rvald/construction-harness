from __future__ import annotations

from pathlib import Path
from typing import Callable

from .model import Decision, PermissionOutcome, PermissionRequest


Policy = Callable[[PermissionRequest], PermissionOutcome]


def allow_all() -> Policy:
    return lambda req: PermissionOutcome("allow", "allow-all policy")


def deny_all() -> Policy:
    return lambda req: PermissionOutcome("deny", "deny-all policy")


def by_side_effect(
    read: Decision = "allow",
    write: Decision = "ask",
    network: Decision = "ask",
    mutate: Decision = "ask",
) -> Policy:
    """Decide based on declared side effects. Most-restrictive wins."""
    precedence = {"deny": 0, "ask": 1, "allow": 2}
    def check(req: PermissionRequest) -> PermissionOutcome:
        decisions: list[tuple[Decision, str]] = []
        if "read" in req.side_effects:
            decisions.append((read, "read"))
        if "write" in req.side_effects:
            decisions.append((write, "write"))
        if "network" in req.side_effects:
            decisions.append((network, "network"))
        if "mutate" in req.side_effects:
            decisions.append((mutate, "mutate"))
        if not decisions:
            # Fail safe: an untagged tool is an unknown quantity, so ask
            # rather than silently allowing it to bypass the gate.
            return PermissionOutcome("ask", "no declared side effects → ask")
        d, src = min(decisions, key=lambda x: precedence[x[0]])
        return PermissionOutcome(d, f"{src} side effect → {d}")
    return check


def path_allowlist(allowed_dirs: list[str]) -> Policy:
    """For filesystem tools: paths must canonicalize under an allowed root."""
    allowed = [Path(d).resolve() for d in allowed_dirs]

    def check(req: PermissionRequest) -> PermissionOutcome:
        if req.tool_name not in {"read_file_viewport", "edit_lines",
                                   "read_file", "write_file"}:
            return PermissionOutcome("allow", "not a filesystem tool")
        path_arg = req.args.get("path")
        if not path_arg:
            return PermissionOutcome("deny", "no path argument")
        try:
            target = Path(path_arg).resolve()
        except OSError:
            return PermissionOutcome("deny", f"bad path: {path_arg}")
        for root in allowed:
            try:
                target.relative_to(root)
                return PermissionOutcome("allow", f"path under {root}")
            except ValueError:
                continue
        return PermissionOutcome(
            "deny", f"path {target} not under any of: {allowed}"
        )
    return check

def compose(*policies: Policy) -> Policy:
    """Compose in left-to-right order; first non-'allow' wins."""
    def check(req: PermissionRequest) -> PermissionOutcome:
        for p in policies:
            outcome = p(req)
            if outcome.decision != "allow":
                return outcome
        return PermissionOutcome("allow", "all policies allowed")
    return check