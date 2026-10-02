"""Accuracy endpoint: how good each projection source's pre-kickoff projections were.

Thin, like the others; the scoring and comparison live in app/services/accuracy.py.
"""

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.scoring_param import SCORING_PARAM_DESCRIPTION, scoring_or_422
from app.db.session import get_db
from app.schemas.accuracy import AccuracyResponse, PlayerGame, PlayerGamesResponse
from app.services import accuracy as accuracy_service

router = APIRouter(tags=["accuracy"])


@router.get("/accuracy", response_model=AccuracyResponse)
def get_accuracy(
    sport: Literal["NBA", "NFL"],
    position: str | None = Query(
        default=None, description="NFL QB/RB/WR/TE/K or NBA G/F/C; default is everyone"
    ),
    scoring: str | None = Query(default=None, description=SCORING_PARAM_DESCRIPTION),
    season: str | None = Query(default=None, description="e.g. 2026 or 2026-27; default is all"),
    source: list[str] = Query(  # noqa: B008 — repeat for each source
        default=[], description="Sources to compare; default is every source with projections"
    ),
    origin: Literal["live", "backtest"] = Query(
        default="live", description="live: saved before the game; backtest: replayed afterwards"
    ),
    include_dnp: bool = Query(
        default=False, description="Score projected players who didn't play as zero"
    ),
    db: Session = Depends(get_db),  # noqa: B008 — idiomatic FastAPI DI
) -> AccuracyResponse:
    report = accuracy_service.compute(
        db,
        sport=sport,
        config=scoring_or_422(scoring, sport),
        sources=source or None,
        position=position,
        season=season,
        origin=origin,
        include_dnp=include_dnp,
    )
    return AccuracyResponse.model_validate(asdict(report))


@router.get("/accuracy/players", response_model=PlayerGamesResponse)
def get_player_games(
    sport: Literal["NBA", "NFL"],
    player_id: int | None = Query(
        default=None, description="One player's finished games; default is the latest games"
    ),
    scoring: str | None = Query(default=None, description=SCORING_PARAM_DESCRIPTION),
    origin: Literal["live", "backtest"] = Query(default="live"),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),  # noqa: B008 — idiomatic FastAPI DI
) -> PlayerGamesResponse:
    config = scoring_or_422(scoring, sport)
    rows = accuracy_service.player_games(
        db, sport=sport, config=config, player_id=player_id, origin=origin, limit=limit
    )
    return PlayerGamesResponse(
        sport=sport,
        scoring=config.name,
        origin=origin,
        items=[PlayerGame.model_validate(asdict(r)) for r in rows],
    )


@router.get("/accuracy/defenses/{team_id}", response_model=PlayerGamesResponse)
def get_defense_games(
    team_id: int,
    scoring: str | None = Query(default=None, description=SCORING_PARAM_DESCRIPTION),
    origin: Literal["live", "backtest"] = Query(default="live"),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),  # noqa: B008 — idiomatic FastAPI DI
) -> PlayerGamesResponse:
    """One NFL team defense's finished games: real fantasy points against each source's
    projection, shaped like `/accuracy/players` (the item's player fields hold the team)."""
    config = scoring_or_422(scoring, "NFL")
    rows = accuracy_service.defense_games(
        db, config=config, team_id=team_id, origin=origin, limit=limit
    )
    return PlayerGamesResponse(
        sport="NFL",
        scoring=config.name,
        origin=origin,
        items=[PlayerGame.model_validate(asdict(r)) for r in rows],
    )
