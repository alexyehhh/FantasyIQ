"""
NewsItem and GeminiCall models.

`NewsItem` is one ESPN news article about NFL players, kept so each is read by Gemini once: the
worker saves new ones (data_pipeline/espn_news.py) and then has Gemini turn the text into facts
about each tagged player (app/services/news/extract.py). `facts` holds those facts, and they
reach the projection model through app/services/projections/news.py.

`GeminiCall` is one request made to Gemini for that reading. The count of recent rows is how the
daily and per-minute limits are kept (app/ai/budget.py), so they hold across restarts.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# pending: not read yet; done: read (facts may be empty); skipped: never needs reading (no player
# tagged, or too old); failed: Gemini's answer couldn't be used after repeated tries.
NEWS_STATUSES = ("pending", "done", "skipped", "failed")


class NewsItem(Base):
    __tablename__ = "news_items"
    __table_args__ = (Index("ix_news_items_status_published", "status", "published_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sport: Mapped[str] = mapped_column(String(10), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="espn")
    # The source's own id for the article; unique, so an article is saved once.
    external_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    published_at: Mapped[datetime] = mapped_column(nullable=False)
    # players.id of the players the source tagged on the article.
    player_ids: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    # [{"player_id", "availability", "role", "about_next_game", "note"}, ...] once read.
    facts: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class GeminiCall(Base):
    __tablename__ = "gemini_calls"
    __table_args__ = (Index("ix_gemini_calls_model_called_at", "model", "called_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)
    called_at: Mapped[datetime] = mapped_column(nullable=False)
