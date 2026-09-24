"""Scoring endpoints.

Serves the FantasyIQ default scoring config for a sport, so a client can describe it (and later
start a custom league's config from it) without keeping its own copy of the weights.
"""

from typing import Literal

from fastapi import APIRouter

from app.services.scoring import ScoringConfig, default_config

router = APIRouter(prefix="/scoring", tags=["scoring"])


@router.get("/presets/{sport}", response_model=ScoringConfig)
def get_scoring_preset(sport: Literal["NBA", "NFL"]) -> ScoringConfig:
    return default_config(sport)
