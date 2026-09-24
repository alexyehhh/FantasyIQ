"""
Team model.

Shared across NBA and NFL — a team is a team regardless of sport, so
this is one table with a `sport` column rather than separate
NBA/NFL team tables. This is the "share what's genuinely shared"
half of the SAD's NBA/NFL design principle.
"""

from datetime import datetime

from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    abbreviation: Mapped[str] = mapped_column(String(10), nullable=False)
    sport: Mapped[str] = mapped_column(String(10), nullable=False)  # "NBA" | "NFL"
    logo_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    primary_color: Mapped[str | None] = mapped_column(String(7), nullable=True)  # e.g. "#a40227"
    bye_week: Mapped[int | None] = mapped_column(nullable=True)  # NFL only; this season's bye

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
