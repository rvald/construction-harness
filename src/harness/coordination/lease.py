from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4


@dataclass
class Lease:
    resource: str
    holder: str            # agent or sub-agent ID
    token: str             # unique lease token; required for ops on this resource
    expires_at: datetime


class LeaseConflict(Exception):
    pass


@dataclass
class LeaseManager:
    """Mediates exclusive access to named resources across concurrent agents."""

    _leases: dict[str, Lease] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def acquire(
        self, resource: str, holder: str, ttl: timedelta = timedelta(seconds=60)
    ) -> Lease:
        async with self._lock:
            existing = self._leases.get(resource)
            if existing is not None:
                if existing.expires_at > datetime.now(timezone.utc):
                    raise LeaseConflict(
                        f"resource {resource!r} held by {existing.holder!r}"
                    )
                # expired — reap
                del self._leases[resource]
            lease = Lease(
                resource=resource,
                holder=holder,
                token=str(uuid4()),
                expires_at=datetime.now(timezone.utc) + ttl,
            )
            self._leases[resource] = lease
            return lease

    async def release(self, lease: Lease) -> None:
        async with self._lock:
            existing = self._leases.get(lease.resource)
            if existing and existing.token == lease.token:
                del self._leases[lease.resource]

    async def renew(self, lease: Lease, ttl: timedelta = timedelta(seconds=60)) -> Lease:
        async with self._lock:
            existing = self._leases.get(lease.resource)
            if not existing or existing.token != lease.token:
                raise LeaseConflict("lease no longer valid")
            new_lease = Lease(
                resource=lease.resource, holder=lease.holder, token=lease.token,
                expires_at=datetime.now(timezone.utc) + ttl,
            )
            self._leases[lease.resource] = new_lease
            return new_lease

    async def check(self, resource: str, token: str) -> bool:
        async with self._lock:
            existing = self._leases.get(resource)
            return (existing is not None
                    and existing.token == token
                    and existing.expires_at > datetime.now(timezone.utc))
