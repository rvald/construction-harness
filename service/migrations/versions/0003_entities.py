"""entities: shredded schedule_items / room_areas / fixture_counts (ADR-003)

Revision ID: 0003_entities
Revises: 0002_sharding
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_entities"
down_revision = "0002_sharding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedule_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("schedule", sa.String(length=64), nullable=False),
        sa.Column("shape", sa.String(length=16), nullable=False),
        sa.Column("mark", sa.String(length=128), nullable=False),
        sa.Column("quantity", sa.Float()),
        sa.Column("unit", sa.String(length=16)),
        sa.Column("quantity_basis", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("attributes", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("src_file_id", sa.String(length=128)),
        sa.Column("src_page_index", sa.Integer()),
    )
    op.create_index("ix_schedule_items_job_id", "schedule_items", ["job_id"])
    op.create_index("ix_schedule_items_job_schedule", "schedule_items", ["job_id", "schedule"])
    op.create_index("ix_schedule_items_job_ordinal", "schedule_items", ["job_id", "ordinal"])

    op.create_table(
        "room_areas",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("room_number", sa.String(length=64), nullable=False),
        sa.Column("area_sf", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("basis", sa.String(length=64), nullable=False),
        sa.Column("src_file_id", sa.String(length=128)),
        sa.Column("src_page_index", sa.Integer()),
    )
    op.create_index("ix_room_areas_job_id", "room_areas", ["job_id"])
    op.create_index("ix_room_areas_job_ordinal", "room_areas", ["job_id", "ordinal"])

    op.create_table(
        "fixture_counts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("symbol_id", sa.String(length=64), nullable=False),
        sa.Column("sheet_page", sa.Integer(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("boxes", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.create_index("ix_fixture_counts_job_id", "fixture_counts", ["job_id"])
    op.create_index("ix_fixture_counts_job_symbol", "fixture_counts", ["job_id", "symbol_id"])
    op.create_index("ix_fixture_counts_job_ordinal", "fixture_counts", ["job_id", "ordinal"])


def downgrade() -> None:
    op.drop_table("fixture_counts")
    op.drop_table("room_areas")
    op.drop_table("schedule_items")
