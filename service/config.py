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

    # --- sharding (ADR-002) ---
    # A shard's peak memory ~= mb_per_candidate * (candidates in its window); measured
    # ~96 MB/candidate for pdfplumber. The candidate cap per shard is derived so peak RSS
    # stays under the budget. Below the cap, a set runs as a single (unsharded) job.
    shard_memory_budget_mb: int = 3000
    mb_per_candidate: int = 96

    # per-shard reliability: total attempts (1 initial + retries) and the RQ backoff between
    # them. When a shard exhausts its attempts it is marked dead and the job still reduces on
    # the surviving shards, flagging the artifact incomplete (degrade-and-flag), never hangs.
    max_shard_attempts: int = 3
    shard_retry_backoff_seconds: int = 10

    # --- queue ---
    rq_queue_name: str = "takeoff"

    # --- observability ---
    log_level: str = "INFO"
    log_json: bool = True

    @property
    def max_candidates_per_shard(self) -> int:
        return max(1, self.shard_memory_budget_mb // self.mb_per_candidate)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
