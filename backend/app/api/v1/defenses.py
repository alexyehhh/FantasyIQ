"""Team defense (D/ST) endpoints.

Thin, like the player endpoints: request/response translation and 404 handling only. The
queries and scoring live in app/services/defenses.py. A defense is an NFL team, so it is
addressed by team id.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.scoring_param import SCORING_PARAM_DESCRIPTION, scoring_or_422
from app.db.session import get_db
from app.schemas.defenses import (
    DefenseDetail,
    DefenseGameStatsEntry,
    DefenseListItem,
    DefenseListResponse,
)
from app.schemas.players import NextGame, ScheduleEntry, SeasonSummary, TeamSummary
from app.services import defenses as defenses_service
from app.services import players as players_service
from app.services import season_summary as season_summary_service

router = APIRouter(prefix="/defenses", tags=["defenses"])


def _defense_or_404(db: Session, team_id: int):
    team = defenses_service.get_defense(db, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Defense not found")
    return team


@router.get("", response_model=DefenseListResponse)
def list_defenses(
    search: str | None = None,
    sort: Literal["name", "fantasy_points"] = "name",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    scoring: str | None = Query(default=None, description=SCORING_PARAM_DESCRIPTION),
    db: Session = Depends(get_db),  # noqa: B008 — idiomatic FastAPI DI
) -> DefenseListResponse:
    config = scoring_or_422(scoring, "NFL")
    teams, total = defenses_service.list_defenses(
        db, search=search, sort=sort, limit=limit, offset=offset, scoring=config
    )
    points = defenses_service.get_season_fantasy_points(db, teams, scoring=config)
    items = []
    for team in teams:
        item = DefenseListItem.model_validate(team)
        item.fantasy_points = points.get(team.id)
        items.append(item)
    return DefenseListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{team_id}", response_model=DefenseDetail)
def get_defense(
    team_id: int, db: Session = Depends(get_db)  # noqa: B008 — idiomatic FastAPI DI
) -> DefenseDetail:
    team = _defense_or_404(db, team_id)
    detail = DefenseDetail.model_validate(team)
    upcoming = players_service.get_team_next_game(db, team.id)
    if upcoming:
        game, opponent, is_home = upcoming
        detail.next_game = NextGame(
            game_id=game.id,
            start_time=game.start_time,
            status=game.status,
            is_home=is_home,
            opponent=TeamSummary.model_validate(opponent),
        )
    return detail


@router.get("/{team_id}/stats", response_model=list[DefenseGameStatsEntry])
def get_defense_stats(
    team_id: int,
    limit: int | None = Query(default=None, ge=1, le=200),
    season: Literal["current", "all"] = Query(
        default="all", description="'current' for the season in play only, 'all' for every season"
    ),
    scoring: str | None = Query(default=None, description=SCORING_PARAM_DESCRIPTION),
    db: Session = Depends(get_db),  # noqa: B008 — idiomatic FastAPI DI
) -> list[DefenseGameStatsEntry]:
    team = _defense_or_404(db, team_id)
    config = scoring_or_422(scoring, "NFL")
    only_season = players_service.get_current_season(db, "NFL") if season == "current" else None
    if season == "current" and only_season is None:
        return []
    return [
        DefenseGameStatsEntry(
            game_id=row.game.id,
            game_date=row.game.start_time,
            week=row.game.week,
            stats=defenses_service.serialize_defense_row(row.stats_row),
            fantasy_points=defenses_service.defense_game_fantasy_points(config, row),
            opponent=TeamSummary.model_validate(row.opponent) if row.opponent else None,
            is_home=row.is_home,
            team_score=row.team_score,
            opponent_score=row.opponent_score,
            result=row.result,
        )
        for row in defenses_service.get_defense_game_log(db, team, limit=limit, season=only_season)
    ]


@router.get("/{team_id}/schedule", response_model=list[ScheduleEntry])
def get_defense_schedule(
    team_id: int,
    db: Session = Depends(get_db),  # noqa: B008 — idiomatic FastAPI DI
) -> list[ScheduleEntry]:
    team = _defense_or_404(db, team_id)
    return [
        ScheduleEntry(
            game_id=matchup.game.id,
            game_date=matchup.game.start_time,
            status=matchup.game.status,
            week=matchup.game.week,
            is_home=matchup.is_home,
            opponent=TeamSummary.model_validate(matchup.opponent) if matchup.opponent else None,
            team_score=matchup.team_score,
            opponent_score=matchup.opponent_score,
            result=matchup.result,
        )
        for matchup in players_service.get_team_schedule(db, team.id, team.sport)
    ]


@router.get("/{team_id}/season", response_model=SeasonSummary | None)
def get_defense_season(
    team_id: int,
    scoring: str | None = Query(default=None, description=SCORING_PARAM_DESCRIPTION),
    db: Session = Depends(get_db),  # noqa: B008 — idiomatic FastAPI DI
) -> SeasonSummary | None:
    """The defense's season totals with their rank among the 32 defenses; null before it has
    played."""
    team = _defense_or_404(db, team_id)
    config = scoring_or_422(scoring, "NFL")
    summary = season_summary_service.get_defense_season_summary(db, team, scoring=config)
    return SeasonSummary.model_validate(summary, from_attributes=True) if summary else None
