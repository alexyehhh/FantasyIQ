"""add news_items and gemini_calls

ESPN news articles kept so Gemini reads each once, and a log of Gemini requests so the rate limits
hold across restarts (see app/db/models/news.py). Additive.

Revision ID: f1c4a9d27b53
Revises: e5b1c7a4d802
Create Date: 2026-10-02 20:00:00.000000
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "f1c4a9d27b53"
down_revision = "e5b1c7a4d802"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "news_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sport", sa.String(length=10), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=False),
        sa.Column("player_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("facts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
    )
    op.create_index(
        "ix_news_items_status_published", "news_items", ["status", "published_at"]
    )
    op.create_table(
        "gemini_calls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("purpose", sa.String(length=30), nullable=False),
        sa.Column("called_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gemini_calls_model_called_at", "gemini_calls", ["model", "called_at"])


def downgrade() -> None:
    op.drop_index("ix_gemini_calls_model_called_at", table_name="gemini_calls")
    op.drop_table("gemini_calls")
    op.drop_index("ix_news_items_status_published", table_name="news_items")
    op.drop_table("news_items")
