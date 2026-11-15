"""Persist prepared terrain datasets and display regions.

Revision ID: 0003_stage4_terrain_registry
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_stage4_terrain_registry"
down_revision = "0002_stage3_timeline_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "terrain_datasets",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("product_version", sa.String()),
        sa.Column("source_url", sa.String(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("asset_path", sa.String(), nullable=False),
        sa.Column("processing_version", sa.String(), nullable=False),
        sa.Column("resolution_m", sa.Float(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attribution", sa.String(), nullable=False),
        sa.Column("ready", sa.Integer(), nullable=False),
        sa.CheckConstraint("length(sha256) = 64"),
        sa.CheckConstraint("resolution_m > 0"),
        sa.CheckConstraint("ready IN (0,1)"),
    )
    op.create_table(
        "terrain_regions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("dataset_id", sa.String(), sa.ForeignKey("terrain_datasets.id")),
        sa.Column("origin_latitude", sa.Float(), nullable=False),
        sa.Column("origin_longitude", sa.Float(), nullable=False),
        sa.Column("spacing_m", sa.Float(), nullable=False),
        sa.Column("grid_half_extent_m", sa.Float(), nullable=False),
        sa.CheckConstraint("origin_latitude >= -90 AND origin_latitude <= 90"),
        sa.CheckConstraint("origin_longitude >= -180 AND origin_longitude < 180"),
        sa.CheckConstraint("spacing_m > 0"),
        sa.CheckConstraint("grid_half_extent_m > 0"),
    )
    op.create_index("ix_terrain_regions_dataset", "terrain_regions", ["dataset_id"])
    op.execute(
        "UPDATE sites SET terrain_region_id = 'shackleton-connecting-ridge' "
        "WHERE id = 'shackleton-connecting-ridge'"
    )
    op.execute("UPDATE sites SET terrain_region_id = 'faustini-rim-a' WHERE id = 'faustini-rim-a'")


def downgrade():
    op.execute(
        "UPDATE sites SET terrain_region_id = NULL "
        "WHERE id = 'shackleton-connecting-ridge' "
        "AND terrain_region_id = 'shackleton-connecting-ridge'"
    )
    op.execute(
        "UPDATE sites SET terrain_region_id = NULL "
        "WHERE id = 'faustini-rim-a' AND terrain_region_id = 'faustini-rim-a'"
    )
    op.drop_index("ix_terrain_regions_dataset", table_name="terrain_regions")
    op.drop_table("terrain_regions")
    op.drop_table("terrain_datasets")
