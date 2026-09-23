"""Response schemas for the player API (app/api/v1/players.py)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PlayerSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    sport: str
    team_id: int | None
    position: str | None
    jersey_number: int | None
    active: bool


class PlayerDetail(PlayerSummary):
    external_id: str | None
    created_at: datetime
    updated_at: datetime


class PlayerListResponse(BaseModel):
    items: list[PlayerSummary]
    total: int
    limit: int
    offset: int


class PlayerGameStatsEntry(BaseModel):
    """One game's stat line. `stats` is intentionally a flat dict rather
    than NBA/NFL-specific fields, since which columns are present depends
    on the player's sport (see app/db/models/player_game_stats*.py)."""

    game_id: int
    game_date: datetime
    stats: dict[str, int | float]
