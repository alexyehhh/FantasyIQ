"""projection snapshots: make origin part of the unique key

A live snapshot and a backtest replay of the same player-game can share a timestamp, so the unique
constraint has to tell them apart.

Revision ID: e5b1c7a4d802
Revises: d3a8f1c2b9e4
Create Date: 2026-10-01 10:00:00.000000
"""
from alembic import op

revision = "e5b1c7a4d802"
down_revision = "d3a8f1c2b9e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_projection_snapshot", "projection_snapshots", type_="unique")
    op.create_unique_constraint(
        "uq_projection_snapshot",
        "projection_snapshots",
        ["source", "kind", "entity_id", "game_id", "origin", "captured_at"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_projection_snapshot", "projection_snapshots", type_="unique")
    op.create_unique_constraint(
        "uq_projection_snapshot",
        "projection_snapshots",
        ["source", "kind", "entity_id", "game_id", "captured_at"],
    )
