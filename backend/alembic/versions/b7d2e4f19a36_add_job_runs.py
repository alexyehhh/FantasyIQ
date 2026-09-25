"""add job_runs

State of the background worker's jobs (data_pipeline/worker.py): when each last ran and whether it
worked. Additive; the worker creates each job's row the first time it runs.

Revision ID: b7d2e4f19a36
Revises: a41c9d0e7b52
Create Date: 2026-09-25 15:00:00.000000
"""
import sqlalchemy as sa

from alembic import op

revision = "b7d2e4f19a36"
down_revision = "a41c9d0e7b52"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_runs",
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("job_runs")
