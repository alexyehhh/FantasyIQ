"""The scoreboard endpoint: every game in the current scoring period.

Thin, like the other endpoint modules: request/response translation only. The query lives in
app/services/scores.py.
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Team
from app.db.session import get_db
from app.schemas.players import TeamSummary
from app.schemas.scores import ScoreboardGame, ScoreboardResponse
from app.services import scores as scores_service

router = APIRouter(prefix="/scores", tags=["scores"])


@router.get("", response_model=ScoreboardResponse)
def get_scoreboard(
    sport: Literal["NBA", "NFL"],
    week: int | None = Query(
        default=None, ge=1, description="NFL only; defaults to the current week"
    ),
    db: Session = Depends(get_db),  # noqa: B008 — idiomatic FastAPI DI
) -> ScoreboardResponse:
    """Every game in the current scoring period, whatever its status: an NFL week, or for the
    NBA the next (or most recent) date of games."""
    week, games = scores_service.get_scoreboard(db, sport=sport, week=week)
    team_ids = {tid for game in games for tid in (game.home_team_id, game.away_team_id)}
    teams = {team.id: team for team in db.scalars(select(Team).where(Team.id.in_(team_ids)))}

    return ScoreboardResponse(
        week=week,
        games=[
            ScoreboardGame(
                game_id=game.id,
                start_time=game.start_time,
                status=game.status,
                week=game.week,
                home_team=TeamSummary.model_validate(teams[game.home_team_id]),
                away_team=TeamSummary.model_validate(teams[game.away_team_id]),
                home_score=game.home_score,
                away_score=game.away_score,
            )
            for game in games
        ],
    )
