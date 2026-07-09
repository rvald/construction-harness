"""Streaming-upload tests: chunked hash/validate is correct, bounded, and rewinds; and the
storage streaming path round-trips against MinIO (ADR-004 gap)."""
from __future__ import annotations

import hashlib
import io
import uuid

import pytest

from service.api.ingestions import _hash_and_validate
from service.errors import ApiError


def test_hash_and_validate_ok():
    data = b"%PDF-1.4\n" + b"x" * 5000
    sha, size = _hash_and_validate(io.BytesIO(data), 10_000_000)
    assert sha == hashlib.sha256(data).hexdigest()      # streaming hash == full-file hash
    assert size == len(data)


def test_rewinds_for_subsequent_upload():
    b = io.BytesIO(b"%PDF-1.4 test")
    _hash_and_validate(b, 1_000_000)
    assert b.tell() == 0


def test_rejects_non_pdf():
    with pytest.raises(ApiError) as ei:
        _hash_and_validate(io.BytesIO(b"nope" * 10), 1_000_000)
    assert ei.value.status_code == 415


def test_rejects_empty():
    with pytest.raises(ApiError) as ei:
        _hash_and_validate(io.BytesIO(b""), 1_000_000)
    assert ei.value.status_code == 400


def test_rejects_oversize_midstream():
    with pytest.raises(ApiError) as ei:
        _hash_and_validate(io.BytesIO(b"%PDF-" + b"x" * 100), 50)
    assert ei.value.status_code == 413


@pytest.mark.integration
def test_upload_fileobj_roundtrip_minio():
    from service import storage
    storage.ensure_bucket()
    key = f"test/{uuid.uuid4()}.pdf"
    storage.upload_fileobj(key, io.BytesIO(b"%PDF-hello"), "application/pdf")
    assert storage.get_bytes(key) == b"%PDF-hello"
    storage.delete(key)
