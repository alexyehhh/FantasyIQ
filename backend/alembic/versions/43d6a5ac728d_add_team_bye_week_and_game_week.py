"""add team bye week and game week

Nullable and NFL-only: filled by data_pipeline/espn_directory.py on the next sync.

Revision ID: 43d6a5ac728d
Revises: c5b5c4e8c035
Create Date: 2026-09-23 18:15:39.706497
"""
import sqlalchemy as sa

from alembic import op

revision = "43d6a5ac728d"
down_revision = "c5b5c4e8c035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("games", sa.Column("week", sa.Integer(), nullable=True))
    op.add_column("teams", sa.Column("bye_week", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("teams", "bye_week")
    op.drop_column("games", "week")
