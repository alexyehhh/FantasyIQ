"""Train, evaluate and save the projection model:

    python -m app.ml.train --sport NBA
    python -m app.ml.train --sport NFL --report

Evaluation trains on the games before a time cutoff and judges on the rest (see `evaluate.py`).
The model that is saved is then refit on *all* games, so it projects with the freshest data; the
saved metrics are the held-out ones. Defaults: the cutoff for NFL is week 11 of the 2025 season;
for NBA it is 70% of the way through the latest full season. Override with --cutoff YYYY-MM-DD.
"""

from __future__ import annotations

import argparse
from datetime import datetime

import pandas as pd

from app.db.session import engine
from app.ml import evaluate, model
from app.ml.dataset import STATS, load_history
from app.ml.features import build_features, usable
from app.services.scoring import default_config


def default_cutoff(sport: str, frame: pd.DataFrame) -> pd.Timestamp:
    if sport == "NFL":
        week_11 = frame[(frame["season"] == "2025") & (frame["week"] == 11)]
        return week_11["start_time"].min()
    latest = frame[frame["season"] == sorted(frame["season"].unique())[-1]]
    return latest["start_time"].quantile(0.7)


def run(sport: str, cutoff: pd.Timestamp | None, report: bool, save: bool) -> None:
    stats = STATS[sport]
    with engine.connect() as conn:
        history = load_history(conn, sport)
    print(f"{sport}: {len(history)} player-games, {history['player_id'].nunique()} players")
    features = build_features(history, stats)
    ready = features[usable(features)].copy()
    cutoff = cutoff or default_cutoff(sport, ready)
    train_mask, test_mask = evaluate.split_by_time(ready, cutoff)
    train_rows, test_rows = ready[train_mask], ready[test_mask]
    print(f"cutoff {cutoff:%Y-%m-%d}: train {len(train_rows)}, test {len(test_rows)}")

    fitted = model.train(sport, train_rows)
    held_out = model.SportModel(sport, fitted, f"{cutoff:%Y-%m-%d}", len(train_rows))
    predictions = {"model": held_out.predict(test_rows)}
    for name in evaluate.BASELINES:
        predictions[name] = evaluate.baseline_lines(test_rows, stats, name)

    group = "week" if sport == "NFL" else "start_time"
    if sport == "NBA":
        test_rows = test_rows.assign(start_time=test_rows["start_time"].dt.date)
    table = evaluate.compare(default_config(sport), test_rows, predictions, stats, group)
    with pd.option_context("display.width", 200, "display.float_format", "{:.3f}".format):
        print(table.to_string(index=False))
        if report:
            print(evaluate.stat_mae(test_rows, predictions, stats).to_string())

    if save:
        final = model.train(sport, ready)
        saved = model.SportModel(
            sport, final, f"{ready['start_time'].max():%Y-%m-%d}", len(ready),
            {"cutoff": f"{cutoff:%Y-%m-%d}", "held_out": table.to_dict("records")},
        )  # fmt: skip
        print("saved", model.save(saved))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sport", choices=sorted(STATS), required=True)
    parser.add_argument("--cutoff", type=datetime.fromisoformat)
    parser.add_argument("--report", action="store_true", help="also print per-stat MAE")
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()
    cutoff = pd.Timestamp(args.cutoff) if args.cutoff else None
    run(args.sport, cutoff, args.report, not args.no_save)


if __name__ == "__main__":
    main()
