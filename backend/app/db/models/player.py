"""
Player model.

Like Team, this is shared across sports rather than split into
NBA/PlayerNFL. Sport-specific stat *shapes* (what a stat line looks
like) genuinely differ between NBA and NFL and live in
PlayerGameStats, not here — a player's identity doesn't.
"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.team import Team


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    sport: Mapped[str] = mapped_column(String(10), nullable=False)  # "NBA" | "NFL"
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    position: Mapped[str | None] = mapped_column(String(10), nullable=True)
    jersey_number: Mapped[int | None] = mapped_column(nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    headshot_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    height_inches: Mapped[int | None] = mapped_column(nullable=True)
    weight_lbs: Mapped[int | None] = mapped_column(nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    college: Mapped[str | None] = mapped_column(String(100), nullable=True)
    experience_years: Mapped[int | None] = mapped_column(nullable=True)
    # Current injury report only (not history); all null when the player is healthy.
    injury_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    injury_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    injury_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    injury_updated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    team: Mapped[Team | None] = relationship()

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
