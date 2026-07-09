"""A2 dedup tests (ADR-004). Drives _submit against real Postgres (the partial unique indexes
are the point) with storage/queue stubbed. Marked integration; memory-light."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from service import storage
from service.api import ingestions
from service.api.ingestions import _config_hash, _submit
from service.db import session_scope
from service.errors import ApiError
from service.models import STATUS_FAILED, TakeoffJob
from service.schemas import TakeoffConfigIn

pytestmark = pytest.mark.integration

DATA = b"%PDF-1.4 test"


@pytest.fixture(autouse=True)
def stub_io(monkeypatch):
    monkeypatch.setattr(storage, "put_bytes", lambda k, d, ct: k)

    class _Q:
        def enqueue(self, *a, **k):
            return None

    monkeypatch.setattr(ingestions, "get_queue", lambda: _Q())


def _sha() -> str:
    return uuid.uuid4().hex + uuid.uuid4().hex   # unique 64-char content hash


def _cfg(**kw) -> dict:
    return TakeoffConfigIn(**kw).model_dump()


def _key() -> str:
    return "k-" + uuid.uuid4().hex


def test_new_then_dedup_same_content_config():
    sha, cfg = _sha(), _cfg()
    jid, st, created = _submit(sha, DATA, cfg, None)
    assert created is True and st == "queued"
    jid2, _, created2 = _submit(sha, DATA, cfg, None)
    assert created2 is False and jid2 == jid          # same job, no re-run


def test_different_config_is_a_new_job():
    sha = _sha()
    jid, _, c1 = _submit(sha, DATA, _cfg(), None)
    jid2, _, c2 = _submit(sha, DATA, _cfg(min_tags=5), None)
    assert c1 and c2 and jid2 != jid


def test_idempotency_key_replay():
    sha, cfg, key = _sha(), _cfg(), _key()
    jid, _, c1 = _submit(sha, DATA, cfg, key)
    jid2, _, c2 = _submit(sha, DATA, cfg, key)
    assert c1 and c2 is False and jid2 == jid


def test_idempotency_key_conflict():
    key = _key()
    _submit(_sha(), DATA, _cfg(), key)
    with pytest.raises(ApiError) as ei:
        _submit(_sha(), DATA, _cfg(), key)            # same key, different content
    assert ei.value.status_code == 409


def test_failed_job_can_be_superseded():
    sha, cfg = _sha(), _cfg()
    jid, _, c1 = _submit(sha, DATA, cfg, None)
    with session_scope() as s:
        s.get(TakeoffJob, jid).status = STATUS_FAILED
    jid2, _, c2 = _submit(sha, DATA, cfg, None)
    assert c1 and c2 and jid2 != jid                  # failed job is superseded, not deduped


def test_active_partial_unique_index_enforced():
    sha, cfg = _sha(), _cfg()
    h = _config_hash(cfg)

    def _row():
        return TakeoffJob(id=str(uuid.uuid4()), content_sha256=sha, config=cfg, config_hash=h,
                          status="queued", pdf_object_key="k", entity_schema_version="1.0.0")

    with session_scope() as s:
        s.add(_row())
    with pytest.raises(IntegrityError):
        with session_scope() as s:
            s.add(_row())                             # second ACTIVE (content, config) rejected
