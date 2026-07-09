"""dedup: partial unique indexes for work-dedup + idempotency-key (ADR-004 A2)

Revision ID: 0004_dedup
Revises: 0003_entities
Create Date: 2026-07-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_dedup"
down_revision = "0003_entities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Work dedup: at most one ACTIVE job per (content, config). A failed/dead job is excluded,
    # so a fresh submit can supersede it.
    op.create_index(
        "uq_takeoff_jobs_active_content_config", "takeoff_jobs",
        ["content_sha256", "config_hash"], unique=True,
        postgresql_where=sa.text("status NOT IN ('failed', 'dead')"),
    )
    # Request dedup: a client Idempotency-Key is unique (partial so multiple NULLs are allowed).
    op.create_index(
        "uq_takeoff_jobs_idempotency_key", "takeoff_jobs", ["idempotency_key"], unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_takeoff_jobs_idempotency_key", table_name="takeoff_jobs")
    op.drop_index("uq_takeoff_jobs_active_content_config", table_name="takeoff_jobs")
