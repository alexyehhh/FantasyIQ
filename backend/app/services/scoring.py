"""Fantasy scoring.

A league's scoring is data, not code: a `ScoringConfig` says what each stat is worth, and the
functions here apply it. Nothing in this module knows about any one league, so the same code
scores the FantasyIQ default, a hand-entered custom league, or (later) a linked Yahoo league.

A config has four parts:

- `player_weights`: points per unit of a player's stat line (keys are the stat column names on
  PlayerGameStats / PlayerGameStatsNFL, plus derived misses such as `extra_points_missed`).
- `field_goal_made` / `field_goal_missed`: brackets over each kick's distance, for leagues that
  score kickers by distance. A blocked kick counts as a miss.
- `defense_weights`: points per unit of a team defense line (columns of TeamGameStatsNFL).
- `points_allowed`: brackets over the defense's points allowed in a game.

A bracket is an inclusive range of whole numbers with an open end allowed (`0-19`, `35+`).
A value that falls in no bracket scores nothing.

The same config also builds the SQL expressions that rank whole seasons of players
(`player_points_expression`, `bracket_case`), so the Python and SQL scorers are one definition
and tests pin them to each other.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from functools import reduce
from operator import add
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, case, literal, true
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import PlayerGameStats, PlayerGameStatsNFL, TeamGameStatsNFL

Sport = Literal["NBA", "NFL"]

_ROW_COLUMNS = {"id", "player_id", "game_id", "team_id", "created_at"}
_PLAYER_MODELS: dict[str, Any] = {"NBA": PlayerGameStats, "NFL": PlayerGameStatsNFL}

# Misses aren't stored; leagues that score them get them as attempts minus makes.
# stat name -> (attempts column, made column)
_DERIVED_MISSES: dict[str, dict[str, tuple[str, str]]] = {
    "NBA": {
        "field_goals_missed": ("field_goal_attempts", "field_goals_made"),
        "three_pointers_missed": ("three_point_attempts", "three_pointers_made"),
        "free_throws_missed": ("free_throw_attempts", "free_throws_made"),
    },
    "NFL": {
        "passing_incompletions": ("passing_attempts", "passing_completions"),
        "field_goals_missed": ("field_goal_attempts", "field_goals_made"),
        "extra_points_missed": ("extra_point_attempts", "extra_points_made"),
    },
}


def _columns(model: Any) -> set[str]:
    return set(model.__table__.columns.keys()) - _ROW_COLUMNS


def player_stat_names(sport: str) -> set[str]:
    """Every stat a `player_weights` key may name for this sport."""
    return _columns(_PLAYER_MODELS[sport]) | set(_DERIVED_MISSES[sport])


# points_allowed is scored by bracket, not per unit.
DEFENSE_STAT_NAMES = _columns(TeamGameStatsNFL) - {"points_allowed"}


class Bracket(BaseModel):
    """`points` for any value from `min` to `max`, both inclusive; None leaves that end open."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min: int | None = None
    max: int | None = None
    points: float

    @model_validator(mode="after")
    def _range_is_not_backwards(self) -> Bracket:
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"bracket minimum {self.min} is above its maximum {self.max}")
        return self

    def contains(self, value: float) -> bool:
        return (self.min is None or value >= self.min) and (self.max is None or value <= self.max)


def _check_no_overlap(name: str, brackets: tuple[Bracket, ...]) -> None:
    ordered = sorted(brackets, key=lambda b: float("-inf") if b.min is None else b.min)
    for earlier, later in zip(ordered, ordered[1:], strict=False):
        if earlier.max is None or (later.min is not None and later.min <= earlier.max):
            raise ValueError(f"{name} brackets overlap")
        if later.min is None:
            raise ValueError(f"{name} brackets overlap")


class ScoringConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    sport: Sport
    player_weights: Mapping[str, float] = Field(default_factory=dict)
    field_goal_made: tuple[Bracket, ...] = ()
    field_goal_missed: tuple[Bracket, ...] = ()
    defense_weights: Mapping[str, float] = Field(default_factory=dict)
    points_allowed: tuple[Bracket, ...] = ()

    @model_validator(mode="after")
    def _is_consistent(self) -> ScoringConfig:
        unknown = set(self.player_weights) - player_stat_names(self.sport)
        if unknown:
            raise ValueError(f"unknown {self.sport} player stats: {sorted(unknown)}")
        unknown = set(self.defense_weights) - DEFENSE_STAT_NAMES
        if unknown:
            raise ValueError(f"unknown defense stats: {sorted(unknown)}")
        if self.sport != "NFL" and (
            self.field_goal_made
            or self.field_goal_missed
            or self.defense_weights
            or self.points_allowed
        ):
            raise ValueError("kicker distance and team defense scoring are NFL only")
        for name in ("field_goal_made", "field_goal_missed", "points_allowed"):
            _check_no_overlap(name, getattr(self, name))
        return self


# The FantasyIQ default. The kicker and defense values are one real Yahoo league's settings,
# used as the default because they are the only real data we have.
_NFL_PLAYER_WEIGHTS = {
    "passing_yards": 0.04,
    "passing_touchdowns": 4,
    "interceptions": -2,
    "rushing_yards": 0.1,
    "rushing_touchdowns": 6,
    "receptions": 1,
    "receiving_yards": 0.1,
    "receiving_touchdowns": 6,
    "fumbles_lost": -2,
    "kick_return_touchdowns": 6,
    "punt_return_touchdowns": 6,
    "extra_points_made": 1,
    "extra_points_missed": -1,
}

DEFAULT_CONFIGS: dict[str, ScoringConfig] = {
    "NBA": ScoringConfig(
        name="FantasyIQ standard",
        sport="NBA",
        player_weights={
            "points": 1,
            "rebounds": 1.2,
            "assists": 1.5,
            "steals": 3,
            "blocks": 3,
            "turnovers": -1,
        },
    ),
    "NFL": ScoringConfig(
        name="FantasyIQ standard (PPR)",
        sport="NFL",
        player_weights=_NFL_PLAYER_WEIGHTS,
        field_goal_made=(
            Bracket(min=0, max=39, points=3),
            Bracket(min=40, max=49, points=4),
            Bracket(min=50, points=5),
        ),
        field_goal_missed=(
            Bracket(min=0, max=39, points=-3),
            Bracket(min=40, max=49, points=-2),
            Bracket(min=50, points=-1),
        ),
        defense_weights={
            "sacks": 1,
            "interceptions": 2,
            "fumble_recoveries": 2,
            "defensive_touchdowns": 6,
            "return_touchdowns": 6,
            "safeties": 2,
            "blocked_kicks": 2,
            "fourth_down_stops": 1,
        },
        points_allowed=(
            Bracket(min=0, max=0, points=10),
            Bracket(min=1, max=6, points=7),
            Bracket(min=7, max=13, points=4),
            Bracket(min=14, max=20, points=1),
            Bracket(min=21, max=27, points=0),
            Bracket(min=28, max=34, points=-1),
            Bracket(min=35, points=-4),
        ),
    ),
}


def default_config(sport: str) -> ScoringConfig:
    return DEFAULT_CONFIGS[sport]


def bracket_points(brackets: Iterable[Bracket], value: float) -> float:
    for bracket in brackets:
        if bracket.contains(value):
            return bracket.points
    return 0.0


def player_stat_values(sport: str, stats: Mapping[str, float]) -> dict[str, float]:
    """A stat line plus its derived misses (attempts minus makes)."""
    values = dict(stats)
    for name, (attempts, made) in _DERIVED_MISSES[sport].items():
        values[name] = stats.get(attempts, 0) - stats.get(made, 0)
    return values


def kick_points(config: ScoringConfig, kicks: Iterable[tuple[int, str]]) -> float:
    """Points for field goal attempts, each given as (distance, result)."""
    total = 0.0
    for distance, result in kicks:
        brackets = config.field_goal_made if result == "made" else config.field_goal_missed
        total += bracket_points(brackets, distance)
    return total


def score_player_game(
    config: ScoringConfig, stats: Mapping[str, float], kicks: Iterable[tuple[int, str]] = ()
) -> float:
    """One player's fantasy points for a game, rounded to a tenth.

    `kicks` are the player's field goal attempts as (distance, result); they only matter to
    configs that score kickers by distance."""
    values = player_stat_values(config.sport, stats)
    total = sum(weight * values.get(stat, 0) for stat, weight in config.player_weights.items())
    return round(total + kick_points(config, kicks), 1)


def score_defense_game(config: ScoringConfig, line: Mapping[str, float]) -> float:
    """One team defense's fantasy points for a game, rounded to a tenth."""
    total = sum(weight * line.get(stat, 0) for stat, weight in config.defense_weights.items())
    if config.points_allowed:
        total += bracket_points(config.points_allowed, line["points_allowed"])
    return round(total, 1)


def bracket_condition(column: ColumnElement[Any], bracket: Bracket) -> ColumnElement[bool]:
    parts = []
    if bracket.min is not None:
        parts.append(column >= bracket.min)
    if bracket.max is not None:
        parts.append(column <= bracket.max)
    return and_(*parts) if parts else true()


def bracket_case(column: ColumnElement[Any], brackets: Iterable[Bracket]) -> ColumnElement[Any]:
    """SQL twin of `bracket_points`: the points for whichever bracket the column falls in."""
    whens = [(bracket_condition(column, bracket), bracket.points) for bracket in brackets]
    return case(*whens, else_=0) if whens else literal(0)


def player_points_expression(config: ScoringConfig, model: Any) -> ColumnElement[Any]:
    """SQL twin of the `player_weights` part of `score_player_game`, over a stats model."""
    columns: dict[str, Any] = {name: getattr(model, name) for name in _columns(model)}
    for name, (attempts, made) in _DERIVED_MISSES[config.sport].items():
        if attempts in columns and made in columns:
            columns[name] = columns[attempts] - columns[made]
    terms = [weight * columns[stat] for stat, weight in config.player_weights.items()]
    return reduce(add, terms) if terms else literal(0)
