"""
Importing this package registers every model with Base.metadata.

Alembic's env.py imports this module (indirectly, via app.db.base)
so autogenerate can see all tables. Anything added here later
(e.g. NFL-specific stats tables) just needs an import line added.
"""

from app.db.models.field_goal_kick import FieldGoalKick
from app.db.models.game import Game
from app.db.models.job_run import JobRun
from app.db.models.player import Player
from app.db.models.player_game_stats import PlayerGameStats
from app.db.models.player_game_stats_nfl import PlayerGameStatsNFL
from app.db.models.team import Team
from app.db.models.team_game_stats_nfl import TeamGameStatsNFL

__all__ = [
    "Team",
    "Player",
    "Game",
    "JobRun",
    "PlayerGameStats",
    "PlayerGameStatsNFL",
    "FieldGoalKick",
    "TeamGameStatsNFL",
]
