"""add team game stats nfl table

One row per team per game with the stats a fantasy team defense is scored on.

Revision ID: 892e3e12195c
Revises: e0ef64cc2e54
Create Date: 2026-09-24 22:06:40.806161
"""

import sqlalchemy as sa

from alembic import op

revision = "892e3e12195c"
down_revision = "e0ef64cc2e54"
branch_labels = None
depends_on = None

STAT_COLUMNS = [
    "sacks",
    "interceptions",
    "fumble_recoveries",
    "safeties",
    "blocked_kicks",
    "defensive_touchdowns",
    "return_touchdowns",
    "fourth_down_stops",
    "points_allowed",
    "yards_allowed",
]


def upgrade() -> None:
    op.create_table(
        "team_game_stats_nfl",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        *[sa.Column(name, sa.Integer(), nullable=False) for name in STAT_COLUMNS],
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id", "game_id", name="uq_team_game_nfl"),
    )


def downgrade() -> None:
    op.drop_table("team_game_stats_nfl")
