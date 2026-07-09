"""B2 tests (ADR-004): structured JSON logging. Fast — no infra."""
from __future__ import annotations

import json
import logging

from service.observability import JsonFormatter, configure_logging


def _record(**extra) -> logging.LogRecord:
    rec = logging.LogRecord("takeoff.worker", logging.INFO, __file__, 10, "takeoff.start",
                            None, None)
    for k, v in extra.items():
        setattr(rec, k, v)
    return rec


def test_json_formatter_emits_standard_and_extra_fields():
    out = json.loads(JsonFormatter().format(_record(job_id="J1", shard_index=2)))
    assert out["level"] == "INFO"
    assert out["logger"] == "takeoff.worker"
    assert out["msg"] == "takeoff.start"
    assert out["job_id"] == "J1"
    assert out["shard_index"] == 2
    assert "ts" in out


def test_json_formatter_includes_exception():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        rec = _record()
        rec.exc_info = sys.exc_info()
    out = json.loads(JsonFormatter().format(rec))
    assert "boom" in out["exc"]


def test_configure_logging_is_idempotent():
    configure_logging(json_enabled=True)
    n = len(logging.getLogger("takeoff").handlers)
    configure_logging(json_enabled=True)
    assert len(logging.getLogger("takeoff").handlers) == n   # no handler pile-up
    assert logging.getLogger("takeoff").propagate is False
