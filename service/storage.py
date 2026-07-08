"""Object storage (MinIO / S3) for raw PDFs and generated artifacts.

boto3 with an explicit endpoint + path-style addressing so the same code talks to MinIO
locally and S3 in production. Credentials come from ``settings`` (env), never hardcoded.
"""
from __future__ import annotations

import boto3
from botocore.client import Config

from service.config import settings

_client = None


def client():
    """Process-wide boto3 S3 client (lazy singleton)."""
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
    return _client


def ensure_bucket() -> None:
    """Create the configured bucket if it does not exist (idempotent, local convenience)."""
    s3 = client()
    existing = {b["Name"] for b in s3.list_buckets().get("Buckets", [])}
    if settings.s3_bucket not in existing:
        s3.create_bucket(Bucket=settings.s3_bucket)


def put_bytes(key: str, data: bytes, content_type: str) -> str:
    client().put_object(Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type)
    return key


def get_bytes(key: str) -> bytes:
    return client().get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()


def download_to(key: str, dest_path) -> None:
    client().download_file(settings.s3_bucket, key, str(dest_path))


def ping() -> None:
    """Readiness probe: raises if the bucket is not reachable."""
    client().head_bucket(Bucket=settings.s3_bucket)
