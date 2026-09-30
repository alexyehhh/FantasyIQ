"""Accuracy endpoint: how good each projection source's pre-kickoff projections were.

Thin, like the others; the scoring and comparison live in app/services/accuracy.py.
"""

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.scoring_param import SCORING_PARAM_DESCRIPTION, scoring_or_422
from app.db.session import get_db
from app.schemas.accuracy import AccuracyResponse
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
