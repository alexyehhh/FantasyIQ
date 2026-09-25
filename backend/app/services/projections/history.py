"""How much a player's score swings from game to game.

This is used only to size the floor and ceiling around a projection (see `spread.py`); it never
moves the projection itself. A player's recent games say how volatile they are far better than
they say how good they will be next week, so the projections come from an outside source alone.
"""

from __future__ import annotations

from collections.abc import Sequence
from math import sqrt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Game, TeamGameStatsNFL
from app.services import players as players_service
from app.services.projections.base import Target
from app.services.scoring import ScoringConfig, score_defense_game

# Each game further back counts this much less than the one after it.
DECAY = 0.8
MAX_GAMES = 10
# A spread from fewer games than this says nothing.
MIN_GAMES_FOR_SPREAD = 3
_LOG_WINDOW = 40  # rows read before dropping unfinished games and games not played
_DEFENSE_METADATA_COLUMNS = {"id", "team_id", "game_id", "created_at"}


def _weighted_std(values: Sequence[float]) -> float | None:
    if len(values) < MIN_GAMES_FOR_SPREAD:
        return None
    weights = [DECAY**i for i in range(len(values))]
    total = sum(weights)
    mean = sum(v * w for v, w in zip(values, weights, strict=True)) / total
    variance = sum(w * (v - mean) ** 2 for v, w in zip(values, weights, strict=True)) / total
    return round(sqrt(variance), 1)


def _player_points(db: Session, target: Target, config: ScoringConfig) -> list[float]:
    """The player's fantasy points in their last final games, most recent first."""
    assert target.player is not None
    rows = players_service.get_player_game_log(db, target.player, limit=_LOG_WINDOW)
    played = [
        row
        for row in rows
        if row.game.status == "final"
        # An NBA row with no minutes is a game the player sat out, not a bad game.
        and (config.sport != "NBA" or getattr(row.stats_row, "minutes", 0) > 0)
    ]
    return [players_service.game_fantasy_points(config, row) for row in played[:MAX_GAMES]]


def _defense_points(db: Session, target: Target, config: ScoringConfig) -> list[float]:
    rows = db.scalars(
        select(TeamGameStatsNFL)
        .join(Game, TeamGameStatsNFL.game_id == Game.id)
        .where(TeamGameStatsNFL.team_id == target.entity_id, Game.status == "final")
        .order_by(Game.start_time.desc())
        .limit(MAX_GAMES)
    ).all()
    return [
        score_defense_game(
            config,
            {
                column.name: getattr(row, column.name)
                for column in row.__table__.columns
                if column.name not in _DEFENSE_METADATA_COLUMNS
            },
        )
        for row in rows
    ]


def points_spread(db: Session, target: Target, config: ScoringConfig) -> tuple[float | None, int]:
    """The spread (standard deviation) of the target's recent fantasy points under `config`, and
    how many games it rests on. The spread is None with too few games to say anything."""
    points = (
        _player_points(db, target, config)
        if target.kind == "player"
        else _defense_points(db, target, config)
    )
    return _weighted_std(points), len(points)
