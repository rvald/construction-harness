from __future__ import annotations

from ..tools.base import Tool
from ..tools.decorator import async_tool
from .spawner import SubagentSpawner
from .subagent import SubagentSpec


def spawn_tool(spawner: SubagentSpawner) -> Tool:

    @async_tool(side_effects={"mutate"})  # conservative — sub-agents may do anything
    async def spawn_subagent(
        objective: str,
        output_format: str,
        tools_allowed: list[str],
        max_iterations: int = 15,
        justification: str = "",
    ) -> str:
        """Spawn a sub-agent to handle a delegated task.

        objective: the specific task for the sub-agent, operationally
                   specific ("read files X and Y and report their schemas"),
                   NOT vague ("look into the database").
        output_format: exact format the sub-agent should return its answer
                       in. Examples: "a JSON object with keys X and Y";
                       "a three-paragraph summary, each under 100 words".
        tools_allowed: names of tools the sub-agent is permitted to use.
                       Narrower is better; the sub-agent can't use tools
                       not in this list.
        max_iterations: hard cap on sub-agent turns. Default 15; reduce
                        for simple lookups.
        justification: one sentence explaining WHY a sub-agent is better
                       than handling this in-line. Required; if you can't
                       articulate why, don't spawn.

        Returns the sub-agent's summary, prefixed with its token cost.
        Side effects: depend on sub-agent's tools; pessimistically 'mutate'.
        """
        if not justification:
            return ("error: justification is required. If you cannot explain "
                    "why a sub-agent is better than inline handling, do not "
                    "spawn one.")
        if not tools_allowed:
            return ("error: tools_allowed must be non-empty. Specify which "
                    "tools the sub-agent needs.")

        spec = SubagentSpec(
            objective=objective,
            output_format=output_format,
            tools_allowed=tools_allowed,
            max_iterations=max_iterations,
        )
        result = await spawner.spawn(spec, justification=justification)
        if result.error:
            return f"sub-agent error: {result.error}"
        return (f"[sub-agent result; {result.tokens_used} tokens, "
                f"{result.iterations_used} iters]\n{result.summary}")

    return spawn_subagent
