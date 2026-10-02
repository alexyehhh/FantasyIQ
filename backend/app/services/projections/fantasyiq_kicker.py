"""Kicker projections for the `fantasyiq` source: the NFL model in `app/ml/kicker.py` run on the
team's earlier kicking, its scoring and the opponent's defense, with the kicker's own make rates.

Kept apart from the player side in `fantasyiq.py`, which it shares no data with: a kicker's history
is kicks and a team's scoring, not box-score workloads.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Game, Player
from app.ml import kicker as model
from app.ml.features import MIN_PRIOR_GAMES
from app.services.projections.base import ProjectionError, StatProjection, Unavailable

KICKER_POSITIONS = {"K", "PK"}
# The stats the model projects for a kicker (the rest of a league's scoring is zero for one).
KICKER_STATS = {
    "field_goal_attempts",
    "field_goals_made",
    "extra_point_attempts",
    "extra_points_made",
}

# (how many finished games, the latest) -> every team's and kicker's kicking so far; rebuilt when a
# game finishes.
_cache: dict[str, tuple[tuple[int, object], model.KickerHistory]] = {}


@dataclass(frozen=True)
class KickerRow:
    """One kicker's game to project."""

    player: Player
    game: Game


def is_kicker(player: Player | None) -> bool:
    return player is not None and player.position in KICKER_POSITIONS


def _history(db: Session) -> model.KickerHistory:
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


def primary_kickers(db: Session, team_ids: set[int]) -> dict[int, int]:
    """Each team's kicker: of its active kickers, the one who kicked most recently (a team can list
    a second kicker who never plays). A team with no kicking history yet takes its first listed."""
    players = db.scalars(
        select(Player)
        .where(
            Player.sport == "NFL",
            Player.active.is_(True),
            Player.position.in_(KICKER_POSITIONS),
            Player.team_id.in_(team_ids),
        )
        .order_by(Player.id)
    ).all()
    last = _history(db).kicker_games.groupby("player_id")["start_time"].max()
    chosen: dict[int, Player] = {}
    for player in players:
        assert player.team_id is not None
        best = chosen.get(player.team_id)
        if best is None or last.get(player.id, pd.Timestamp.min) > last.get(
            best.id, pd.Timestamp.min
        ):
            chosen[player.team_id] = player
    return {team: player.id for team, player in chosen.items()}


def predict(db: Session, rows: Sequence[KickerRow]) -> dict[int, StatProjection | Unavailable]:
    """Expected stat line and kicks by player id. A kicker who isn't his team's, or whose team has
    too few games of history, is Unavailable."""
    saved = model.load_cached()
    if saved is None:
        raise ProjectionError(
            "The FantasyIQ kicker model hasn't been trained (python -m app.ml.train_kicker)"
        )
    if not rows:
        return {}
    results: dict[int, StatProjection | Unavailable] = {}
    primary = primary_kickers(db, {r.player.team_id for r in rows if r.player.team_id})
    eligible = []
    for row in rows:
        if row.player.team_id is None or primary.get(row.player.team_id) != row.player.id:
            results[row.player.id] = Unavailable("Not his team's kicker")
        else:
            eligible.append(row)
    if not eligible:
        return results

    games = {r.game.id: r.game for r in eligible}
    # A game projected after it was played is projected as it would have been beforehand, so both
    # teams' history stops at its start.
    starts: dict[int, pd.Timestamp] = {}
    for game in games.values():
        for team in (game.home_team_id, game.away_team_id):
            starts[team] = min(starts.get(team, pd.Timestamp.max), pd.Timestamp(game.start_time))
    history = _history(db)
    team_games = history.team_games
    team_games = team_games[team_games["start_time"] < team_games["team_id"].map(starts)]
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
    stacked = pd.concat([team_games, upcoming], ignore_index=True)
    stacked["start_time"] = pd.to_datetime(stacked["start_time"])  # object when there is no history
    stacked = stacked.sort_values(["team_id", "start_time"], kind="stable").reset_index(drop=True)
    features = model.build_features(stacked)
    attempts = saved.predict(features)

    for row in eligible:
        wanted = features[
            (features["team_id"] == row.player.team_id) & (features["game_id"] == row.game.id)
        ]
        if wanted.empty or wanted.iloc[0]["n_prior"] < MIN_PRIOR_GAMES:
            results[row.player.id] = Unavailable(
                f"Fewer than {MIN_PRIOR_GAMES} games of history for the model to go on"
            )
            continue
        kicker_games = history.kicker_games
        prior = kicker_games[
            (kicker_games["player_id"] == row.player.id)
            & (kicker_games["start_time"] < pd.Timestamp(row.game.start_time))
        ]
        rates = model.kicker_rates(prior, saved.league)
        stats, kicks = model.expected_line(attempts.loc[wanted.index[0]].to_dict(), rates)
        results[row.player.id] = StatProjection(
            stats=stats,
            kicks=kicks,
            notes=[
                f"Projection from the FantasyIQ model (games to {saved.trained_through}), from "
                "the team's recent kicking and scoring, the opponent's defense and his own "
                f"{int(prior[[c for c in prior if c.startswith('att_')]].sum().sum())} earlier "
                "field goal attempts."
            ],
            meta={"trained_through": saved.trained_through},
        )
    return results
