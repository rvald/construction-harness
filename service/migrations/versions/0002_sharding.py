"""sharding: takeoff_jobs execution mode + takeoff_shards (ADR-002)

Revision ID: 0002_sharding
Revises: 0001_takeoff_jobs
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_sharding"
down_revision = "0001_takeoff_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("takeoff_jobs",
                  sa.Column("mode", sa.String(length=16), nullable=False, server_default="single"))
    op.add_column("takeoff_jobs",
                  sa.Column("shard_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("takeoff_jobs",
                  sa.Column("completed_shards", sa.Integer(), nullable=False, server_default="0"))

    op.create_table(
        "takeoff_shards",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("shard_index", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("partial_object_key", sa.String(length=512)),
        sa.Column("error", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_takeoff_shards_job_id", "takeoff_shards", ["job_id"])
    op.create_index("ix_takeoff_shards_status", "takeoff_shards", ["status"])


def downgrade() -> None:
    op.drop_index("ix_takeoff_shards_status", table_name="takeoff_shards")
    op.drop_index("ix_takeoff_shards_job_id", table_name="takeoff_shards")
    op.drop_table("takeoff_shards")
    op.drop_column("takeoff_jobs", "completed_shards")
    op.drop_column("takeoff_jobs", "shard_count")
    op.drop_column("takeoff_jobs", "mode")
