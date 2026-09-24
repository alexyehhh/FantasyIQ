"""add player directory, injury and game score columns

All columns are additive and nullable: filled by data_pipeline/espn_directory.py
and the game ingestion jobs, so existing rows stay valid until the next sync.

Also namespaces teams.external_id by sport ("nba:1"): ESPN numbers teams per
league, so the NBA's and NFL's Atlanta were both "1" and collided on the
table-wide unique constraint.

Revision ID: c5b5c4e8c035
Revises: 457ab4cd6e57
Create Date: 2026-09-23 17:37:24.340874
"""
import sqlalchemy as sa

from alembic import op

revision = "c5b5c4e8c035"
down_revision = "457ab4cd6e57"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("games", sa.Column("home_score", sa.Integer(), nullable=True))
    op.add_column("games", sa.Column("away_score", sa.Integer(), nullable=True))
    op.add_column("players", sa.Column("headshot_url", sa.String(length=255), nullable=True))
    op.add_column("players", sa.Column("height_inches", sa.Integer(), nullable=True))
    op.add_column("players", sa.Column("weight_lbs", sa.Integer(), nullable=True))
    op.add_column("players", sa.Column("birth_date", sa.Date(), nullable=True))
    op.add_column("players", sa.Column("college", sa.String(length=100), nullable=True))
    op.add_column("players", sa.Column("experience_years", sa.Integer(), nullable=True))
    op.add_column("players", sa.Column("injury_status", sa.String(length=30), nullable=True))
    op.add_column("players", sa.Column("injury_type", sa.String(length=50), nullable=True))
    op.add_column("players", sa.Column("injury_note", sa.Text(), nullable=True))
    op.add_column("players", sa.Column("injury_updated_at", sa.DateTime(), nullable=True))
    op.add_column("teams", sa.Column("logo_url", sa.String(length=255), nullable=True))
    op.add_column("teams", sa.Column("primary_color", sa.String(length=7), nullable=True))
    op.execute(
        "UPDATE teams SET external_id = lower(sport) || ':' || external_id "
        "WHERE external_id IS NOT NULL AND external_id NOT LIKE '%:%'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE teams SET external_id = split_part(external_id, ':', 2) "
        "WHERE external_id LIKE '%:%'"
    )
    op.drop_column("teams", "primary_color")
    op.drop_column("teams", "logo_url")
    op.drop_column("players", "injury_updated_at")
    op.drop_column("players", "injury_note")
    op.drop_column("players", "injury_type")
    op.drop_column("players", "injury_status")
    op.drop_column("players", "experience_years")
    op.drop_column("players", "college")
    op.drop_column("players", "birth_date")
    op.drop_column("players", "weight_lbs")
    op.drop_column("players", "height_inches")
    op.drop_column("players", "headshot_url")
    op.drop_column("games", "away_score")
    op.drop_column("games", "home_score")
