"""Response schemas for the headlines endpoint (app/api/v1/players.py)."""

from typing import Literal

from pydantic import BaseModel

from app.schemas.players import TeamSummary, UTCDatetime


class HeadlineEntry(BaseModel):
    """One headline about a fantasy-relevant player, built from real synced data: either a
    standout stat line from a finished game, or a real reported injury update. Never a
    designation alone and never about a player who isn't fantasy-relevant."""

    kind: Literal["injury", "performance"]
    player_id: int
    player_name: str
    sport: str
    team: TeamSummary | None
    position: str | None
    headshot_url: str | None
    headline: str
    at: UTCDatetime


class HeadlinesResponse(BaseModel):
    items: list[HeadlineEntry]
