"""widen player game stats for kicking, returns and shooting splits

Adds the box-score stats that custom fantasy scoring needs and that ESPN reports
as structured data: NBA made shots and free throws, NFL kicking and return
touchdowns. Rows loaded before this migration read 0 for the new columns until
their games are re-ingested (ingestion upserts, so re-running a game is safe).

Revision ID: 6282a01bcfe0
Revises: 43d6a5ac728d
Create Date: 2026-09-24 21:33:51.736752
"""

import sqlalchemy as sa

from alembic import op

revision = "6282a01bcfe0"
down_revision = "43d6a5ac728d"
branch_labels = None
depends_on = None

NEW_COLUMNS: dict[str, list[str]] = {
    "player_game_stats": [
        "field_goals_made",
        "three_pointers_made",
        "free_throws_made",
        "free_throw_attempts",
    ],
    "player_game_stats_nfl": [
        "field_goals_made",
        "field_goal_attempts",
        "extra_points_made",
        "extra_point_attempts",
        "kick_return_touchdowns",
        "punt_return_touchdowns",
    ],
}


def upgrade() -> None:
    # The temporary server default lets NOT NULL columns be added to populated tables;
    # it is dropped again so the tables match the models (which default in Python).
    for table, columns in NEW_COLUMNS.items():
        for column in columns:
            op.add_column(
                table,
                sa.Column(column, sa.Integer(), nullable=False, server_default="0"),
            )
            op.alter_column(table, column, server_default=None)


def downgrade() -> None:
    for table, columns in NEW_COLUMNS.items():
        for column in reversed(columns):
            op.drop_column(table, column)
