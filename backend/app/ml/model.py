"""The per-stat gradient boosting model: train, predict, save, load.

One regressor per stat, so a prediction is a raw stat line and any league's `ScoringConfig` can
score it. Counting stats use a Poisson loss, which predicts the *expected* count (what scoring
needs, since points are linear in the stats) and never goes negative; yardage and minutes can be
any size or sign, so they use squared error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from app.ml.dataset import STATS
from app.ml.features import as_matrix, feature_names

MODEL_DIR = Path(__file__).resolve().parents[2] / "models"
_POSITION_COLUMN = "position_code"
_PARAMS: dict[str, Any] = {
    "learning_rate": 0.05,
    "max_iter": 250,
    "max_depth": 4,
    "min_samples_leaf": 40,
    "l2_regularization": 1.0,
    "random_state": 0,
}


def _loss(stat: str) -> str:
    return "squared_error" if stat == "minutes" or stat.endswith("_yards") else "poisson"


# How much of the prediction is the gradient boosting model; the rest is the decaying average.
# NBA has enough history (about 40k training rows) for the model to beat the average on its own.
# NFL has about 5k, and unshrunk the model did no better than the average on held-out games, so
# half of it is the average. Chosen from the held-out comparison in `evaluate.py`.
MODEL_WEIGHT = {"NBA": 1.0, "NFL": 0.5}


@dataclass
class SportModel:
    sport: str
    regressors: dict[str, HistGradientBoostingRegressor]
    trained_through: str
    n_rows: int
    metrics: dict[str, Any] = field(default_factory=dict)

    def predict(self, features: pd.DataFrame) -> pd.DataFrame:
        """Expected stat line for each row of `features` (as built by `build_features`)."""
        matrix = as_matrix(features, tuple(self.regressors))
        weight = MODEL_WEIGHT[self.sport]
        predictions = {}
        for stat, reg in self.regressors.items():
            raw = reg.predict(matrix)
            if _loss(stat) == "poisson":
                raw = np.clip(raw, 0, None)
            average = features[f"{stat}__ewm"].fillna(0).to_numpy()
            predictions[stat] = weight * raw + (1 - weight) * average
        return pd.DataFrame(predictions, index=features.index)


def train(sport: str, features: pd.DataFrame) -> dict[str, HistGradientBoostingRegressor]:
    """Fit one regressor per stat on `features` (rows that already have a result)."""
    stats = STATS[sport]
    matrix = as_matrix(features, stats)
    categorical = [feature_names(stats).index(_POSITION_COLUMN)]
    regressors = {}
    for stat in stats:
        reg = HistGradientBoostingRegressor(
            loss=_loss(stat), categorical_features=categorical, **_PARAMS
        )
        regressors[stat] = reg.fit(matrix, features[stat].to_numpy(dtype="float64"))
    return regressors


def save(model: SportModel, directory: Path = MODEL_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{model.sport.lower()}.joblib"
    joblib.dump(model, path)
    return path


def load(sport: str, directory: Path = MODEL_DIR) -> SportModel | None:
    path = directory / f"{sport.lower()}.joblib"
    return joblib.load(path) if path.exists() else None


_cache: dict[str, tuple[float, SportModel]] = {}


def load_cached(sport: str, directory: Path = MODEL_DIR) -> SportModel | None:
    """`load`, but reading the file again only when it has been retrained since."""
    path = directory / f"{sport.lower()}.joblib"
    if not path.exists():
        return None
    modified = path.stat().st_mtime
    cached = _cache.get(str(path))
    if cached is None or cached[0] != modified:
        cached = (modified, joblib.load(path))
        _cache[str(path)] = cached
    return cached[1]
