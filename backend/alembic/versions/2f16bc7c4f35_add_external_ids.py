"""add provider external ids for ingestion upserts

Revision ID: 2f16bc7c4f35
Revises: 7acb05c31b81
"""

from alembic import op
import sqlalchemy as sa


revision = "2f16bc7c4f35"
down_revision = "7acb05c31b81"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("teams", sa.Column("external_id", sa.String(length=64), nullable=True))
    op.add_column("players", sa.Column("external_id", sa.String(length=64), nullable=True))
    op.add_column("games", sa.Column("external_id", sa.String(length=64), nullable=True))
    op.create_unique_constraint("uq_teams_external_id", "teams", ["external_id"])
    op.create_unique_constraint("uq_players_external_id", "players", ["external_id"])
    op.create_unique_constraint("uq_games_external_id", "games", ["external_id"])


def downgrade() -> None:
    op.drop_constraint("uq_games_external_id", "games", type_="unique")
    op.drop_constraint("uq_players_external_id", "players", type_="unique")
    op.drop_constraint("uq_teams_external_id", "teams", type_="unique")
    op.drop_column("games", "external_id")
    op.drop_column("players", "external_id")
    op.drop_column("teams", "external_id")
