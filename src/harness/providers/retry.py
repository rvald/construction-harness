from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


class RetryBudgetExceeded(Exception):
    pass


@dataclass
class RetryPolicy:
    max_attempts: int = 5
    base_delay: float = 1.0
    max_delay: float = 30.0
    max_total_seconds: float = 120.0
    retryable_statuses: frozenset[int] = frozenset({429, 500, 502, 503, 504})

    async def run(self, fn: Callable[[], Awaitable[Any]]) -> Any:
        start = asyncio.get_event_loop().time()
        last_exception: Exception | None = None

        for attempt in range(self.max_attempts):
            try:
                return await fn()
            except Exception as e:
                last_exception = e
                if not self._retryable(e):
                    raise
                elapsed = asyncio.get_event_loop().time() - start
                if elapsed >= self.max_total_seconds:
                    raise RetryBudgetExceeded(
                        f"retry budget ({self.max_total_seconds}s) exceeded"
                    ) from e
                delay = self._delay(attempt, e)
                await asyncio.sleep(delay)

        raise RetryBudgetExceeded(
            f"exhausted {self.max_attempts} attempts"
        ) from last_exception

    def _retryable(self, e: Exception) -> bool:
        status = getattr(e, "status_code", None)
        if status is None:
            # treat connection-level failures as retryable
            return isinstance(e, (ConnectionError, TimeoutError,
                                   asyncio.TimeoutError))
        return status in self.retryable_statuses

    def _delay(self, attempt: int, error: Exception) -> float:
        retry_after = getattr(error, "retry_after", None)
        if retry_after is not None:
            return float(retry_after)
        jitter = random.uniform(0, self.base_delay)
        return min(self.base_delay * (2 ** attempt) + jitter, self.max_delay)
