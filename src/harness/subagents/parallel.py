from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .spawner import SubagentSpawner
from .subagent import SubagentResult, SubagentSpec


@dataclass
class ParallelSpawner:
    inner: SubagentSpawner

    async def spawn_all(
        self, specs: list[SubagentSpec], justification: str = "",
    ) -> list[SubagentResult]:
        """Run multiple sub-agents concurrently; wait for all; return results."""
        tasks = [
            asyncio.create_task(self.inner.spawn(spec, justification=justification))
            for spec in specs
        ]
        return await asyncio.gather(*tasks, return_exceptions=False)
