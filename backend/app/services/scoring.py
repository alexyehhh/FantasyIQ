"""Default fantasy scoring.

A fantasy score is a weighted sum of a game's stat line, so a league's own
settings can later replace these weights without changing anything else. Keys
are the stat column names on PlayerGameStats / PlayerGameStatsNFL.

The frontend keeps a copy of these weights (frontend/src/lib/scoring.ts) to
score individual game lines; tests on both sides pin the same worked examples
so the two can't drift apart unnoticed.
"""

DEFAULT_SCORING: dict[str, dict[str, float]] = {
    "NBA": {
        "points": 1,
        "rebounds": 1.2,
        "assists": 1.5,
        "steals": 3,
        "blocks": 3,
        "turnovers": -1,
    },
    "NFL": {
        "passing_yards": 0.04,
        "passing_touchdowns": 4,
        "interceptions": -2,
        "rushing_yards": 0.1,
        "rushing_touchdowns": 6,
        "receptions": 1,
        "receiving_yards": 0.1,
        "receiving_touchdowns": 6,
        "fumbles_lost": -2,
    },
}


def fantasy_points(sport: str, stats: dict[str, float]) -> float:
    """One game's fantasy points, rounded to a tenth."""
    weights = DEFAULT_SCORING[sport]
    return round(sum(weight * stats.get(stat, 0) for stat, weight in weights.items()), 1)
