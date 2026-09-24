"""Player endpoints.

Thin: request/response translation and 404 handling only. Every query
goes through app/services/players.py, per AGENTS.md's rule that
business logic doesn't live in route handlers.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.players import (
    InjuryReport,
    NextGame,
    PlayerDetail,
    PlayerGameStatsEntry,
    PlayerListItem,
    PlayerListResponse,
    ScheduleEntry,
    TeamSummary,
)
from app.services import players as players_service

router = APIRouter(prefix="/players", tags=["players"])


@router.get("", response_model=PlayerListResponse)
def list_players(
    sport: Literal["NBA", "NFL"] | None = None,
    team_id: int | None = None,
    search: str | None = None,
    position: list[str] | None = Query(default=None),  # noqa: B008 — repeat to match any
    sort: Literal["name", "fantasy_points"] = "name",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),  # noqa: B008 — idiomatic FastAPI DI
) -> PlayerListResponse:
    if sort == "fantasy_points" and sport is None:
        raise HTTPException(
            status_code=422, detail="sport is required to sort by fantasy points"
        )
    players, total = players_service.list_players(
        db,
        sport=sport,
        team_id=team_id,
        search=search,
        positions=position,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    points = players_service.get_season_fantasy_points(db, players)
    items = []
    for player in players:
        item = PlayerListItem.model_validate(player)
        item.fantasy_points = points.get(player.id)
        items.append(item)
    return PlayerListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{player_id}", response_model=PlayerDetail)
def get_player(
    player_id: int, db: Session = Depends(get_db)  # noqa: B008 — idiomatic FastAPI DI
) -> PlayerDetail:
    player = players_service.get_player(db, player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")
    detail = PlayerDetail.model_validate(player)
    if player.injury_status:
        detail.injury = InjuryReport(
            status=player.injury_status,
            type=player.injury_type,
            note=player.injury_note,
            updated_at=player.injury_updated_at,
        )
    upcoming = players_service.get_next_game(db, player)
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


@router.get("/{player_id}/stats", response_model=list[PlayerGameStatsEntry])
def get_player_stats(
    player_id: int,
    limit: int | None = Query(default=None, ge=1, le=200),
    db: Session = Depends(get_db),  # noqa: B008 — idiomatic FastAPI DI
) -> list[PlayerGameStatsEntry]:
    player = players_service.get_player(db, player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")

    return [
        PlayerGameStatsEntry(
            game_id=row.game.id,
            game_date=row.game.start_time,
            week=row.game.week,
            stats=players_service.serialize_stats_row(row.stats_row),
            opponent=TeamSummary.model_validate(row.opponent) if row.opponent else None,
            is_home=row.is_home,
            team_score=row.team_score,
            opponent_score=row.opponent_score,
            result=row.result,
        )
        for row in players_service.get_player_game_log(db, player, limit=limit)
    ]


@router.get("/{player_id}/schedule", response_model=list[ScheduleEntry])
def get_player_schedule(
    player_id: int,
    db: Session = Depends(get_db),  # noqa: B008 — idiomatic FastAPI DI
) -> list[ScheduleEntry]:
    player = players_service.get_player(db, player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")

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
        for matchup in players_service.get_player_schedule(db, player)
    ]
