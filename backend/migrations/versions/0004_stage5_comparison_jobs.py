"""Allow durable comparison jobs.

Revision ID: 0004_stage5_comparison_jobs
"""

from alembic import op

revision = "0004_stage5_comparison_jobs"
down_revision = "0003_stage4_terrain_registry"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_observation_jobs_kind", "observation_jobs", type_="check")
    op.create_check_constraint(
        "ck_observation_jobs_kind",
        "observation_jobs",
        "kind IN ('now','timeline','comparison')",
    )


def downgrade():
    op.drop_constraint("ck_observation_jobs_kind", "observation_jobs", type_="check")
    op.create_check_constraint(
        "ck_observation_jobs_kind",
        "observation_jobs",
        "kind IN ('now','timeline')",
    )
