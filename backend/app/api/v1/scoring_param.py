"""Turns a request's `scoring` query parameter into a ScoringConfig.

Every endpoint that scores accepts the same parameter: "default" (or nothing) for the sport's
FantasyIQ preset, or an inline JSON ScoringConfig. An invalid one is the caller's mistake, so
it is answered with a 422 that says why, never a 500.
"""

from fastapi import HTTPException
from pydantic import ValidationError

from app.services.scoring import ScoringConfig, resolve_scoring

SCORING_PARAM_DESCRIPTION = (
    "'default' for the FantasyIQ scoring of the sport, or an inline JSON ScoringConfig"
)


def scoring_or_422(spec: str | None, sport: str) -> ScoringConfig:
    try:
        return resolve_scoring(spec, sport)
    except ValidationError as exc:
        detail = [{"loc": list(error["loc"]), "msg": error["msg"]} for error in exc.errors()]
        raise HTTPException(status_code=422, detail=detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
