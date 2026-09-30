"""
ProjectionSnapshot model.

What a projection source said about a player (or team defense) for a game *before it was played*.
Nothing else can say how accurate a source was: Sleeper publishes only its current projection, so
unless it is saved ahead of kickoff it is gone once the game is over. The raw stat line is stored,
never fantasy points, so the same snapshot can be scored under any league's scoring later, against
the game's real box score.

The worker captures snapshots while a game is still scheduled, so a snapshot can't have seen the
result. A source's projection for a game is its *latest* snapshot (`captured_at` is when it said
it); a capture that would repeat the latest one is skipped, so a row means "it changed".
`origin` is "live" for a snapshot captured ahead of the game and "backtest" for one replayed
afterwards from data the source could have had, which a comparison must keep apart.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProjectionSnapshot(Base):
    __tablename__ = "projection_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "kind",
            "entity_id",
            "game_id",
            "origin",
            "captured_at",
            name="uq_projection_snapshot",
        ),
        Index("ix_projection_snapshots_game_source", "game_id", "source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False)  # "sleeper", "fantasyiq", ...
    sport: Mapped[str] = mapped_column(String(10), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # "player" | "defense"
    # players.id for a player, teams.id for a team defense (as in the projection endpoints).
    entity_id: Mapped[int] = mapped_column(nullable=False)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), nullable=False)
    origin: Mapped[str] = mapped_column(String(10), nullable=False, default="live")
    captured_at: Mapped[datetime] = mapped_column(nullable=False)
    # The raw projected stat line, by our stat names (the columns of the stats tables).
    stats: Mapped[dict[str, float]] = mapped_column(JSONB, nullable=False)
    # A kicker's expected field goals by distance: [{"low", "high", "made", "missed"}, ...].
    kicks: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    # What the source knew or assumed, for reading an old snapshot later (model version, settings).
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
