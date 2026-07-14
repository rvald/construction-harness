from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from ..messages import ToolResult
from ..tools.base import Tool
from .model import Decision, PermissionOutcome, PermissionRequest
from .policy import Policy


# A prompt function asks the human and returns "allow" or "deny".
# Set to None for non-interactive contexts (e.g. RQ workers with no stdin);
# an "ask" decision is then downgraded to "deny" rather than hanging on input().
HumanPrompt = Callable[[PermissionRequest], Awaitable[Decision]]


async def default_cli_prompt(req: PermissionRequest) -> Decision:
    """Simple stdin prompt. Replace with a richer UI as needed."""
    print(f"\nPermission request:")
    print(f"  tool: {req.tool_name}")
    print(f"  args: {req.args}")
    print(f"  side effects: {sorted(req.side_effects)}")
    response = input("Allow? [y/N]: ").strip().lower()
    return "allow" if response == "y" else "deny"


@dataclass
class PermissionManager:
    policy: Policy
    human_prompt: HumanPrompt | None = field(default=default_cli_prompt)
    session_approvals: set[str] = field(default_factory=set)

    async def check(self, tool: Tool, args: dict) -> PermissionOutcome:
        key = self._cache_key(tool.name, args)
        if key in self.session_approvals:
            return PermissionOutcome("allow", "previously approved this session")

        req = PermissionRequest(
            tool_name=tool.name, args=args, side_effects=tool.side_effects
        )
        outcome = self.policy(req)

        if outcome.decision == "ask":
            if self.human_prompt is None:
                # No human available (headless/worker): fail closed.
                return PermissionOutcome(
                    "deny", "ask downgraded to deny (non-interactive)"
                )
            human_decision = await self.human_prompt(req)
            outcome = PermissionOutcome(
                decision=human_decision,
                reason=f"human said {human_decision}",
            )
            if human_decision == "allow":
                self.session_approvals.add(key)

        return outcome

    def _cache_key(self, tool_name: str, args: dict) -> str:
        import json
        return f"{tool_name}:{json.dumps(args, sort_keys=True)}"
