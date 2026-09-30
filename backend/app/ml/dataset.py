"""Loading player-game history as a flat table, one row per player per finished game.

Only games whose box score is complete (`stats_final`) are used. A player's team *in that game* is
not stored (the roster sync only knows the current team), so `is_home` is known only when the
player's current team played in the game and is left empty otherwise.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection

# Positions each sport's model covers. Kickers and team defenses score by distance and bracket, so
# they are not modelled in v1.
POSITIONS: dict[str, tuple[str, ...]] = {
    "NFL": ("QB", "RB", "FB", "WR", "TE"),
    "NBA": ("PG", "SG", "SF", "PF", "C", "G", "F", "GF", "FC"),
}
# A fullback is projected like a running back.
POSITION_ALIASES = {"FB": "RB"}

NFL_STATS = (
    "passing_completions",
    "passing_attempts",
    "passing_yards",
    "passing_touchdowns",
    "interceptions",
    "rushing_attempts",
    "rushing_yards",
    "rushing_touchdowns",
    "receptions",
    "receiving_targets",
    "receiving_yards",
    "receiving_touchdowns",
    "fumbles_lost",
)
NBA_STATS = (
    "minutes",
    "points",
    "rebounds",
    "assists",
    "steals",
    "blocks",
    "turnovers",
    "field_goals_made",
    "field_goal_attempts",
    "three_pointers_made",
    "three_point_attempts",
    "free_throws_made",
    "free_throw_attempts",
)
STATS: dict[str, tuple[str, ...]] = {"NFL": NFL_STATS, "NBA": NBA_STATS}
_TABLES = {"NFL": "player_game_stats_nfl", "NBA": "player_game_stats"}


def load_history(conn: Connection, sport: str) -> pd.DataFrame:
    """Every finished game's stat line for the sport's modelled positions, oldest first.

    Columns: player_id, game_id, start_time, season, week, position, is_home, then the stats.
    NBA games a player sat out (no minutes) are dropped: a projection is for a player who plays."""
    stats = ", ".join(f"s.{name}" for name in STATS[sport])
    query = text(
        f"""
        SELECT s.player_id, s.game_id, g.start_time, g.season, g.week, p.position,
               CASE WHEN p.team_id = g.home_team_id THEN 1
                    WHEN p.team_id = g.away_team_id THEN 0 END AS is_home,
               {stats}
        FROM {_TABLES[sport]} s
        JOIN games g ON g.id = s.game_id
        JOIN players p ON p.id = s.player_id
        WHERE g.sport = :sport AND g.status = 'final' AND g.stats_final
          AND p.position = ANY(:positions)
        """
    )
    frame = pd.read_sql(query, conn, params={"sport": sport, "positions": list(POSITIONS[sport])})
    if sport == "NBA":
        frame = frame[frame["minutes"] > 0]
    frame["position"] = frame["position"].replace(POSITION_ALIASES)
    frame["is_home"] = frame["is_home"].astype("float64")
    frame["week"] = frame["week"].astype("float64")
    return frame.sort_values(["player_id", "start_time"]).reset_index(drop=True)
