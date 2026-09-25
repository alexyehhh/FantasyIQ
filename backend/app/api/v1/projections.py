"""Projection endpoints: what a source expects from players and team defenses next game.

Thin, like the others: request/response translation and error mapping only. The scoring and the
sources live in app/services/projections/. Every endpoint takes the usual `scoring` parameter, so
a projection is in the caller's league scoring, and a `source` naming who the stats come from.
"""

from collections.abc import Sequence
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.scoring_param import SCORING_PARAM_DESCRIPTION, scoring_or_422
from app.db.session import get_db
from app.schemas.players import TeamSummary
from app.schemas.projections import (
    ProjectedGame,
    ProjectionEntry,
    ProjectionResponse,
    ProjectionSource,
)
from app.services import defenses as defenses_service
from app.services import players as players_service
from app.services.projections import service as projections_service
from app.services.projections.base import PROVIDERS, ProjectionError, UnknownSource
from app.services.projections.service import Projection, ProjectionInputError
from app.services.scoring import ScoringConfig

router = APIRouter(tags=["projections"])

DEFAULT_SOURCE = "sleeper"
_SOURCE_PARAM = Query(
    default=DEFAULT_SOURCE, description="Where the stats come from: see /projections/sources"
)
_WEEK_PARAM = Query(default=None, ge=1, le=18, description="NFL week; default is the next game")


def _entry(projection: Projection) -> ProjectionEntry:
    game = None
    if projection.game and projection.opponent and projection.is_home is not None:
        game = ProjectedGame(
            game_id=projection.game.id,
            start_time=projection.game.start_time,
            status=projection.game.status,  # type: ignore[arg-type]
            week=projection.game.week,
            is_home=projection.is_home,
            opponent=TeamSummary.model_validate(projection.opponent),
        )
    return ProjectionEntry(
        kind=projection.kind,
        id=projection.entity_id,
        name=projection.name,
        position=projection.position,
        team=TeamSummary.model_validate(projection.team) if projection.team else None,
        headshot_url=projection.headshot_url,
        source=projection.source,
        status=projection.status,
        fantasy_points=projection.fantasy_points,
        low=projection.low,
        high=projection.high,
        std=projection.std,
        spread_basis=projection.spread_basis,  # type: ignore[arg-type]
        chance_best=projection.chance_best,
        game=game,
        stats=projection.stats,
        games_sampled=projection.games_sampled,
        injury_status=projection.injury_status,
        approximate=projection.approximate,
        unprojected_stats=projection.unprojected,
        notes=projection.notes,
    )


def _run(
    db: Session,
    *,
    sport: str,
    source: str,
    config: ScoringConfig,
    player_ids: Sequence[int] = (),
    defense_ids: Sequence[int] = (),
    week: int | None = None,
) -> ProjectionResponse:
    try:
        projections = projections_service.project(
            db,
            sport=sport,
            source=source,
            config=config,
            player_ids=player_ids,
            defense_ids=defense_ids,
            week=week,
        )
    except UnknownSource as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProjectionInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProjectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ProjectionResponse(
        source=source,
        scoring=config.name,
        week=week or projections_service.current_week(db, sport),
        items=[_entry(p) for p in projections],
    )


@router.get("/projections/sources", response_model=list[ProjectionSource])
def list_sources() -> list[ProjectionSource]:
    return [
        ProjectionSource(
            name=p.name, label=p.label, description=p.description, sports=sorted(p.sports)
        )
        for p in PROVIDERS.values()
    ]


@router.get("/projections/top", response_model=ProjectionResponse)
def top_projections(
    sport: Literal["NBA", "NFL"],
    slot: str = Query(
        description="Lineup slot: NFL QB/RB/WR/TE/FLEX/SUPERFLEX/K/DST, NBA G/F/C/UTIL"
    ),
    source: str = _SOURCE_PARAM,
    week: int | None = _WEEK_PARAM,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    scoring: str | None = Query(default=None, description=SCORING_PARAM_DESCRIPTION),
    db: Session = Depends(get_db),  # noqa: B008 — idiomatic FastAPI DI
) -> ProjectionResponse:
    """A page of the best projections for a lineup slot, highest first, and how many there are."""
    config = scoring_or_422(scoring, sport)
    try:
        projections, total = projections_service.top_players(
            db,
            sport=sport,
            slot=slot.upper(),
            source=source,
            config=config,
            week=week,
            limit=limit,
            offset=offset,
        )
    except (UnknownSource, ProjectionInputError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProjectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ProjectionResponse(
        source=source,
        scoring=config.name,
        week=week or projections_service.current_week(db, sport),
        items=[_entry(p) for p in projections],
        total=total,
    )


@router.get("/projections", response_model=ProjectionResponse)
def compare_projections(
    sport: Literal["NBA", "NFL"],
    player_id: list[int] = Query(default=[]),  # noqa: B008 — repeat for each player
    defense_id: list[int] = Query(default=[]),  # noqa: B008 — NFL team ids, repeat for each
    source: str = _SOURCE_PARAM,
    week: int | None = _WEEK_PARAM,
    scoring: str | None = Query(default=None, description=SCORING_PARAM_DESCRIPTION),
    db: Session = Depends(get_db),  # noqa: B008 — idiomatic FastAPI DI
) -> ProjectionResponse:
    """Project several players and/or defenses side by side, best first: who to start."""
    if not player_id and not defense_id:
        raise HTTPException(status_code=422, detail="Give at least one player_id or defense_id")
    if len(player_id) + len(defense_id) > 50:
        raise HTTPException(status_code=422, detail="At most 50 players and defenses at once")
    return _run(
        db,
        sport=sport,
        source=source,
        config=scoring_or_422(scoring, sport),
        player_ids=player_id,
        defense_ids=defense_id,
        week=week,
    )


@router.get("/players/{player_id}/projection", response_model=ProjectionEntry)
def get_player_projection(
    player_id: int,
    source: str = _SOURCE_PARAM,
    week: int | None = _WEEK_PARAM,
    scoring: str | None = Query(default=None, description=SCORING_PARAM_DESCRIPTION),
    db: Session = Depends(get_db),  # noqa: B008 — idiomatic FastAPI DI
) -> ProjectionEntry:
    player = players_service.get_player(db, player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")
    response = _run(
        db,
        sport=player.sport,
        source=source,
        config=scoring_or_422(scoring, player.sport),
        player_ids=[player_id],
        week=week,
    )
    return response.items[0]


@router.get("/defenses/{team_id}/projection", response_model=ProjectionEntry)
def get_defense_projection(
    team_id: int,
    source: str = _SOURCE_PARAM,
    week: int | None = _WEEK_PARAM,
    scoring: str | None = Query(default=None, description=SCORING_PARAM_DESCRIPTION),
    db: Session = Depends(get_db),  # noqa: B008 — idiomatic FastAPI DI
) -> ProjectionEntry:
    if defenses_service.get_defense(db, team_id) is None:
        raise HTTPException(status_code=404, detail="Defense not found")
    response = _run(
        db,
        sport="NFL",
        source=source,
        config=scoring_or_422(scoring, "NFL"),
        defense_ids=[team_id],
        week=week,
    )
    return response.items[0]
