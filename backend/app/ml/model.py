"""The per-stat gradient boosting model: train, predict, save, load.

One regressor per stat, so a prediction is a raw stat line and any league's `ScoringConfig` can
score it. Counting stats use a Poisson loss, which predicts the *expected* count (what scoring
needs, since points are linear in the stats) and never goes negative; yardage and minutes can be
any size or sign, so they use squared error.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge

from app.core.config import get_settings
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


# A first-choice backup behind a newly out starter is projected to fill at least
# `projection_first_choice_share` of the way from his own usual workload to the starter's (see
# config.py). It is a chosen setting, not a fitted one, and leans towards Sleeper, whose projections
# put such backups in the starter's role: in past games they took about two thirds of the gap, so
# the higher the setting the more it overshoots history. The NFL only; the NBA keeps what the model
# learned.
_FLOORED_SPORTS = {"NFL"}
# The workload stat that is floored, and the stats that move with it in proportion.
_ROLE_STATS = {
    "rushing_attempts": ("rushing_yards", "rushing_touchdowns"),
    "receiving_targets": ("receptions", "receiving_yards", "receiving_touchdowns"),
    "passing_attempts": (
        "passing_completions",
        "passing_yards",
        "passing_touchdowns",
        "interceptions",
    ),
}


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
        lines = pd.DataFrame(predictions, index=features.index)
        return self._fill_the_starters_role(lines, features)

    def _fill_the_starters_role(self, lines: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
        """Raise a first-choice backup's workload to the configured share of the way to the
        starter's, and scale the stats that follow from it (yards, touchdowns) alike."""
        share = get_settings().projection_first_choice_share
        if self.sport not in _FLOORED_SPORTS or share <= 0:
            return lines
        lines = lines.copy()
        for load, followers in _ROLE_STATS.items():
            gap = features.get(f"top_gap__{load}")
            if load not in lines or gap is None:
                continue
            target = features[f"{load}__ewm"].fillna(0) + share * gap.fillna(0)
            floored = np.maximum(lines[load], target)
            factor = np.divide(floored, lines[load], out=np.ones(len(lines)), where=lines[load] > 0)
            lines[load] = floored
            for stat in followers:
                if stat in lines:
                    lines[stat] = lines[stat] * factor
        return lines


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
        for kind in ("inherit", "new_inherit", "top_new_inherit", "top_gap", "ret")
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


def dump_atomic(obj: Any, path: Path) -> Path:
    """Write `obj` to `path` in one step: to a temporary file beside it, then renamed over it, so
    the API never reads a half-written model (it reloads when the file's mtime changes)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            joblib.dump(obj, handle)
        os.chmod(tmp, 0o644)  # mkstemp makes it owner-only
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def save(model: SportModel, directory: Path = MODEL_DIR) -> Path:
    return dump_atomic(model, directory / f"{model.sport.lower()}.joblib")


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
