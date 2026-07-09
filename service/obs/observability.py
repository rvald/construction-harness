"""Structured logging for the service (ADR-004 B2).

A JSON formatter that emits the standard fields plus whatever `extra={...}` a call site
attached (job_id, request_id, shard_index, timing, ...). `configure_logging` wires it onto
the `takeoff` logger namespace, idempotently, with level/format from env
(TAKEOFF_LOG_LEVEL, TAKEOFF_LOG_JSON). Never log document contents or secrets (guardrail).
"""
from __future__ import annotations

import json
import logging

from service.core.config import settings

# Attributes present on a bare LogRecord — everything else is a call-site `extra` field.
_STD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STD_ATTRS and not key.startswith("_"):
                out[key] = value
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def configure_logging(level: str | None = None, json_enabled: bool | None = None) -> None:
    """Attach a single handler to the `takeoff` logger. Idempotent (replaces its own handler),
    so calling it from both the API and the worker process is safe."""
    level = level or settings.log_level
    json_enabled = settings.log_json if json_enabled is None else json_enabled

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter() if json_enabled
                         else logging.Formatter("%(levelname)s %(name)s %(message)s"))

    logger = logging.getLogger("takeoff")
    logger.handlers.clear()          # idempotent: no handler pile-up on re-config
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False         # don't double-emit through uvicorn/root
