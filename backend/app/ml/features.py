"""Features for one player-game, built only from that player's *earlier* games.

For every stat the model predicts there are six summaries of the games before this one: a
decaying average (each game further back counts 0.8 as much, the same decay `history.py` uses for
spread), the last game, the last 3 games, the last 30 games, the median of the last 8 and their
standard deviation. The median is there
because one huge game shouldn't move a projection much. Every summary is computed on the series
shifted by one game, so a row never sees its own result or anything after it; `test_ml_features`
checks that directly.

`build_features` takes history rows (stats filled in) and, when projecting, target rows (stats
empty, one per player) stacked after them. A target row only ever reads the rows before it.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

DECAY = 0.8
MIN_PRIOR_GAMES = 3
_LONG_WINDOW = 30
_MEDIAN_WINDOW = 8
_REST_CAP_DAYS = 30
# Stable integer codes so a saved model and later serving agree on what a position means.
POSITION_CODES = {
    "QB": 0, "RB": 1, "WR": 2, "TE": 3,
    "PG": 10, "SG": 11, "SF": 12, "PF": 13, "C": 14, "G": 15, "F": 16, "GF": 17, "FC": 18,
}  # fmt: skip


def feature_names(stats: Sequence[str]) -> list[str]:
    names = []
    for stat in stats:
        names += [f"{stat}__ewm", f"{stat}__m3", f"{stat}__m30", f"{stat}__med8"]
        names += [f"{stat}__last", f"{stat}__std8"]
    return names + ["n_prior", "days_rest", "is_home", "position_code"]


def build_features(frame: pd.DataFrame, stats: Sequence[str]) -> pd.DataFrame:
    """`frame` plus feature columns. Rows must be sorted by player_id then start_time."""
    out = frame.copy()
    by_player = out["player_id"]
    columns: dict[str, pd.Series] = {}
    for stat in stats:
        prior = out.groupby("player_id", sort=False)[stat].shift(1)
        grouped = prior.groupby(by_player, sort=False)
        columns[f"{stat}__ewm"] = grouped.transform(lambda x: x.ewm(alpha=1 - DECAY).mean())
        columns[f"{stat}__m3"] = grouped.transform(lambda x: x.rolling(3, min_periods=1).mean())
        columns[f"{stat}__m30"] = grouped.transform(
            lambda x: x.rolling(_LONG_WINDOW, min_periods=1).mean()
        )
        columns[f"{stat}__med8"] = grouped.transform(
            lambda x: x.rolling(_MEDIAN_WINDOW, min_periods=1).median()
        )
        columns[f"{stat}__last"] = prior
        columns[f"{stat}__std8"] = grouped.transform(
            lambda x: x.rolling(_MEDIAN_WINDOW, min_periods=3).std()
        )
    out = pd.concat([out, pd.DataFrame(columns)], axis=1)
    out["n_prior"] = out.groupby("player_id", sort=False).cumcount().clip(upper=_LONG_WINDOW)
    days = out.groupby("player_id", sort=False)["start_time"].diff().dt.total_seconds() / 86400
    out["days_rest"] = days.clip(upper=_REST_CAP_DAYS)
    out["position_code"] = out["position"].map(POSITION_CODES).astype("float64")
    return out


def usable(frame: pd.DataFrame) -> pd.Series:
    """Rows with enough earlier games to have a meaningful projection."""
    return frame["n_prior"] >= MIN_PRIOR_GAMES


def as_matrix(frame: pd.DataFrame, stats: Sequence[str]) -> np.ndarray:
    return frame[feature_names(stats)].to_numpy(dtype="float64")
