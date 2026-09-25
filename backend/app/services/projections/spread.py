"""How far a projection could miss by.

A projection is an average; the decision "start A or B" also depends on how much each player's
real score swings around it. The spread is one standard deviation of a player's fantasy points in
a game. It comes from the player's own recent games when there are enough of them, blended toward
a typical spread for their position, which stands alone when there is no history (a rookie, or
the start of a season). The typical spreads are round-number assumptions, not fitted values: a
share of the projection that is larger for positions that rely on touchdowns.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from typing import Literal

# A typical game's standard deviation as a share of the projected points, by position (ESPN's
# position codes). NBA scores swing less, in proportion, than NFL ones.
_NFL_SHARE = {"QB": 0.35, "RB": 0.5, "WR": 0.55, "TE": 0.55, "PK": 0.35, "K": 0.35, "DEF": 0.6}
_NFL_DEFAULT_SHARE = 0.5
_NBA_SHARE = 0.3
_MIN_SPREAD = 2.0
# History counts as this many games' worth less than its size says: with n games it gets a weight
# of n / (n + _PRIOR_GAMES), so 4 games weigh the same as the position's typical spread.
_PRIOR_GAMES = 4

Basis = Literal["history", "blended", "position"]


def typical_spread(sport: str, position: str | None, projected: float) -> float:
    share = _NBA_SHARE if sport == "NBA" else _NFL_SHARE.get(position or "", _NFL_DEFAULT_SHARE)
    return max(_MIN_SPREAD, share * abs(projected))


def spread(
    sport: str,
    position: str | None,
    projected: float,
    history_std: float | None,
    games: int,
) -> tuple[float, Basis]:
    """The spread of a projection and what it rests on."""
    typical = typical_spread(sport, position, projected)
    if history_std is None or games <= 0:
        return round(typical, 1), "position"
    weight = games / (games + _PRIOR_GAMES)
    return round(weight * history_std + (1 - weight) * typical, 1), "blended"


def chance_best(
    means: Sequence[float], spreads: Sequence[float], *, draws: int = 4000, seed: int = 0
) -> list[float]:
    """Each player's chance (0-1) of scoring the most, when scores are normally distributed
    around their projections and independent. Fixed seed: the same request gets the same answer."""
    rng = random.Random(seed)
    wins = [0] * len(means)
    for _ in range(draws):
        scores = [rng.gauss(m, s) for m, s in zip(means, spreads, strict=True)]
        wins[scores.index(max(scores))] += 1
    return [w / draws for w in wins]
