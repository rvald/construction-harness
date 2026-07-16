from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .spawner import SubagentSpawner
from .subagent import SubagentResult, SubagentSpec


@dataclass
class ParallelSpawner:
    inner: SubagentSpawner
    # Bound on concurrent sub-agents (hence concurrent provider calls) so a
    # wide fan-out doesn't stampede the provider's rate limit. gemini and codex
    # both cap fan-out; here it's a semaphore over the batch.
    max_parallel: int = 4

    async def spawn_all(
        self, specs: list[SubagentSpec], justification: str = "",
    ) -> list[SubagentResult]:
        """Run multiple sub-agents concurrently; wait for all; return results
        in the order of `specs`."""
        # One write-gate for the whole sibling batch: any mutating tool call in
        # any sub-agent serializes on it, so concurrent writes can't interleave
        # mid-operation. Read-only calls never take it, so reads still overlap.
        write_gate = asyncio.Lock()
        sem = asyncio.Semaphore(self.max_parallel)

        async def run(spec: SubagentSpec) -> SubagentResult:
            async with sem:
                return await self.inner.spawn(
                    spec, justification=justification, write_gate=write_gate,
                )

        # return_exceptions=True so one sibling's failure surfaces as its own
        # error result instead of cancelling the rest of the in-flight batch.
        results = await asyncio.gather(
            *(run(spec) for spec in specs), return_exceptions=True,
        )
        return [
            r if isinstance(r, SubagentResult)
            else SubagentResult(
                summary="", tokens_used=0, iterations_used=0, error=str(r),
            )
            for r in results
        ]
