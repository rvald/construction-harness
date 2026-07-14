from ..tools.base import Tool
from ..tools.decorator import async_tool
from .parallel import ParallelSpawner
from .subagent import SubagentSpec


def spawn_parallel_tool(spawner: ParallelSpawner) -> Tool:

    @async_tool(side_effects={"mutate"})
    async def spawn_parallel_subagents(
        objectives: list[str],
        output_format: str,
        tools_allowed: list[str],
        justification: str,
    ) -> str:
        """Spawn multiple sub-agents concurrently.

        objectives: list of distinct, non-overlapping objectives. Each
                    sub-agent handles one. Do not pass the same objective
                    twice.
        output_format: format ALL sub-agents use; the parent synthesizes
                       across parallel results, so they must be comparable.
        tools_allowed: same list for all sub-agents.
        justification: why parallel is better than sequential here.
                       Required.

        Returns a newline-separated, indexed list of sub-agent summaries.
        Do not use this for tasks where one sub-agent's output is input
        to the next — those need sequential spawn_subagent.
        """
        if not justification:
            return "error: justification required"
        if len(objectives) < 2:
            return "error: use spawn_subagent for a single objective"
        if len(set(objectives)) != len(objectives):
            return "error: objectives must be distinct (no duplicates)"

        specs = [
            SubagentSpec(
                objective=obj, output_format=output_format,
                tools_allowed=tools_allowed,
            )
            for obj in objectives
        ]
        results = await spawner.spawn_all(specs, justification)
        lines = []
        for i, r in enumerate(results, start=1):
            lines.append(f"--- sub-agent {i} ---")
            if r.error:
                lines.append(f"error: {r.error}")
            else:
                lines.append(r.summary)
        return "\n".join(lines)

    return spawn_parallel_subagents
