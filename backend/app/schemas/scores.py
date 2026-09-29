"""Response schemas for the scoreboard endpoint (app/api/v1/scores.py)."""

from pydantic import BaseModel

from app.schemas.players import TeamSummary, UTCDatetime


class ScoreboardGame(BaseModel):
    """One game on the scoreboard: both teams and the score so far, whatever the game's status."""

    game_id: int
    start_time: UTCDatetime
    status: str  # "scheduled" | "in_progress" | "final"
    week: int | None
    home_team: TeamSummary
    away_team: TeamSummary
    home_score: int | None
    away_score: int | None


class ScoreboardResponse(BaseModel):
    """`week` is the NFL week these games are for, or None for the NBA (which has no weeks)."""

    week: int | None
    games: list[ScoreboardGame]
