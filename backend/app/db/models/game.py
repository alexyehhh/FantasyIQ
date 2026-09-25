"""
Game model.

One row per real-world game, referenced by both teams playing and by
every PlayerGameStats row for that game.
"""

from datetime import datetime

from sqlalchemy import ForeignKey, String, false, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    sport: Mapped[str] = mapped_column(String(10), nullable=False)  # "NBA" | "NFL"
    season: Mapped[str] = mapped_column(String(10), nullable=False)  # e.g. "2025-26"
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    start_time: Mapped[datetime] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="scheduled"
    )  # scheduled | in_progress | final
    week: Mapped[int | None] = mapped_column(nullable=True)  # NFL regular-season week
    home_score: Mapped[int | None] = mapped_column(nullable=True)
    away_score: Mapped[int | None] = mapped_column(nullable=True)
    # True once a box score taken after the game ended has been stored. The schedule sync can mark
    # a game final without touching its stats, so `status` alone can't say the stats are complete.
    stats_final: Mapped[bool] = mapped_column(default=False, server_default=false())

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
