"""Response schemas for the player API (app/api/v1/players.py)."""

from datetime import date, datetime, timezone
from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer


def _as_utc(value: datetime) -> datetime:
    """The database stores naive UTC; say so explicitly in API responses, or a
    browser would read "2026-09-24T00:20:00" as the viewer's local time."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


UTCDatetime = Annotated[datetime, PlainSerializer(_as_utc, return_type=datetime)]


class TeamSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    abbreviation: str
    logo_url: str | None
    primary_color: str | None
    bye_week: int | None


class PlayerSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    sport: str
    team_id: int | None
    team: TeamSummary | None
    position: str | None
    jersey_number: int | None
    active: bool
    headshot_url: str | None
    injury_status: str | None


class PlayerListItem(PlayerSummary):
    """A player as listed: with their fantasy points for the latest season with stats
    (default scoring), or None if they have none."""

    fantasy_points: float | None = None


class InjuryReport(BaseModel):
    status: str
    type: str | None
    note: str | None
    updated_at: UTCDatetime | None


class NextGame(BaseModel):
    game_id: int
    start_time: UTCDatetime
    status: str
    is_home: bool
    opponent: TeamSummary


class PlayerDetail(PlayerSummary):
    external_id: str | None
    height_inches: int | None
    weight_lbs: int | None
    birth_date: date | None
    college: str | None
    experience_years: int | None
    injury: InjuryReport | None = None
    next_game: NextGame | None = None
    created_at: UTCDatetime
    updated_at: UTCDatetime


class PlayerListResponse(BaseModel):
    items: list[PlayerListItem]
    total: int
    limit: int
    offset: int


class KickEntry(BaseModel):
    """One field goal attempt: its distance in yards and how it ended."""

    distance: int
    result: str  # "made" | "missed" | "blocked"


class PlayerGameStatsEntry(BaseModel):
    """One game's stat line. `stats` is intentionally a flat dict rather
    than NBA/NFL-specific fields, since which columns are present depends
    on the player's sport (see app/db/models/player_game_stats*.py).

    `opponent`/`is_home`/scores/`result` are relative to the player's
    current team and are None when the game can't be tied to it (e.g. a
    game played for a previous team, or one without a final score).

    `fantasy_points` is the game's score under the request's scoring config. `kicks` lists an
    NFL kicker's field goal attempts, in order, and is empty for everyone else."""

    game_id: int
    game_date: UTCDatetime
    week: int | None = None
    stats: dict[str, int | float]
    fantasy_points: float
    kicks: list[KickEntry] = []
    opponent: TeamSummary | None = None
    is_home: bool | None = None
    team_score: int | None = None
    opponent_score: int | None = None
    result: str | None = None  # "W" | "L" | "T"


class ScheduleEntry(BaseModel):
    """One game on the player's team's schedule this season, played or not.

    Scores and `result` are from the player's team's side and only present once
    the game has been played."""

    game_id: int
    game_date: UTCDatetime
    status: str  # "scheduled" | "in_progress" | "final"
    week: int | None
    is_home: bool | None
    opponent: TeamSummary | None
    team_score: int | None
    opponent_score: int | None
    result: str | None  # "W" | "L" | "T"


class RankedStat(BaseModel):
    """A season total and its rank (1 = best) among the same position; `tied` when another
    player has the same total."""

    total: float
    rank: int
    tied: bool


class SeasonSummary(BaseModel):
    """A player's (or defense's) totals for the latest season with stats, each ranked among
    `pool_size` players in `position_group`. `stats` has every stat column plus
    `fantasy_points` under the request's scoring. Fewer is better for turnovers,
    interceptions thrown, fumbles lost, and a defense's points and yards allowed."""

    season: str
    games: int
    position_group: str
    pool_size: int
    stats: dict[str, RankedStat]
