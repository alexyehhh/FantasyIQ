"""Scoring an *expected* stat line.

`score_player_game` and `score_defense_game` score one real game. A projection is an average over
games that could happen, and two kinds of scoring don't survive averaging first:

- Kicks. A kicker is expected to attempt 0.4 field goals from 40-49 yards, not one from exactly
  45. Each `KickBucket` is scored as its expected count spread evenly over its distances, which is
  exact whenever the bucket lies inside one of the config's brackets (the usual case) and an
  approximation, reported as such, when a bracket boundary falls inside a bucket.
- Points allowed. Scoring the *average* points allowed (17.5 -> the 14-20 bracket) treats every
  defense expected to give up 21 as though it will give up exactly 21, when its real chance of a
  bonus or a penalty spans several brackets. Instead the expected bracket points are taken over a
  spread of outcomes around the average.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from math import erf, sqrt

from app.services.projections.base import KickBucket
from app.services.scoring import Bracket, ScoringConfig, bracket_points, player_stat_values

# How far one team's points in an NFL game typically stray from its average (about 9-10 points).
# An assumption, not a fitted value: the same spread is used for every defense.
POINTS_ALLOWED_SD = 9.5
_MAX_POINTS = 100


@dataclass(frozen=True)
class Scored:
    points: float
    approximate: bool = False


def _normal_cdf(x: float, mean: float, sd: float) -> float:
    return 0.5 * (1 + erf((x - mean) / (sd * sqrt(2))))


def expected_bracket_points(
    brackets: Iterable[Bracket], mean: float, sd: float = POINTS_ALLOWED_SD
) -> float:
    """Expected points from `brackets` when a team's points allowed are normally spread around
    `mean` (rounded to whole points, never below 0)."""
    brackets = list(brackets)
    total = 0.0
    for points in range(_MAX_POINTS + 1):
        low = -float("inf") if points == 0 else points - 0.5
        high = float("inf") if points == _MAX_POINTS else points + 0.5
        chance = _normal_cdf(high, mean, sd) - _normal_cdf(low, mean, sd)
        total += chance * bracket_points(brackets, points)
    return total


def expected_kick_points(config: ScoringConfig, kicks: Iterable[KickBucket]) -> Scored:
    total = 0.0
    exact = True
    for bucket in kicks:
        for count, brackets in (
            (bucket.made, config.field_goal_made),
            (bucket.missed, config.field_goal_missed),
        ):
            if not count or not brackets:
                continue
            values = [bracket_points(brackets, d) for d in range(bucket.low, bucket.high + 1)]
            if len(set(values)) > 1:
                exact = False
            total += count * sum(values) / len(values)
    return Scored(total, not exact)


def score_expected_player(
    config: ScoringConfig, stats: Mapping[str, float], kicks: Iterable[KickBucket] = ()
) -> Scored:
    """A player's expected fantasy points for a game, rounded to a tenth."""
    values = player_stat_values(config.sport, stats)
    total = sum(weight * values.get(stat, 0) for stat, weight in config.player_weights.items())
    kicking = expected_kick_points(config, kicks)
    return Scored(round(total + kicking.points, 1), kicking.approximate)


def score_expected_defense(config: ScoringConfig, stats: Mapping[str, float]) -> Scored:
    """A team defense's expected fantasy points for a game, rounded to a tenth."""
    total = sum(weight * stats.get(stat, 0) for stat, weight in config.defense_weights.items())
    if config.points_allowed and "points_allowed" in stats:
        total += expected_bracket_points(config.points_allowed, stats["points_allowed"])
    return Scored(round(total, 1))
