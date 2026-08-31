"""
PlayerGameStats model.

One row per player per game. The unique constraint on
(player_id, game_id) is the actual enforcement mechanism behind the
SAD's "ingestion must be idempotent" principle: re-running an
ingestion job for a game that's already been loaded will hit this
constraint on insert, and the ingestion code (Milestone 3) upserts
against it rather than blindly inserting.

Stat columns here are NBA-shaped (points, rebounds, assists, etc.)
per the Milestone 2 scope. NFL will need its own stat shape later —
per the SAD, that's a deliberately separate table when we get there,
not a pile of nullable columns bolted onto this one.
"""

from datetime import datetime

from sqlalchemy import ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PlayerGameStats(Base):
    __tablename__ = "player_game_stats"
    __table_args__ = (
        UniqueConstraint("player_id", "game_id", name="uq_player_game"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), nullable=False)

    minutes: Mapped[float] = mapped_column(default=0)
    points: Mapped[int] = mapped_column(default=0)
    rebounds: Mapped[int] = mapped_column(default=0)
    assists: Mapped[int] = mapped_column(default=0)
    steals: Mapped[int] = mapped_column(default=0)
    blocks: Mapped[int] = mapped_column(default=0)
    turnovers: Mapped[int] = mapped_column(default=0)
    field_goal_attempts: Mapped[int] = mapped_column(default=0)
    three_point_attempts: Mapped[int] = mapped_column(default=0)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
