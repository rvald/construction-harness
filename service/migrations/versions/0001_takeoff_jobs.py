"""takeoff_jobs

Revision ID: 0001_takeoff_jobs
Revises:
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_takeoff_jobs"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "takeoff_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("idempotency_key", sa.String(length=255)),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", postgresql.JSONB()),
        sa.Column("pdf_object_key", sa.String(length=512), nullable=False),
        sa.Column("artifact_object_key", sa.String(length=512)),
        sa.Column("manifest", postgresql.JSONB()),
        sa.Column("entity_schema_version", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_takeoff_jobs_idempotency_key", "takeoff_jobs", ["idempotency_key"])
    op.create_index("ix_takeoff_jobs_content_sha256", "takeoff_jobs", ["content_sha256"])
    op.create_index("ix_takeoff_jobs_status", "takeoff_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_takeoff_jobs_status", table_name="takeoff_jobs")
    op.drop_index("ix_takeoff_jobs_content_sha256", table_name="takeoff_jobs")
    op.drop_index("ix_takeoff_jobs_idempotency_key", table_name="takeoff_jobs")
    op.drop_table("takeoff_jobs")
