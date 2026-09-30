"""add projection_snapshots

What each projection source said about a player or team defense before a game was played, saved by
the worker so its accuracy can be scored against the real result later (see
app/db/models/projection_snapshot.py). Additive.

Revision ID: d3a8f1c2b9e4
Revises: b7d2e4f19a36
Create Date: 2026-09-30 18:00:00.000000
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "d3a8f1c2b9e4"
down_revision = "b7d2e4f19a36"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projection_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("sport", sa.String(length=10), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(length=10), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("kicks", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source", "kind", "entity_id", "game_id", "captured_at", name="uq_projection_snapshot"
        ),
    )
    op.create_index(
        "ix_projection_snapshots_game_source", "projection_snapshots", ["game_id", "source"]
    )


def downgrade() -> None:
    op.drop_index("ix_projection_snapshots_game_source", table_name="projection_snapshots")
    op.drop_table("projection_snapshots")
