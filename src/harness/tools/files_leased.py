
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from ..coordination.lease import Lease, LeaseManager
from .base import Tool
from .decorator import async_tool


def leased_file_tools(mgr: LeaseManager, holder: str) -> list[Tool]:

    @async_tool(side_effects={"write"})
    async def acquire_file_lease(path: str, ttl_seconds: int = 60) -> str:
        """Acquire an exclusive write-lease on a file.

        path: the file you intend to modify.
        ttl_seconds: how long to hold the lease before auto-expiry.

        Returns a lease token to include in subsequent edit calls.
        If another agent holds a lease on the same file, returns an
        error; wait and retry, or choose a different approach.
        """
        try:
            lease = await mgr.acquire(
                path, holder, ttl=timedelta(seconds=ttl_seconds)
            )
            return f"token={lease.token} (expires in {ttl_seconds}s)"
        except Exception as e:
            return f"could not acquire lease: {e}"

    @async_tool(side_effects={"write"})
    async def edit_lines_leased(
        path: str, start_line: int, end_line: int,
        replacement: str, lease_token: str,
    ) -> str:
        """Replace a line range, verifying a lease token for the file.

        lease_token: obtained from acquire_file_lease. Required.
        Other args: see edit_lines.
        """
        ok = await mgr.check(path, lease_token)
        if not ok:
            return f"edit rejected: lease for {path} is invalid or expired"
        from .files import edit_lines
        return edit_lines.run(path=path, start_line=start_line,
                               end_line=end_line, replacement=replacement)

    return [acquire_file_lease, edit_lines_leased]
