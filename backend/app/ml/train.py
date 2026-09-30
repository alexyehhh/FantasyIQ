"""Train, evaluate and save the projection model:

    python -m app.ml.train --sport NBA
    python -m app.ml.train --sport NFL --report

Evaluation trains on the games before a time cutoff and judges on the rest (see `evaluate.py`).
The model that is saved is then refit on *all* games, so it projects with the freshest data; the
saved metrics are the held-out ones. Defaults: the cutoff for NFL is week 11 of the 2025 season;
for NBA it is 70% of the way through the latest full season. Override with --cutoff YYYY-MM-DD.
The worker retrains on a schedule with the same functions (`app/ml/retrain.py`).
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from app.db.session import engine
from app.ml import evaluate, model
from app.ml.availability import Timeline, attach_training_context
from app.ml.dataset import STATS, load_history, load_team_games
from app.ml.features import build_features, usable
from app.services.scoring import default_config

# A season counts as full once it has this share of the rows of the biggest one.
_FULL_SEASON_SHARE = 0.8


def default_cutoff(sport: str, frame: pd.DataFrame) -> pd.Timestamp:
    if sport == "NFL":
        week_11 = frame[(frame["season"] == "2025") & (frame["week"] == 11)]
        return week_11["start_time"].min()
    # The latest season with most of a season's games, so the first days of a new season don't
    # leave a test set of a handful of games.
    counts = frame["season"].value_counts()
    full = sorted(s for s, n in counts.items() if n >= _FULL_SEASON_SHARE * counts.max())
    latest = frame[frame["season"] == full[-1]]
    return latest["start_time"].quantile(0.7)


@dataclass
class Trained:
    """The held-out comparison and, unless asked not to, the model refit on every game."""

    cutoff: pd.Timestamp
    table: pd.DataFrame  # one row per (position, method), from `evaluate.compare`
    stat_mae: pd.DataFrame
    final: model.SportModel | None


def fit(
    sport: str,
    cutoff: pd.Timestamp | None = None,
    context: bool = True,
    final: bool = True,
    log: Callable[[str], None] = print,
) -> Trained:
    """Evaluate on the games after the cutoff, then (if `final`) refit on all of them."""
    stats = STATS[sport]
    with engine.connect() as conn:
        history = load_history(conn, sport)
        team_games = load_team_games(conn, sport)
    log(f"{sport}: {len(history)} player-games, {history['player_id'].nunique()} players")
    if context:
        history = attach_training_context(history, Timeline(history, team_games, stats), stats)
    features = build_features(history, stats)
    ready = features[usable(features)].copy()
    cutoff = cutoff or default_cutoff(sport, ready)
    train_mask, test_mask = evaluate.split_by_time(ready, cutoff)
    train_rows, test_rows = ready[train_mask], ready[test_mask]
    log(f"cutoff {cutoff:%Y-%m-%d}: train {len(train_rows)}, test {len(test_rows)}")

    fitted = model.train(sport, train_rows)
    adjusters = model.train_adjusters(sport, train_rows)
    held_out = model.SportModel(
        sport, fitted, f"{cutoff:%Y-%m-%d}", len(train_rows), adjusters=adjusters
    )
    predictions = {
        "model": held_out.predict(test_rows),
        "avg+teammates": held_out.base_lines(test_rows),
    }
    for name in evaluate.BASELINES:
        predictions[name] = evaluate.baseline_lines(test_rows, stats, name)

    group = "week" if sport == "NFL" else "start_time"
    if sport == "NBA":
        test_rows = test_rows.assign(start_time=test_rows["start_time"].dt.date)
    table = evaluate.compare(default_config(sport), test_rows, predictions, stats, group)

    saved = None
    if final:
        saved = model.SportModel(
            sport, model.train(sport, ready), f"{ready['start_time'].max():%Y-%m-%d}", len(ready),
            {"cutoff": f"{cutoff:%Y-%m-%d}", "held_out": table.to_dict("records")},
            adjusters=model.train_adjusters(sport, ready),
        )  # fmt: skip
    return Trained(cutoff, table, evaluate.stat_mae(test_rows, predictions, stats), saved)


def run(
    sport: str, cutoff: pd.Timestamp | None, report: bool, save: bool, context: bool = True
) -> None:
    trained = fit(sport, cutoff, context, final=save)
    with pd.option_context("display.width", 200, "display.float_format", "{:.3f}".format):
        print(trained.table.to_string(index=False))
        if report:
            print(trained.stat_mae.to_string())
    if trained.final is not None:
        print("saved", model.save(trained.final))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sport", choices=sorted(STATS), required=True)
    parser.add_argument("--cutoff", type=datetime.fromisoformat)
    parser.add_argument("--report", action="store_true", help="also print per-stat MAE")
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument(
        "--no-context", action="store_true", help="leave out the teammate features (to compare)"
    )
    args = parser.parse_args()
    cutoff = pd.Timestamp(args.cutoff) if args.cutoff else None
    run(args.sport, cutoff, args.report, not args.no_save, not args.no_context)


if __name__ == "__main__":
    main()
