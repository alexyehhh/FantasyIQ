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
    PlayerDetail,
    PlayerGameStatsEntry,
    PlayerListResponse,
    PlayerSummary,
)
from app.services import players as players_service

router = APIRouter(prefix="/players", tags=["players"])


@router.get("", response_model=PlayerListResponse)
def list_players(
    sport: Literal["NBA", "NFL"] | None = None,
    team_id: int | None = None,
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),  # noqa: B008 — idiomatic FastAPI DI
) -> PlayerListResponse:
    players, total = players_service.list_players(
        db, sport=sport, team_id=team_id, search=search, limit=limit, offset=offset
    )
    return PlayerListResponse(
        items=[PlayerSummary.model_validate(player) for player in players],
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
    return PlayerDetail.model_validate(player)


@router.get("/{player_id}/stats", response_model=list[PlayerGameStatsEntry])
def get_player_stats(
    player_id: int,
    limit: int | None = Query(default=None, ge=1, le=200),
    db: Session = Depends(get_db),  # noqa: B008 — idiomatic FastAPI DI
) -> list[PlayerGameStatsEntry]:
    player = players_service.get_player(db, player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")

    rows = players_service.get_player_game_stats(db, player, limit=limit)
    return [
        PlayerGameStatsEntry(
            game_id=stats_row.game_id,
            game_date=game_start_time,
            stats=players_service.serialize_stats_row(stats_row),
        )
        for stats_row, game_start_time in rows
    ]
