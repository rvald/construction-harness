from __future__ import annotations

from ..permissions.manager import PermissionManager
from ..providers.base import Provider
from ..tools.base import Tool
from ..tools.selector import ToolCatalog
from .parallel import ParallelSpawner
from .parallel_tool import spawn_parallel_tool
from .spawn_tool import spawn_tool
from .spawner import SubagentSpawner


def subagent_tools(
    provider: Provider,
    catalog: ToolCatalog,
    permission_manager: PermissionManager | None = None,
    max_subagents_per_session: int = 5,
    max_parallel: int = 4,
) -> list[Tool]:
    """Build the delegation tools a parent agent uses to spawn sub-agents.

    Add the returned tools to the PARENT catalog; the loop then offers them
    with no change to `arun`. This is the single place the sub-agent machinery
    is wired together, so the isolation guarantees hold by construction:

      * context isolation — each sub-agent runs `arun` with a fresh transcript
        and its own context budget (see SubagentSpawner.spawn);
      * tool isolation — each gets a catalog restricted to `tools_allowed`,
        minus the delegation tools, so it cannot recurse;
      * permission inheritance — `permission_manager` is threaded into every
        sub-agent, fail-closed in headless (an "ask" downgrades to "deny");
      * shared-state safety — parallel siblings share one write-gate, so their
        mutating tool calls serialize instead of interleaving.

    `provider` and `catalog` are the PARENT's; the spawner narrows the catalog
    per sub-agent. `max_subagents_per_session` caps total spawns; `max_parallel`
    caps how many run at once in one `spawn_parallel_subagents` call.
    """
    spawner = SubagentSpawner(
        provider=provider,
        catalog=catalog,
        max_subagents_per_session=max_subagents_per_session,
        permission_manager=permission_manager,
    )
    parallel = ParallelSpawner(inner=spawner, max_parallel=max_parallel)
    return [spawn_tool(spawner), spawn_parallel_tool(parallel)]
