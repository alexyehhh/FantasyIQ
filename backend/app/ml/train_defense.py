"""Train, evaluate and save the team defense model:

    python -m app.ml.train_defense
    python -m app.ml.train_defense --no-save --cutoff 2025-11-01

Evaluation trains on the games before a cutoff (week 11 of 2025 by default) and judges on the
rest, against simple baselines; the saved model is then refit on every game.
"""

from __future__ import annotations

import argparse

import pandas as pd

from app.db.session import engine
from app.ml.defense import (
    STATS,
    DefenseModel,
    build_features,
    compare,
    default_cutoff,
    load_history,
    save,
    train,
    usable,
)
from app.services.scoring import default_config


def run(cutoff: pd.Timestamp | None, save_model: bool) -> None:
    with engine.connect() as conn:
        history = load_history(conn)
    features = build_features(history)
    ready = features[usable(features)].copy()
    cutoff = cutoff or default_cutoff(ready)
    early = ready["start_time"] < cutoff
    train_rows, test_rows = ready[early], ready[~early]
    print(
        f"{len(history)} team-games; cutoff {cutoff:%Y-%m-%d}: "
        f"train {len(train_rows)}, test {len(test_rows)}"
    )

    fitted = DefenseModel(train(train_rows), f"{cutoff:%Y-%m-%d}", len(train_rows))
    league = pd.DataFrame({s: train_rows[s].mean() for s in STATS}, index=test_rows.index)
    predictions = {
        "model": fitted.predict(test_rows),
        "league_avg": league,
        "recent_avg": pd.DataFrame({s: test_rows[f"{s}__ewm"].fillna(league[s]) for s in STATS}),
        "last_8": pd.DataFrame({s: test_rows[f"{s}__m8"].fillna(league[s]) for s in STATS}),
    }
    table = compare(default_config("NFL"), test_rows, predictions)
    with pd.option_context("display.width", 200, "display.float_format", "{:.3f}".format):
        print(table.to_string(index=False))
        mae = {
            method: {s: float((lines[s] - test_rows[s]).abs().mean()) for s in STATS}
            for method, lines in predictions.items()
        }
        print(pd.DataFrame(mae).to_string())

    if save_model:
        final = DefenseModel(
            train(ready), f"{ready['start_time'].max():%Y-%m-%d}", len(ready),
            {"cutoff": f"{cutoff:%Y-%m-%d}", "held_out": table.to_dict("records")},
        )  # fmt: skip
        print("saved", save(final))


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and evaluate the team defense model")
    parser.add_argument("--cutoff", type=pd.Timestamp)
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()
    run(args.cutoff, not args.no_save)


if __name__ == "__main__":
    main()
