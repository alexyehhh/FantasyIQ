"""
PlayerGameStatsNFL model.

One row per player per game, NFL-shaped. Per the note on
PlayerGameStats, NFL's stat shape (passing/rushing/receiving,
not points/rebounds/assists) doesn't fit that table, so it gets its
own table here rather than a pile of nullable columns bolted onto the
NBA one. Same idempotency mechanism: the unique constraint on
(player_id, game_id) is what the NFL ingestion job upserts against.
"""

from datetime import datetime

from sqlalchemy import ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PlayerGameStatsNFL(Base):
    __tablename__ = "player_game_stats_nfl"
    __table_args__ = (
        UniqueConstraint("player_id", "game_id", name="uq_player_game_nfl"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), nullable=False)

    passing_completions: Mapped[int] = mapped_column(default=0)
    passing_attempts: Mapped[int] = mapped_column(default=0)
    passing_yards: Mapped[int] = mapped_column(default=0)
    passing_touchdowns: Mapped[int] = mapped_column(default=0)
    interceptions: Mapped[int] = mapped_column(default=0)

    rushing_attempts: Mapped[int] = mapped_column(default=0)
    rushing_yards: Mapped[int] = mapped_column(default=0)
    rushing_touchdowns: Mapped[int] = mapped_column(default=0)

    receptions: Mapped[int] = mapped_column(default=0)
    receiving_targets: Mapped[int] = mapped_column(default=0)
    receiving_yards: Mapped[int] = mapped_column(default=0)
    receiving_touchdowns: Mapped[int] = mapped_column(default=0)

    fumbles_lost: Mapped[int] = mapped_column(default=0)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
