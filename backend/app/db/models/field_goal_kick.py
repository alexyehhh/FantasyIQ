"""
FieldGoalKick model.

One row per field goal attempt, with its distance. Fantasy leagues score kickers
by distance bracket (a 52-yard make is worth more than a 24-yard one, and a miss
from 25 costs more than a miss from 55) and every league draws the brackets
differently. Storing the raw distance keeps those brackets in the scoring config
instead of baked into columns. The per-game made/attempted totals on
PlayerGameStatsNFL stay as they are.

`external_play_id` (ESPN's play id) is the unique key ingestion upserts against,
so re-running a game never duplicates a kick.
"""

from datetime import datetime

from sqlalchemy import ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FieldGoalKick(Base):
    __tablename__ = "field_goal_kicks"
    __table_args__ = (
        UniqueConstraint("external_play_id", name="uq_field_goal_kick_play"),
        Index("ix_field_goal_kicks_player_game", "player_id", "game_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), nullable=False)
    external_play_id: Mapped[str] = mapped_column(nullable=False)

    distance: Mapped[int] = mapped_column(nullable=False)
    # "made" | "missed" | "blocked"
    result: Mapped[str] = mapped_column(nullable=False)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
