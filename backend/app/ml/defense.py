"""The team defense model (NFL): how many sacks, takeaways and points a defense will get in a game.

A defense's stat line is mostly luck from game to game (about 2.3 sacks a game with a spread of
1.6; a touchdown on one game in seventeen), so there is little to learn from a defense's own
recent games and plenty of shrinking towards the league's typical game to do. What does carry
signal is the opponent: a team that scores 30 a game and gives the ball away a lot makes a
different day for a defense than one that scores 14. So each game's features are the defense's own
recent averages, the opponent's recent offense (points scored, sacks taken, giveaways, all read
from the same team table by pairing the two teams' rows), and home or away.

There are only about a thousand team-games, so the model is a ridge regression per stat with its
strength chosen by cross-validation, not trees. As with the player model, features use only games
before the one predicted (shifted by one game). It predicts raw stats, so any league's scoring
applies, and points allowed is scored by bracket in `score_expected_defense`.

Train and evaluate with `python -m app.ml.train_defense` (kept in its own module so the saved
model's class lives here, not in `__main__`, and loads anywhere).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import RidgeCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.ml.features import DECAY, MIN_PRIOR_GAMES
from app.ml.model import MODEL_DIR, dump_atomic
from app.services.projections.expected_scoring import score_expected_defense
from app.services.scoring import ScoringConfig, score_defense_game

STATS = (
    "sacks",
    "interceptions",
    "fumble_recoveries",
    "defensive_touchdowns",
    "return_touchdowns",
    "safeties",
    "blocked_kicks",
    "fourth_down_stops",
    "points_allowed",
)
# What a team's offense did, read from the opponent's defensive row in the same game.
OFFENSE = ("points_scored", "sacks_taken", "giveaways")
_MEDIAN_WINDOW = 8
_LONG_WINDOW = 8
_ALPHAS = (1.0, 10.0, 30.0, 100.0, 300.0, 1000.0, 3000.0)
FILE = "nfl_defense.joblib"


def feature_names() -> list[str]:
    own = [f"{s}__{kind}" for s in STATS for kind in ("ewm", "m8")]
    opponent = [f"opp_{s}__ewm" for s in OFFENSE]
    return own + opponent + ["is_home", "days_rest", "n_prior"]


def load_history(conn: Connection) -> pd.DataFrame:
    """Every finished game's defensive line per team, with what that team's offense did (from the
    opponent's row), oldest first. Columns: team_id, opponent_id, game_id, start_time, season,
    week, is_home, STATS, OFFENSE."""
    stats = ", ".join(f"t.{s}" for s in STATS)
    query = text(
        f"""
        SELECT t.team_id, o.team_id AS opponent_id, g.id AS game_id, g.start_time, g.season,
               g.week, CASE WHEN t.team_id = g.home_team_id THEN 1 ELSE 0 END AS is_home,
               {stats},
               o.points_allowed AS points_scored, o.sacks AS sacks_taken,
               o.interceptions + o.fumble_recoveries AS giveaways
        FROM team_game_stats_nfl t
        JOIN games g ON g.id = t.game_id
        JOIN team_game_stats_nfl o ON o.game_id = g.id AND o.team_id <> t.team_id
        WHERE g.sport = 'NFL' AND g.status = 'final' AND g.stats_final
        """
    )
    frame = pd.read_sql(query, conn)
    frame["week"] = frame["week"].astype("float64")
    return frame.sort_values(["team_id", "start_time"]).reset_index(drop=True)


def upcoming_rows(games: pd.DataFrame) -> pd.DataFrame:
    """Two empty rows (one per team) for each game still to be played, to stack after the history.
    `games`: game_id, start_time, season, week, home_id, away_id."""
    rows = []
    for g in games.itertuples(index=False):
        for team, opponent, home in ((g.home_id, g.away_id, 1), (g.away_id, g.home_id, 0)):
            rows.append(
                {
                    "team_id": team,
                    "opponent_id": opponent,
                    "game_id": g.game_id,
                    "start_time": g.start_time,
                    "season": g.season,
                    "week": float(g.week) if g.week is not None else np.nan,
                    "is_home": home,
                }
            )
    return pd.DataFrame(rows)


def build_features(frame: pd.DataFrame) -> pd.DataFrame:
    """`frame` (sorted by team then time; upcoming games' rows may have empty stats) plus features
    built only from each team's earlier games."""
    out = frame.copy()
    by_team = out["team_id"]
    columns: dict[str, pd.Series] = {}
    for stat in (*STATS, *OFFENSE):
        prior = out.groupby("team_id", sort=False)[stat].shift(1)
        grouped = prior.groupby(by_team, sort=False)
        ewm = grouped.transform(lambda x: x.ewm(alpha=1 - DECAY).mean())
        if stat in STATS:
            columns[f"{stat}__ewm"] = ewm
            columns[f"{stat}__m8"] = grouped.transform(
                lambda x: x.rolling(_LONG_WINDOW, min_periods=1).mean()
            )
        if stat in OFFENSE:
            columns[f"off_{stat}__ewm"] = ewm
    out = pd.concat([out, pd.DataFrame(columns)], axis=1)
    out["n_prior"] = out.groupby("team_id", sort=False).cumcount()
    days = out.groupby("team_id", sort=False)["start_time"].diff().dt.total_seconds() / 86400
    out["days_rest"] = days.clip(upper=30)
    # The opponent's offense before this game: their row in the same game, by id.
    offense = out[["game_id", "team_id", *[f"off_{s}__ewm" for s in OFFENSE]]].rename(
        columns={"team_id": "opponent_id", **{f"off_{s}__ewm": f"opp_{s}__ewm" for s in OFFENSE}}
    )
    return (
        out.merge(offense, on=["game_id", "opponent_id"], how="left")
        .sort_values(["team_id", "start_time"], kind="stable")
        .reset_index(drop=True)
    )


def usable(frame: pd.DataFrame) -> pd.Series:
    return frame["n_prior"] >= MIN_PRIOR_GAMES


@dataclass
class DefenseModel:
    regressors: dict[str, Any]
    trained_through: str
    n_rows: int
    metrics: dict[str, Any] = field(default_factory=dict)

    def predict(self, features: pd.DataFrame) -> pd.DataFrame:
        """The expected stat line of each row of `features`."""
        matrix = features[feature_names()].to_numpy(dtype="float64")
        return pd.DataFrame(
            {s: np.clip(self.regressors[s].predict(matrix), 0, None) for s in STATS},
            index=features.index,
        )


def train(features: pd.DataFrame) -> dict[str, Any]:
    matrix = features[feature_names()].to_numpy(dtype="float64")
    return {
        stat: make_pipeline(
            SimpleImputer(strategy="mean"), StandardScaler(), RidgeCV(alphas=_ALPHAS)
        ).fit(matrix, features[stat].to_numpy(dtype="float64"))
        for stat in STATS
    }


def save(model: DefenseModel, directory: Path = MODEL_DIR) -> Path:
    return dump_atomic(model, directory / FILE)


def load(directory: Path = MODEL_DIR) -> DefenseModel | None:
    path = directory / FILE
    return joblib.load(path) if path.exists() else None


_cache: dict[str, tuple[float, DefenseModel]] = {}


def load_cached(directory: Path = MODEL_DIR) -> DefenseModel | None:
    """The saved model, read again only when it has been retrained since."""
    path = directory / FILE
    if not path.exists():
        return None
    modified = path.stat().st_mtime
    cached = _cache.get(str(path))
    if cached is None or cached[0] != modified:
        cached = (modified, joblib.load(path))
        _cache[str(path)] = cached
    return cached[1]


# --- Evaluation --------------------------------------------------------------------------------


def expected_points(config: ScoringConfig, lines: pd.DataFrame) -> pd.Series:
    return pd.Series(
        [score_expected_defense(config, r).points for r in lines.to_dict("records")],
        index=lines.index,
    )


def actual_points(config: ScoringConfig, lines: pd.DataFrame) -> pd.Series:
    return pd.Series(
        [score_defense_game(config, r) for r in lines.to_dict("records")], index=lines.index
    )


def compare(
    config: ScoringConfig, test: pd.DataFrame, predictions: dict[str, pd.DataFrame]
) -> pd.DataFrame:
    """MAE, RMSE and bias in fantasy points for each method on the test games."""
    actual = actual_points(config, test[list(STATS)])
    rows = []
    for method, lines in predictions.items():
        error = expected_points(config, lines) - actual
        rows.append(
            {
                "method": method,
                "rows": len(test),
                "mae": float(error.abs().mean()),
                "rmse": float(np.sqrt((error**2).mean())),
                "bias": float(error.mean()),
            }
        )
    return pd.DataFrame(rows)


def default_cutoff(frame: pd.DataFrame) -> pd.Timestamp:
    """Week 11 of the 2025 season, like the player model's NFL split."""
    return frame[(frame["season"] == "2025") & (frame["week"] == 11)]["start_time"].min()
