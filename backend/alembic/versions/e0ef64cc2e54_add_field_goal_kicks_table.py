"""add field goal kicks table

One row per field goal attempt with its distance, so kickers can be scored by
distance bracket under any league's settings.

Revision ID: e0ef64cc2e54
Revises: 6282a01bcfe0
Create Date: 2026-09-24 21:54:30.975237
"""

import sqlalchemy as sa

from alembic import op

revision = "e0ef64cc2e54"
down_revision = "6282a01bcfe0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "field_goal_kicks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("external_play_id", sa.String(), nullable=False),
        sa.Column("distance", sa.Integer(), nullable=False),
        sa.Column("result", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_play_id", name="uq_field_goal_kick_play"),
    )
    op.create_index(
        "ix_field_goal_kicks_player_game",
        "field_goal_kicks",
        ["player_id", "game_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_field_goal_kicks_player_game", table_name="field_goal_kicks")
    op.drop_table("field_goal_kicks")
