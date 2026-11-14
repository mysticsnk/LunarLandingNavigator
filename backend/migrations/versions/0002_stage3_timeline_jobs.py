"""Allow durable timeline jobs.

Revision ID: 0002_stage3_timeline_jobs
"""

from alembic import op

revision = "0002_stage3_timeline_jobs"
down_revision = "0001_stage1"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("observation_jobs_kind_check", "observation_jobs", type_="check")
    op.create_check_constraint(
        "ck_observation_jobs_kind",
        "observation_jobs",
        "kind IN ('now','timeline')",
    )


def downgrade():
    op.drop_constraint("ck_observation_jobs_kind", "observation_jobs", type_="check")
    op.create_check_constraint("observation_jobs_kind_check", "observation_jobs", "kind = 'now'")
