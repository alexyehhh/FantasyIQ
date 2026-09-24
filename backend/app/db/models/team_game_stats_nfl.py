"""
TeamGameStatsNFL model.

One row per team per game holding the stats a fantasy team defense (D/ST) is scored
on. Kept separate from PlayerGameStatsNFL because these belong to the team unit, not
a player, and are read from team-level box score totals and the play-by-play. The
unique constraint on (team_id, game_id) is what NFL ingestion upserts against.

Definitions follow Yahoo's D/ST scoring, so a linked league can be scored from them:

- `points_allowed` excludes points the opponent scored on defense (interception and
  fumble return touchdowns and their extra points) and safeties. Kick and punt return
  touchdowns against the team still count.
- `defensive_touchdowns` are interception, fumble and blocked-kick returns;
  `return_touchdowns` are kickoff and punt returns, which leagues score separately.
- `fumble_recoveries` are recoveries of the opponent's fumbles.
- `fourth_down_stops` are opposing drives that ended on downs.
- `blocked_kicks` counts blocked field goals and punts only. ESPN's name for a blocked
  extra point hasn't been seen in real data, so those aren't counted yet.

Not stored yet because no real sample exists to verify them against: extra points
returned by the defense, and three-and-outs.
"""

from datetime import datetime

from sqlalchemy import ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TeamGameStatsNFL(Base):
    __tablename__ = "team_game_stats_nfl"
    __table_args__ = (
        UniqueConstraint("team_id", "game_id", name="uq_team_game_nfl"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), nullable=False)

    sacks: Mapped[int] = mapped_column(default=0)
    interceptions: Mapped[int] = mapped_column(default=0)
    fumble_recoveries: Mapped[int] = mapped_column(default=0)
    safeties: Mapped[int] = mapped_column(default=0)
    blocked_kicks: Mapped[int] = mapped_column(default=0)
    defensive_touchdowns: Mapped[int] = mapped_column(default=0)
    return_touchdowns: Mapped[int] = mapped_column(default=0)
    fourth_down_stops: Mapped[int] = mapped_column(default=0)
    points_allowed: Mapped[int] = mapped_column(default=0)
    yards_allowed: Mapped[int] = mapped_column(default=0)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
