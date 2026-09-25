"""Response schemas for the projection API (app/api/v1/projections.py)."""

from typing import Literal

from pydantic import BaseModel

from app.schemas.players import TeamSummary, UTCDatetime


class ProjectionSource(BaseModel):
    name: str
    label: str
    description: str
    sports: list[str]


class ProjectedGame(BaseModel):
    game_id: int
    start_time: UTCDatetime
    status: Literal["scheduled", "in_progress", "final"]
    week: int | None
    is_home: bool
    opponent: TeamSummary


class ProjectionEntry(BaseModel):
    """One player's or team defense's projection for a game.

    `status` is "ok" (`fantasy_points` is set), "out" (ruled out: 0 points), "no_game" (a bye week
    or nothing scheduled) or "unavailable" (the source has nothing for them; `notes` says why).

    `stats` is the expected stat line the points come from. `low`/`high` are one standard
    deviation either side (`std`), from the player's own games where there are enough and a typical
    spread for the position otherwise (`spread_basis`). `chance_best` is the chance (0-1) of
    scoring the most among the players compared, and null when there is only one; `games_sampled`
    is how many past games that spread rests on (the projection itself never uses them).
    `unprojected_stats` are stats the scoring values that the source doesn't project (counted as
    zero; rare ones like kick return touchdowns aren't listed), and `approximate`
    means a kicker's distance ranges only roughly line up with the scoring's brackets."""

    kind: Literal["player", "defense"]
    id: int
    name: str
    position: str | None
    team: TeamSummary | None
    headshot_url: str | None
    source: str
    status: Literal["ok", "out", "no_game", "unavailable"]
    fantasy_points: float | None
    low: float | None
    high: float | None
    std: float | None
    spread_basis: Literal["history", "blended", "position"] | None
    chance_best: float | None
    game: ProjectedGame | None
    stats: dict[str, float]
    games_sampled: int | None
    injury_status: str | None
    approximate: bool
    unprojected_stats: list[str]
    notes: list[str]


class ProjectionResponse(BaseModel):
    """Projections ranked by fantasy points under `scoring`, best first. For the top list `total`
    is how many people there are to page through (the page is `items`); null otherwise."""

    source: str
    scoring: str
    week: int | None
    items: list[ProjectionEntry]
    total: int | None = None
