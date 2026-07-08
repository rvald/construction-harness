"""12-factor configuration — every value comes from the environment.

No secrets in code or images; docker-compose injects them. Import ``settings`` for a
process-wide singleton.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TAKEOFF_", env_file=".env", extra="ignore")

    environment: str = "local"

    # --- stores ---
    database_url: str = "postgresql+psycopg://takeoff:takeoff@postgres:5432/takeoff"
    redis_url: str = "redis://redis:6379/0"

    # --- object storage (MinIO / S3) ---
    s3_endpoint_url: str | None = "http://minio:9000"
    s3_region: str = "us-east-1"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "takeoff"

    # --- limits ---
    max_upload_bytes: int = 500 * 1024 * 1024   # 500 MiB ceiling on an uploaded PDF
    job_timeout_seconds: int = 1200             # 20 min; the ~5-min build plus headroom

    # --- queue ---
    rq_queue_name: str = "takeoff"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
