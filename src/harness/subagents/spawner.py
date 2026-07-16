from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from ..agent import arun
from ..context.accountant import ContextAccountant, ContextBudget
from ..permissions.manager import PermissionManager
from ..providers.base import Provider
from ..tools.selector import ToolCatalog
from .subagent import SubagentResult, SubagentSpec


class SubagentBudgetExceeded(Exception):
    pass


# Tools a sub-agent must never receive, however it phrases tools_allowed: the
# delegation tools themselves. Stripping them makes agent-in-agent recursion
# structurally impossible (gemini blocks the same way) — and, because a gated
# sub-agent registry therefore never holds a spawn tool, it also rules out
# re-entering the shared write-gate, so that gate can never deadlock.
_DELEGATION_TOOL_NAMES = {"spawn_subagent", "spawn_parallel_subagents"}


@dataclass
class SubagentSpawner:
    provider: Provider
    catalog: ToolCatalog
    max_subagents_per_session: int = 5
    # Threaded into every sub-agent so delegated tool calls are gated exactly
    # like the parent's — fail-closed in headless (an "ask" becomes "deny").
    # None means sub-agents run ungated; pass one whenever the parent has one.
    permission_manager: PermissionManager | None = None
    _spawn_count: int = field(default=0, init=False)

    async def spawn(
        self,
        spec: SubagentSpec,
        parent_scratchpad_root: str | None = None,
        justification: str = "",
        write_gate: asyncio.Lock | None = None,
    ) -> SubagentResult:
        # Budget check and increment run with no `await` between them, so under
        # single-threaded asyncio no sibling spawn can interleave and overshoot
        # the cap. Keep them adjacent: an await here would reintroduce the race.
        if self._spawn_count >= self.max_subagents_per_session:
            raise SubagentBudgetExceeded(
                f"spawn budget of {self.max_subagents_per_session} exhausted"
            )
        self._spawn_count += 1

        # Restrict the catalog to the tools the sub-agent is allowed, minus the
        # delegation tools — a sub-agent can never spawn (see above).
        allowed = [
            t for t in self.catalog.tools
            if t.name in spec.tools_allowed
            and t.name not in _DELEGATION_TOOL_NAMES
        ]
        if not allowed:
            available = sorted(t.name for t in self.catalog.tools)
            return SubagentResult(
                summary="", tokens_used=0, iterations_used=0,
                error=(f"none of tools_allowed={spec.tools_allowed} match "
                       f"available tools: {available}"),
            )
        sub_catalog = ToolCatalog(tools=allowed)

        # constrain context budget
        budget = ContextBudget(window_size=spec.max_tokens)
        accountant = ContextAccountant(budget=budget)

        system = spec.system_override or _default_subagent_system(spec)

        try:
            result = await arun(
                provider=self.provider,
                catalog=sub_catalog,
                user_message=(
                    f"Objective: {spec.objective}\n\n"
                    f"Return format: {spec.output_format}"
                ),
                system=system,
                accountant=accountant,
                permission_manager=self.permission_manager,
                write_gate=write_gate,
                max_iterations=spec.max_iterations,
            )
            return SubagentResult(
                summary=result.summary,
                tokens_used=result.tokens_used,
                iterations_used=result.iterations_used,
                # A sub-agent that stopped on a bound rather than finishing is a
                # failure the parent must see — don't let it read as "done".
                error=None if result.stop_reason == "completed"
                else f"subagent stopped: {result.stop_reason}",
            )
        except SubagentBudgetExceeded:
            raise  # let budget failures propagate to the caller
        except Exception as e:
            return SubagentResult(
                summary="", tokens_used=0, iterations_used=0, error=str(e),
            )


def _default_subagent_system(spec: SubagentSpec) -> str:
    header = f"""\
You are a sub-agent. You have one objective:

{spec.objective}

Return your answer in this format:
{spec.output_format}

You have the following tools available: {spec.tools_allowed}.
You have a maximum of {spec.max_iterations} iterations.
You have a maximum of {spec.max_tokens} tokens of context.
"""
    # Smaller / weaker models sometimes narrate tool calls in text instead of
    # actually dispatching them. When the spec allows tools at all, make the
    # mandatory-execute rule explicit — see the callout below this snippet.
    mandate = ""
    if spec.tools_allowed:
        mandate = (
            "\nYou MUST call at least one tool from your allowed list before\n"
            "producing your final answer. Do not describe what you would do — do it.\n"
            "Describing a tool call in prose without actually invoking it is a failure.\n"
        )
    footer = """
When you have completed the objective, produce your final answer in the
requested format. Do not continue working after you have the answer.
If you cannot complete the objective (missing data, scope unclear), say
so explicitly — do not fabricate.
"""
    return header + mandate + footer
