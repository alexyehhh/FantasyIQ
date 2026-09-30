"""Loading player-game history as a flat table, one row per player per finished game.

Only games whose box score is complete (`stats_final`) are used. A player's team *in that game* is
not stored (the roster sync only knows the current team), so `is_home` is known only when the
player's current team played in the game and is left empty otherwise.
"""

from __future__ import annotations

from collections.abc import Sequence

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


def load_history(
    conn: Connection, sport: str, player_ids: Sequence[int] | None = None
) -> pd.DataFrame:
    """Every finished game's stat line for the sport's modelled positions (only `player_ids`, if
    given), oldest first.

    Columns: player_id, game_id, start_time, season, week, position, team_id, is_home, then the
    stats. `team_id` is the player's current team when it played in the game, else empty.
    NBA games a player sat out (no minutes) are dropped: a projection is for a player who plays."""
    stats = ", ".join(f"s.{name}" for name in STATS[sport])
    query = text(
        f"""
        SELECT s.player_id, s.game_id, g.start_time, g.season, g.week, p.position,
               CASE WHEN p.team_id IN (g.home_team_id, g.away_team_id)
                    THEN p.team_id END AS team_id,
               CASE WHEN p.team_id = g.home_team_id THEN 1
                    WHEN p.team_id = g.away_team_id THEN 0 END AS is_home,
               {stats}
        FROM {_TABLES[sport]} s
        JOIN games g ON g.id = s.game_id
        JOIN players p ON p.id = s.player_id
        WHERE g.sport = :sport AND g.status = 'final' AND g.stats_final
          AND p.position = ANY(:positions)
          AND (:all_players OR s.player_id = ANY(:player_ids))
        """
    )
    params = {
        "sport": sport,
        "positions": list(POSITIONS[sport]),
        "all_players": player_ids is None,
        "player_ids": list(player_ids or ()),
    }
    frame = pd.read_sql(query, conn, params=params)
    if sport == "NBA":
        frame = frame[frame["minutes"] > 0]
    frame["position"] = frame["position"].replace(POSITION_ALIASES)
    frame["is_home"] = frame["is_home"].astype("float64")
    frame["week"] = frame["week"].astype("float64")
    return frame.sort_values(["player_id", "start_time"]).reset_index(drop=True)


def load_team_games(conn: Connection, sport: str) -> pd.DataFrame:
    """One row per team per finished game with a complete box score: team_id, game_id, season,
    start_time, oldest first. The order of a team's rows is its schedule, which is what says which
    of its players missed a game."""
    query = text(
        """
        SELECT t.team_id, g.id AS game_id, g.season, g.start_time
        FROM games g
        CROSS JOIN LATERAL (VALUES (g.home_team_id), (g.away_team_id)) AS t(team_id)
        WHERE g.sport = :sport AND g.status = 'final' AND g.stats_final
        """
    )
    frame = pd.read_sql(query, conn, params={"sport": sport})
    return frame.sort_values(["team_id", "start_time"]).reset_index(drop=True)
