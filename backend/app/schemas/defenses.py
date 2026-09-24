"""Response schemas for the team defense API (app/api/v1/defenses.py)."""

from pydantic import BaseModel

from app.schemas.players import NextGame, TeamSummary, UTCDatetime


class DefenseListItem(TeamSummary):
    """A team defense as listed: with its fantasy points for the latest season with defense
    stats (under the request's scoring), or None if it has none."""

    fantasy_points: float | None = None


class DefenseListResponse(BaseModel):
    items: list[DefenseListItem]
    total: int
    limit: int
    offset: int


class DefenseDetail(TeamSummary):
    next_game: NextGame | None = None


class DefenseGameStatsEntry(BaseModel):
    """One game's defense line. `stats` is a flat dict of stat name -> value (sacks,
    interceptions, points_allowed, ...); `fantasy_points` is under the request's scoring.

    `opponent`, the scores and `result` are from the defense's side."""

    game_id: int
    game_date: UTCDatetime
    week: int | None = None
    stats: dict[str, int]
    fantasy_points: float
    opponent: TeamSummary | None = None
    is_home: bool | None = None
    team_score: int | None = None
    opponent_score: int | None = None
    result: str | None = None  # "W" | "L" | "T"
