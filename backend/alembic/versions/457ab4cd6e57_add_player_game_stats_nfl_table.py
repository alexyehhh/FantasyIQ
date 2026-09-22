"""add player_game_stats_nfl table

Revision ID: 457ab4cd6e57
Revises: 2f16bc7c4f35
Create Date: 2026-09-22 23:50:05.432287
"""

import sqlalchemy as sa

from alembic import op

revision = "457ab4cd6e57"
down_revision = "2f16bc7c4f35"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "player_game_stats_nfl",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("passing_completions", sa.Integer(), nullable=False),
        sa.Column("passing_attempts", sa.Integer(), nullable=False),
        sa.Column("passing_yards", sa.Integer(), nullable=False),
        sa.Column("passing_touchdowns", sa.Integer(), nullable=False),
        sa.Column("interceptions", sa.Integer(), nullable=False),
        sa.Column("rushing_attempts", sa.Integer(), nullable=False),
        sa.Column("rushing_yards", sa.Integer(), nullable=False),
        sa.Column("rushing_touchdowns", sa.Integer(), nullable=False),
        sa.Column("receptions", sa.Integer(), nullable=False),
        sa.Column("receiving_targets", sa.Integer(), nullable=False),
        sa.Column("receiving_yards", sa.Integer(), nullable=False),
        sa.Column("receiving_touchdowns", sa.Integer(), nullable=False),
        sa.Column("fumbles_lost", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["game_id"],
            ["games.id"],
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("player_id", "game_id", name="uq_player_game_nfl"),
    )


def downgrade() -> None:
    op.drop_table("player_game_stats_nfl")
