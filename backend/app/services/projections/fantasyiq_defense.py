"""Team defense projections for the `fantasyiq` source: the NFL model in `app/ml/defense.py` run
on the defense's earlier games and its opponent's recent offense.

Kept apart from the player side in `fantasyiq.py`, which it shares no data with: a defense's
history is the team table, not player box scores.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Game
from app.ml import defense as model
from app.ml.features import MIN_PRIOR_GAMES
from app.services.projections.base import ProjectionError, StatProjection, Unavailable

# (how many finished games, the latest) -> every team-game so far; rebuilt when a game finishes.
_cache: dict[str, tuple[tuple[int, object], pd.DataFrame]] = {}


@dataclass(frozen=True)
class DefenseRow:
    """One team's defense in a game to project."""

    team_id: int
    game: Game


def _history(db: Session) -> pd.DataFrame:
    key = tuple(
        db.execute(
            select(func.count(Game.id), func.max(Game.start_time)).where(
                Game.sport == "NFL", Game.status == "final", Game.stats_final.is_(True)
            )
        ).one()
    )
    cached = _cache.get("NFL")
    if cached is None or cached[0] != key:
        cached = (key, model.load_history(db.connection()))
        _cache["NFL"] = cached
    return cached[1]


def predict(db: Session, rows: Sequence[DefenseRow]) -> dict[int, StatProjection | Unavailable]:
    """Expected stat line by team id. A team with too few games of history is Unavailable."""
    saved = model.load_cached()
    if saved is None:
        raise ProjectionError(
            "The FantasyIQ defense model hasn't been trained (python -m app.ml.train_defense)"
        )
    if not rows:
        return {}
    games = {r.game.id: r.game for r in rows}
    # A game projected after it was played is projected as it would have been beforehand, so both
    # teams' history stops at its start.
    starts: dict[int, pd.Timestamp] = {}
    for game in games.values():
        for team in (game.home_team_id, game.away_team_id):
            starts[team] = min(starts.get(team, pd.Timestamp.max), pd.Timestamp(game.start_time))
    history = _history(db)
    history = history[history["start_time"] < history["team_id"].map(starts)]

    upcoming = model.upcoming_rows(
        pd.DataFrame(
            [
                {
                    "game_id": g.id,
                    "start_time": pd.Timestamp(g.start_time),
                    "season": g.season,
                    "week": g.week,
                    "home_id": g.home_team_id,
                    "away_id": g.away_team_id,
                }
                for g in games.values()
            ]
        )
    )
    stacked = pd.concat([history, upcoming], ignore_index=True)
    stacked = stacked.sort_values(["team_id", "start_time"], kind="stable").reset_index(drop=True)
    features = model.build_features(stacked)
    wanted = {(r.team_id, r.game.id) for r in rows}
    chosen = features[
        features[model.STATS[0]].isna()
        & features.apply(lambda row: (row["team_id"], row["game_id"]) in wanted, axis=1)
    ]
    lines = saved.predict(chosen)
    results: dict[int, StatProjection | Unavailable] = {}
    for index, team_id in chosen["team_id"].items():
        if chosen.loc[index, "n_prior"] < MIN_PRIOR_GAMES:
            results[int(team_id)] = Unavailable(
                f"Fewer than {MIN_PRIOR_GAMES} games of history for the model to go on"
            )
            continue
        results[int(team_id)] = StatProjection(
            stats={stat: float(v) for stat, v in lines.loc[index].items()},
            notes=[
                f"Projection from the FantasyIQ model (games to {saved.trained_through}), "
                "allowing for the opponent's recent offense."
            ],
            meta={"trained_through": saved.trained_through},
        )
    return results
