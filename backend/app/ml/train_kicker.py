"""Train, evaluate and save the kicker model:

    python -m app.ml.train_kicker
    python -m app.ml.train_kicker --no-save --cutoff 2025-11-01

Evaluation trains on the games before a cutoff (week 11 of 2025 by default) and judges, in fantasy
points under the default scoring, on the kicker-games after it, against simple baselines; the saved
model is then refit on every game. The worker retrains on a schedule with the same functions
(`app/ml/retrain.py`).
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from app.db.session import engine
from app.ml.kicker import (
    ATTEMPTS,
    KickerModel,
    build_features,
    compare,
    default_cutoff,
    league_rates,
    load_history,
    save,
    train,
    usable,
    with_prior_totals,
)
from app.services.scoring import default_config


@dataclass
class Trained:
    """The held-out comparison and, unless asked not to, the model refit on every game."""

    cutoff: pd.Timestamp
    table: pd.DataFrame  # one row per method, from `kicker.compare`
    final: KickerModel | None


def fit(
    cutoff: pd.Timestamp | None = None, final: bool = True, log: Callable[[str], None] = print
) -> Trained:
    """Evaluate on the kicker-games after the cutoff, then (if `final`) refit on all of them."""
    with engine.connect() as conn:
        history = load_history(conn)
    features = build_features(history.team_games)
    ready = features[usable(features) & features["xpa"].notna()].copy()
    cutoff = cutoff or default_cutoff(ready)
    early = ready["start_time"] < cutoff
    train_rows = ready[early]
    log(
        f"{len(history.team_games)} team-games, {len(history.kicker_games)} kicker-games; "
        f"cutoff {cutoff:%Y-%m-%d}: train {len(train_rows)}, "
        f"test {int((~early).sum())} team-games"
    )

    league = league_rates(history.kicker_games[history.kicker_games["start_time"] < cutoff])
    fitted = KickerModel(train(train_rows), league, f"{cutoff:%Y-%m-%d}", len(train_rows))
    # The test rows are the kicker-games after the cutoff, with the team's features beside them.
    kicker_games = with_prior_totals(history.kicker_games)
    test = kicker_games.merge(
        ready[~early], on=["team_id", "game_id", "start_time"], how="inner", suffixes=("", "_t")
    )
    test = test.reset_index(drop=True)
    league_attempts = pd.DataFrame({s: train_rows[s].mean() for s in ATTEMPTS}, index=test.index)
    recent = pd.DataFrame({s: test[f"{s}__ewm"].fillna(league_attempts[s]) for s in ATTEMPTS})
    predictions = {
        "model": fitted.predict(test),
        "league_avg": league_attempts,
        "recent_avg": recent,
    }
    table = compare(default_config("NFL"), test, history.kicks, league, predictions)

    saved = None
    if final:
        saved = KickerModel(
            train(ready), league_rates(history.kicker_games),
            f"{ready['start_time'].max():%Y-%m-%d}", len(ready),
            {"cutoff": f"{cutoff:%Y-%m-%d}", "held_out": table.to_dict("records")},
        )  # fmt: skip
    return Trained(cutoff, table, saved)


def run(cutoff: pd.Timestamp | None, save_model: bool) -> None:
    trained = fit(cutoff, final=save_model)
    with pd.option_context("display.width", 200, "display.float_format", "{:.3f}".format):
        print(trained.table.to_string(index=False))
    if trained.final is not None:
        print("saved", save(trained.final))


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and evaluate the kicker model")
    parser.add_argument("--cutoff", type=pd.Timestamp)
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()
    run(args.cutoff, not args.no_save)


if __name__ == "__main__":
    main()
