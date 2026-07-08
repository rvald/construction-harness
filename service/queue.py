"""RQ queue wiring. Redis is the broker; workers run the takeoff build synchronously."""
from __future__ import annotations

from redis import Redis
from rq import Queue

from service.config import settings

_redis: Redis | None = None


def redis_conn() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url)
    return _redis


def get_queue() -> Queue:
    return Queue(settings.rq_queue_name, connection=redis_conn())
