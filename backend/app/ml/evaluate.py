"""Scoring a model against what actually happened, on games it was not trained on.

The split is by time, never random: the model trains on everything before a cutoff and is judged
on the games after it, the same position it is in when projecting a real upcoming game. Every
prediction is turned into fantasy points with the same `ScoringConfig` as the actual line, so the
error is in points a league would see. Rows are compared only where every method has a prediction.

Baselines are the model's own inputs used as predictions: the decaying average, the last 3 games
and the median of the last 8 (the one outlier games barely move). The model has to beat them.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from app.ml.features import usable
from app.services.scoring import ScoringConfig, score_player_game

BASELINES = {"recent_avg": "ewm", "last_3": "m3", "median_8": "med8"}


def fantasy_points(config: ScoringConfig, lines: pd.DataFrame) -> pd.Series:
    """Score every row of `lines` (columns are stat names) under `config`."""
    return pd.Series(
        [score_player_game(config, record) for record in lines.to_dict("records")],
        index=lines.index,
    )


def split_by_time(frame: pd.DataFrame, cutoff: pd.Timestamp) -> tuple[pd.Series, pd.Series]:
    """Boolean masks: games before `cutoff` (train) and on or after it (test)."""
    before = frame["start_time"] < cutoff
    return before, ~before


def baseline_lines(features: pd.DataFrame, stats: tuple[str, ...], kind: str) -> pd.DataFrame:
    suffix = BASELINES[kind]
    return pd.DataFrame({s: features[f"{s}__{suffix}"].fillna(0) for s in stats})


def _metrics(actual: pd.Series, predicted: pd.Series, groups: pd.Series) -> dict[str, float]:
    error = predicted - actual
    frame = pd.DataFrame({"a": actual, "p": predicted, "g": groups})
    rank = [
        g["a"].corr(g["p"], method="spearman")
        for _, g in frame.groupby("g")
        if len(g) >= 10 and g["a"].nunique() > 1 and g["p"].nunique() > 1
    ]
    return {
        "mae": float(error.abs().mean()),
        "rmse": float(np.sqrt((error**2).mean())),
        "bias": float(error.mean()),
        "rank_corr": float(np.nanmean(rank)) if rank else float("nan"),
    }


def compare(
    config: ScoringConfig,
    test: pd.DataFrame,
    predictions: Mapping[str, pd.DataFrame],
    stats: tuple[str, ...],
    group_column: str,
) -> pd.DataFrame:
    """One row per (position, method): MAE, RMSE, bias, weekly rank correlation, rows."""
    actual = fantasy_points(config, test[list(stats)])
    rows = []
    scored = {name: fantasy_points(config, lines) for name, lines in predictions.items()}
    for position, index in [("ALL", test.index)] + [
        (p, test.index[test["position"] == p]) for p in sorted(test["position"].unique())
    ]:
        for method, points in scored.items():
            m = _metrics(actual[index], points[index], test.loc[index, group_column])
            rows.append({"position": position, "method": method, "rows": len(index), **m})
    return pd.DataFrame(rows)


def stat_mae(
    test: pd.DataFrame, predictions: Mapping[str, pd.DataFrame], stats: tuple[str, ...]
) -> pd.DataFrame:
    """Per-stat MAE for each method, for spotting which stats the model helps with."""
    return pd.DataFrame(
        {
            method: {s: float((lines[s] - test[s]).abs().mean()) for s in stats}
            for method, lines in predictions.items()
        }
    )


def testable(features: pd.DataFrame) -> pd.DataFrame:
    return features[usable(features)]
