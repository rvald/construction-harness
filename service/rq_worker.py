"""Worker entrypoint: configure structured logging, then run the RQ worker (ADR-004 B2).

Replaces the bare `rq worker takeoff` CLI so the worker process gets the JSON formatter +
level from env before it starts pulling jobs. Run: `python -m service.rq_worker`.
"""
from __future__ import annotations

from rq import Queue, Worker

from service.config import settings
from service.observability import configure_logging
from service.queue import redis_conn


def main() -> None:
    configure_logging()
    conn = redis_conn()
    Worker([Queue(settings.rq_queue_name, connection=conn)], connection=conn).work()


if __name__ == "__main__":
    main()
