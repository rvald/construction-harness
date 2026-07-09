"""B1 tests (ADR-004): the status response surfaces execution shape + partial-result flags
for both single and sharded jobs. PG-backed (needs a job row); memory-light."""
from __future__ import annotations

import uuid

import pytest

from service.api.ingestions import get_ingestion
from service.core.db import session_scope
from service.core.models import MODE_SHARDED, MODE_SINGLE, TakeoffJob
from service.takeoff.pipeline_adapter import ENTITY_SCHEMA_VERSION

pytestmark = pytest.mark.integration


def _job(**kw) -> str:
    jid = str(uuid.uuid4())
    defaults = dict(id=jid, content_sha256=uuid.uuid4().hex + uuid.uuid4().hex, config={},
                    config_hash=uuid.uuid4().hex, status="succeeded", pdf_object_key="k",
                    entity_schema_version=ENTITY_SCHEMA_VERSION)
    defaults.update(kw)
    with session_scope() as s:
        s.add(TakeoffJob(**defaults))
    return jid


def test_sharded_manifest_surfaced():
    jid = _job(mode=MODE_SHARDED, shard_count=3, manifest={
        "mode": "sharded", "shard_count": 3, "incomplete": True,
        "failed_shards": [{"shard_index": 1, "page_range": [53, 103], "error": {"type": "X"}}]})
    st = get_ingestion(jid)
    assert st.mode == "sharded"
    assert st.shard_count == 3
    assert st.incomplete is True
    assert [f["shard_index"] for f in st.failed_shards] == [1]


def test_single_job_defaults_and_run_manifest():
    jid = _job(mode=MODE_SINGLE, shard_count=0,
               manifest={"file_id": "drawings", "checksum": "abc", "timing": {"schedules": 10}})
    st = get_ingestion(jid)
    assert st.mode == "single"
    assert st.shard_count == 0
    assert st.incomplete is False
    assert st.failed_shards == []
    assert st.manifest.checksum == "abc"           # single-run manifest still surfaced
