"""The kicker model (NFL): how many extra points and field goals, from which distances, a kicker
will try in a game, and how many of them he will make.

A kicker's day is mostly his team's: how often it scores touchdowns (extra points) and how often
its drives stall in range (field goals, by distance). So attempts are modelled per *team*, from the
team's own recent kicking, its recent scoring, the opponent's recent points allowed, and home or
away. Only about a thousand team-games exist, so each target is a ridge regression with its
strength chosen by cross-validation, not trees. A game where the team didn't kick at all is left
out of the history rather than counted as zeros: a projection is for a kicker who kicks.

Whether a kick goes in is a different question, and one a kicker's own record says little about
over so few kicks: his make rate in each distance range is his earlier makes and misses blended
with the league's rate for that range, which counts for as many kicks as `FG_RATE_WEIGHT`. The
expected kicks come out in the same distance ranges Sleeper projects, so any league's by-distance
scoring applies.

As with the other models, features use only games before the one predicted, and the model predicts
raw stats. Train and evaluate with `python -m app.ml.train_kicker`.
"""

from __future__ import annotations

from collections.abc import Mapping
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
from app.services.projections.base import KickBucket
from app.services.projections.expected_scoring import score_expected_player
from app.services.scoring import ScoringConfig, score_player_game

# Sleeper's distance ranges (inclusive); a bucket's kicks are treated as evenly spread over it.
BUCKETS = {
    "0_19": (0, 19),
    "20_29": (20, 29),
    "30_39": (30, 39),
    "40_49": (40, 49),
    "50p": (50, 65),
}
ATTEMPTS = ("xpa", *(f"fga_{b}" for b in BUCKETS))
_WINDOW = 8
_ALPHAS = (1.0, 10.0, 30.0, 100.0, 300.0, 1000.0, 3000.0)
# How many kicks of league-average evidence a kicker's own record is blended with.
FG_RATE_WEIGHT = 20.0
XP_RATE_WEIGHT = 40.0
FILE = "nfl_kicker.joblib"


def bucket_of(distance: int) -> str:
    for name, (_, high) in BUCKETS.items():
        if distance <= high:
            return name
    return "50p"


def feature_names() -> list[str]:
    own = [f"{s}__{kind}" for s in (*ATTEMPTS, "fga") for kind in ("ewm", "m8")]
    return own + [
        "own_points_scored__ewm",
        "opp_points_allowed__ewm",
        "is_home",
        "days_rest",
        "n_prior",
    ]


# --- Loading -----------------------------------------------------------------------------------


@dataclass
class KickerHistory:
    """Every finished NFL game's kicking, as the model reads it.

    `team_games`: one row per team per game (team_id, opponent_id, game_id, start_time, season,
    week, is_home, points_scored, points_allowed, and the ATTEMPTS plus `fga`).
    `kicker_games`: one row per kicker per game he kicked in (player_id, team_id, game_id,
    start_time, xpa, xpm, att_<bucket>, made_<bucket>).
    `kicks`: every field goal attempt (player_id, game_id, distance, result)."""

    team_games: pd.DataFrame
    kicker_games: pd.DataFrame
    kicks: pd.DataFrame


_TEAM_SQL = """
    SELECT t.team_id, o.team_id AS opponent_id, g.id AS game_id, g.start_time, g.season, g.week,
           CASE WHEN t.team_id = g.home_team_id THEN 1 ELSE 0 END AS is_home,
           o.points_allowed AS points_scored, t.points_allowed AS points_allowed
    FROM team_game_stats_nfl t
    JOIN games g ON g.id = t.game_id
    JOIN team_game_stats_nfl o ON o.game_id = g.id AND o.team_id <> t.team_id
    WHERE g.sport = 'NFL' AND g.status = 'final' AND g.stats_final
"""
_STATS_SQL = """
    SELECT s.player_id, s.game_id, s.extra_point_attempts AS xpa, s.extra_points_made AS xpm
    FROM player_game_stats_nfl s
    JOIN games g ON g.id = s.game_id
    WHERE g.sport = 'NFL' AND g.status = 'final' AND g.stats_final
      AND (s.field_goal_attempts > 0 OR s.extra_point_attempts > 0)
"""
_KICKS_SQL = """
    SELECT k.player_id, k.game_id, k.distance, k.result
    FROM field_goal_kicks k
    JOIN games g ON g.id = k.game_id
    WHERE g.sport = 'NFL' AND g.status = 'final' AND g.stats_final
"""


def _assign_teams(rows: pd.DataFrame) -> pd.DataFrame:
    """The team each kicker row was for. The roster sync only knows a player's *current* team, so
    that team is used when it played in the game; a kicker who has since moved takes the game's one
    team that has no kicker yet, and is left out if that's not unambiguous."""
    teams: dict[int, int] = {}
    for _, group in rows.groupby("game_id", sort=False):
        sides = {int(group.iloc[0]["home_team_id"]), int(group.iloc[0]["away_team_id"])}
        chosen: dict[int, int] = {}
        for index, row in group.iterrows():
            current = row["current_team"]
            if pd.notna(current) and int(current) in sides and int(current) not in chosen.values():
                chosen[index] = int(current)
        rest = [i for i in group.index if i not in chosen]
        free = sides - set(chosen.values())
        if len(rest) == 1 and len(free) == 1:
            chosen[rest[0]] = next(iter(free))
        teams.update(chosen)
    assigned = rows[rows.index.isin(teams)]
    return assigned.assign(team_id=assigned.index.map(teams)).astype({"team_id": "int64"})


def _bucket_counts(group: pd.DataFrame) -> pd.Series:
    """One kicker-game's attempts and makes in each distance range."""
    counts = {}
    for name in BUCKETS:
        in_range = group["bucket"] == name
        counts[f"att_{name}"] = float(in_range.sum())
        counts[f"made_{name}"] = float((in_range & group["made"]).sum())
    return pd.Series(counts)


def load_history(conn: Connection) -> KickerHistory:
    team = pd.read_sql(text(_TEAM_SQL), conn)
    team["week"] = team["week"].astype("float64")
    stats = pd.read_sql(text(_STATS_SQL), conn)
    kicks = pd.read_sql(text(_KICKS_SQL), conn)

    kicks = kicks.assign(bucket=kicks["distance"].map(bucket_of), made=(kicks["result"] == "made"))
    per_game = (
        kicks.groupby(["player_id", "game_id"])
        .apply(_bucket_counts, include_groups=False)
        .reset_index()
        if not kicks.empty
        else pd.DataFrame(columns=["player_id", "game_id"])
    )

    rows = stats.merge(per_game, on=["player_id", "game_id"], how="outer")
    counted = [c for c in rows.columns if c not in ("player_id", "game_id")]
    rows[counted] = rows[counted].fillna(0.0)
    if rows.empty:
        return KickerHistory(_empty_team_games(team), _empty_kicker_games(), kicks)

    players = pd.read_sql(
        text("SELECT id AS player_id, team_id AS current_team FROM players"), conn
    )
    games = pd.read_sql(
        text("SELECT id AS game_id, start_time, home_team_id, away_team_id FROM games"), conn
    )
    rows = rows.merge(players, on="player_id", how="left").merge(games, on="game_id", how="left")
    kicker_games = _assign_teams(rows.reset_index(drop=True)).drop(
        columns=["current_team", "home_team_id", "away_team_id"]
    )
    kicker_games = kicker_games.sort_values(["player_id", "start_time"]).reset_index(drop=True)

    # Each team's kicking per game; a game with no kicker row is one with no kicks at all.
    totals = kicker_games.groupby(["team_id", "game_id"])[
        ["xpa", *(f"att_{b}" for b in BUCKETS)]
    ].sum()
    totals = totals.rename(columns={f"att_{b}": f"fga_{b}" for b in BUCKETS}).reset_index()
    team = team.merge(totals, on=["team_id", "game_id"], how="left")
    team[list(ATTEMPTS)] = team[list(ATTEMPTS)].fillna(0.0)
    team["fga"] = team[[f"fga_{b}" for b in BUCKETS]].sum(axis=1)
    # A game with no kick at all is no kicker's day: it is left empty, not counted as zeros, so a
    # projection (like Sleeper's, and like the player models') is for a kicker who kicks.
    team.loc[(team["xpa"] == 0) & (team["fga"] == 0), [*ATTEMPTS, "fga"]] = np.nan
    team = team.sort_values(["team_id", "start_time"]).reset_index(drop=True)
    return KickerHistory(team, kicker_games, kicks)


def _empty_kicker_games() -> pd.DataFrame:
    columns = ["player_id", "game_id", "team_id", "start_time", "xpa", "xpm"]
    columns += [f"{kind}_{b}" for kind in ("att", "made") for b in BUCKETS]
    return pd.DataFrame(
        {c: pd.Series(dtype="datetime64[ns]" if c == "start_time" else "float64") for c in columns}
    )


def _empty_team_games(team: pd.DataFrame) -> pd.DataFrame:
    out = team.copy()
    for column in (*ATTEMPTS, "fga"):
        out[column] = np.nan
    return out.sort_values(["team_id", "start_time"]).reset_index(drop=True)


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
    for stat in (*ATTEMPTS, "fga", "points_scored", "points_allowed"):
        prior = out.groupby("team_id", sort=False)[stat].shift(1)
        grouped = prior.groupby(by_team, sort=False)
        ewm = grouped.transform(lambda x: x.ewm(alpha=1 - DECAY).mean())
        if stat in ("points_scored", "points_allowed"):
            columns[f"own_{stat}__ewm"] = ewm
        else:
            columns[f"{stat}__ewm"] = ewm
            columns[f"{stat}__m8"] = grouped.transform(
                lambda x: x.rolling(_WINDOW, min_periods=1).mean()
            )
    out = pd.concat([out, pd.DataFrame(columns)], axis=1)
    out["n_prior"] = out.groupby("team_id", sort=False).cumcount()
    days = out.groupby("team_id", sort=False)["start_time"].diff().dt.total_seconds() / 86400
    out["days_rest"] = days.clip(upper=30)
    # How many points the opponent has been giving up: their row in the same game, by id.
    allowed = out[["game_id", "team_id", "own_points_allowed__ewm"]].rename(
        columns={"team_id": "opponent_id", "own_points_allowed__ewm": "opp_points_allowed__ewm"}
    )
    return (
        out.merge(allowed, on=["game_id", "opponent_id"], how="left")
        .sort_values(["team_id", "start_time"], kind="stable")
        .reset_index(drop=True)
    )


def usable(frame: pd.DataFrame) -> pd.Series:
    return frame["n_prior"] >= MIN_PRIOR_GAMES


# --- Make rates and the expected line ----------------------------------------------------------


@dataclass(frozen=True)
class LeagueRates:
    """How often kicks go in across the league: by distance range, and extra points."""

    field_goal: dict[str, float]
    extra_point: float


def league_rates(kicker_games: pd.DataFrame) -> LeagueRates:
    """The league's make rates over `kicker_games`."""
    if kicker_games.empty:
        return LeagueRates({b: 0.8 for b in BUCKETS}, 0.95)
    field_goal = {}
    for name in BUCKETS:
        attempts = kicker_games[f"att_{name}"].sum()
        field_goal[name] = float(kicker_games[f"made_{name}"].sum() / attempts) if attempts else 0.8
    xpa = kicker_games["xpa"].sum()
    return LeagueRates(field_goal, float(kicker_games["xpm"].sum() / xpa) if xpa else 0.95)


def kicker_rates(prior: pd.DataFrame, league: LeagueRates) -> LeagueRates:
    """A kicker's make rates: his earlier games (`prior`) blended with the league's."""
    field_goal = {
        name: float(
            (prior[f"made_{name}"].sum() + FG_RATE_WEIGHT * league.field_goal[name])
            / (prior[f"att_{name}"].sum() + FG_RATE_WEIGHT)
        )
        for name in BUCKETS
    }
    extra_point = float(
        (prior["xpm"].sum() + XP_RATE_WEIGHT * league.extra_point)
        / (prior["xpa"].sum() + XP_RATE_WEIGHT)
    )
    return LeagueRates(field_goal, extra_point)


def expected_line(
    attempts: Mapping[str, float], rates: LeagueRates
) -> tuple[dict[str, float], list[KickBucket]]:
    """The expected stat line and field goals by distance, from expected attempts and make rates."""
    kicks = []
    for name, (low, high) in BUCKETS.items():
        tried = float(attempts[f"fga_{name}"])
        made = tried * rates.field_goal[name]
        kicks.append(KickBucket(low, high, made, tried - made))
    xpa = float(attempts["xpa"])
    stats = {
        "field_goal_attempts": sum(k.made + k.missed for k in kicks),
        "field_goals_made": sum(k.made for k in kicks),
        "extra_point_attempts": xpa,
        "extra_points_made": xpa * rates.extra_point,
    }
    return stats, kicks


# --- The model ---------------------------------------------------------------------------------


@dataclass
class KickerModel:
    regressors: dict[str, Any]
    league: LeagueRates
    trained_through: str
    n_rows: int
    metrics: dict[str, Any] = field(default_factory=dict)

    def predict(self, features: pd.DataFrame) -> pd.DataFrame:
        """Each row's expected attempts: extra points and field goals by distance range."""
        matrix = features[feature_names()].to_numpy(dtype="float64")
        return pd.DataFrame(
            {s: np.clip(self.regressors[s].predict(matrix), 0, None) for s in ATTEMPTS},
            index=features.index,
        )


def train(features: pd.DataFrame) -> dict[str, Any]:
    matrix = features[feature_names()].to_numpy(dtype="float64")
    return {
        stat: make_pipeline(
            SimpleImputer(strategy="mean"), StandardScaler(), RidgeCV(alphas=_ALPHAS)
        ).fit(matrix, features[stat].to_numpy(dtype="float64"))
        for stat in ATTEMPTS
    }


def save(model: KickerModel, directory: Path = MODEL_DIR) -> Path:
    return dump_atomic(model, directory / FILE)


def load(directory: Path = MODEL_DIR) -> KickerModel | None:
    path = directory / FILE
    return joblib.load(path) if path.exists() else None


_cache: dict[str, tuple[float, KickerModel]] = {}


def load_cached(directory: Path = MODEL_DIR) -> KickerModel | None:
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


def with_prior_totals(kicker_games: pd.DataFrame) -> pd.DataFrame:
    """`kicker_games` plus, for each row, the kicker's totals over his *earlier* games."""
    counted = ["xpa", "xpm", *(f"att_{b}" for b in BUCKETS), *(f"made_{b}" for b in BUCKETS)]
    ordered = kicker_games.sort_values(["player_id", "start_time"]).copy()
    totals = ordered.groupby("player_id")[counted].cumsum() - ordered[counted]
    return ordered.join(totals.add_prefix("prior_"))


def _prior_rates(row: Mapping[str, float], league: LeagueRates) -> LeagueRates:
    prior = pd.DataFrame([{k.removeprefix("prior_"): v for k, v in row.items() if "prior_" in k}])
    return kicker_rates(prior, league)


def _actual_points(
    config: ScoringConfig, game: Mapping[str, Any], kicks: list[tuple[int, str]]
) -> float:
    fga = sum(game[f"att_{b}"] for b in BUCKETS)
    fgm = sum(game[f"made_{b}"] for b in BUCKETS)
    stats = {
        "field_goal_attempts": fga,
        "field_goals_made": fgm,
        "extra_point_attempts": game["xpa"],
        "extra_points_made": game["xpm"],
    }
    return score_player_game(config, stats, kicks)


def compare(
    config: ScoringConfig,
    test: pd.DataFrame,
    kicks: pd.DataFrame,
    league: LeagueRates,
    predictions: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """MAE, RMSE and bias in fantasy points per method over `test`: kicker-games joined to the
    team's features and the kicker's earlier totals. `predictions` map a method to expected
    attempts per test row (same index)."""
    by_game: dict[tuple[int, int], list[tuple[int, str]]] = {}
    for k in kicks.itertuples(index=False):
        by_game.setdefault((k.player_id, k.game_id), []).append((k.distance, k.result))
    rows = test.to_dict("records")
    actual = pd.Series(
        [_actual_points(config, r, by_game.get((r["player_id"], r["game_id"]), [])) for r in rows],
        index=test.index,
    )
    rates = [_prior_rates(r, league) for r in rows]
    table = []
    for method, attempts in predictions.items():
        expected = pd.Series(
            [
                score_expected_player(config, *expected_line(a, rate)).points
                for a, rate in zip(attempts.to_dict("records"), rates, strict=True)
            ],
            index=test.index,
        )
        error = expected - actual
        table.append(
            {
                "method": method,
                "rows": len(test),
                "mae": float(error.abs().mean()),
                "rmse": float(np.sqrt((error**2).mean())),
                "bias": float(error.mean()),
            }
        )
    return pd.DataFrame(table)


def default_cutoff(frame: pd.DataFrame) -> pd.Timestamp:
    """Week 11 of the 2025 season, like the other NFL models' split."""
    return frame[(frame["season"] == "2025") & (frame["week"] == 11)]["start_time"].min()
