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
from sklearn.linear_model import Ridge

from app.ml.dataset import STATS
from app.ml.features import as_matrix, context_stats, feature_names

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


_RIDGE_ALPHA = 5.0


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
    adjusters: dict[str, Ridge] = field(default_factory=dict)

    def base_lines(self, features: pd.DataFrame) -> pd.DataFrame:
        """The decaying average of each stat, moved by what teammates being out or back implies."""
        context = _context_matrix(features, tuple(self.regressors))
        lines = {}
        for stat in self.regressors:
            base = features[f"{stat}__ewm"].fillna(0).to_numpy()
            if stat in self.adjusters:
                base = base + context @ self.adjusters[stat].coef_
            lines[stat] = np.clip(base, 0, None) if _loss(stat) == "poisson" else base
        return pd.DataFrame(lines, index=features.index)

    def predict(self, features: pd.DataFrame) -> pd.DataFrame:
        """Expected stat line for each row of `features` (as built by `build_features`)."""
        matrix = as_matrix(features, tuple(self.regressors))
        weight = MODEL_WEIGHT[self.sport]
        base = self.base_lines(features)
        predictions = {}
        for stat, reg in self.regressors.items():
            raw = reg.predict(matrix)
            if _loss(stat) == "poisson":
                raw = np.clip(raw, 0, None)
            predictions[stat] = weight * raw + (1 - weight) * base[stat].to_numpy()
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


def _context_features(stats: tuple[str, ...]) -> list[str]:
    chosen = context_stats(stats)
    return [
        f"{kind}__{s}"
        for s in chosen
        for kind in ("inherit", "new_inherit", "top_new_inherit", "ret")
    ]


def _context_matrix(features: pd.DataFrame, stats: tuple[str, ...]) -> np.ndarray:
    """The teammate features, with no team context (a traded player's old game) as no news."""
    return features[_context_features(stats)].fillna(0).to_numpy(dtype="float64")


def train_adjusters(sport: str, features: pd.DataFrame) -> dict[str, Ridge]:
    """For each stat, how much its change from the decaying average follows the teammate features.

    A handful of coefficients per stat, pooled over every player, so they can be learned from the
    few games where a starter was out, which a tree model with hundreds of splits cannot. Only the
    coefficients are used (no intercept): with no teammate news the average is left alone."""
    stats = STATS[sport]
    context = _context_matrix(features, stats)
    adjusters = {}
    for stat in stats:
        residual = features[stat].to_numpy(dtype="float64") - features[f"{stat}__ewm"].fillna(0)
        adjusters[stat] = Ridge(alpha=_RIDGE_ALPHA).fit(context, residual.to_numpy())
    return adjusters


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
