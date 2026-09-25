"""add games.stats_final

Marks games whose stored box score was taken after the game ended, so a game whose stats were
captured mid-game (live refresh) is fetched again once it is final. Games that are already final
and have stats were loaded by the ingest jobs from a finished game, so they start out true.

Revision ID: a41c9d0e7b52
Revises: 892e3e12195c
Create Date: 2026-09-25 13:10:00.000000
"""
import sqlalchemy as sa

from alembic import op

revision = "a41c9d0e7b52"
down_revision = "892e3e12195c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "games",
        sa.Column("stats_final", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.execute(
        "UPDATE games SET stats_final = true WHERE status = 'final' AND ("
        "EXISTS (SELECT 1 FROM player_game_stats s WHERE s.game_id = games.id) OR "
        "EXISTS (SELECT 1 FROM player_game_stats_nfl s WHERE s.game_id = games.id))"
    )


def downgrade() -> None:
    op.drop_column("games", "stats_final")
