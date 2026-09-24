"""
Season totals and where they rank.

A player's header shows their season totals for the stats that matter at their position, each
with its rank among the other players at that position (a team defense ranks among the other
defenses). Like the other services this is plain SQLAlchemy plus arithmetic, with no knowledge of
HTTP; the API layer and, later, the AI tool layer both call it.

Rank 1 is the most of a stat, except for stats where fewer is better (turnovers, points allowed).
Players tied on a total share a rank and are flagged `tied`. "Same position" follows the
position filters: an RB group includes fullbacks, and the NBA's G/F/C groups include the specific
PG/SG and SF/PF codes. Only players who actually played that season are ranked.
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Game, Player, Team, TeamGameStatsNFL
from app.services import defenses as defenses_service
from app.services import players as players_service
from app.services.scoring import ScoringConfig

FANTASY_POINTS = "fantasy_points"

# Rank group label -> the position codes ESPN stores that belong to it.
POSITION_GROUPS: dict[str, dict[str, tuple[str, ...]]] = {
    "NFL": {
        "QB": ("QB",),
        "RB": ("RB", "FB"),
        "WR": ("WR",),
        "TE": ("TE",),
        "K": ("PK",),
    },
    "NBA": {
        "G": ("G", "PG", "SG"),
        "F": ("F", "SF", "PF"),
        "C": ("C",),
    },
}

PLAYER_LOWER_IS_BETTER = {"turnovers", "interceptions", "fumbles_lost"}
DEFENSE_LOWER_IS_BETTER = {"points_allowed", "yards_allowed"}

DEFENSE_GROUP = "DEF"


@dataclass
class RankedTotal:
    total: float
    rank: int
    tied: bool


@dataclass
class SeasonSummary:
    season: str
    games: int
    position_group: str
    pool_size: int
    stats: dict[str, RankedTotal]


def position_group(sport: str, position: str | None) -> tuple[str, tuple[str, ...]] | None:
    """The rank group a position belongs to, as (label, codes); None for a player with no position.

    A position with no group of its own (a linebacker, a punter) is ranked among players with
    exactly that code."""
    if position is None:
        return None
    for label, codes in POSITION_GROUPS[sport].items():
        if position in codes:
            return label, codes
    return position, (position,)


def _rank(value: float, everyone: list[float], lower_is_better: bool) -> RankedTotal:
    better = sum(1 for other in everyone if (other < value if lower_is_better else other > value))
    tied = sum(1 for other in everyone if other == value) > 1
    return RankedTotal(total=value, rank=better + 1, tied=tied)


def _summarize(
    season: str,
    group: str,
    pool: dict[int, dict[str, float]],
    games: dict[int, int],
    subject_id: int,
    lower_is_better: set[str],
) -> SeasonSummary | None:
    if subject_id not in pool:
        return None
    subject = pool[subject_id]
    stats = {
        stat: _rank(
            value,
            [totals[stat] for totals in pool.values()],
            stat in lower_is_better,
        )
        for stat, value in subject.items()
    }
    return SeasonSummary(
        season=season,
        games=games[subject_id],
        position_group=group,
        pool_size=len(pool),
        stats=stats,
    )


def get_player_season_summary(
    db: Session, player: Player, scoring: ScoringConfig | None = None
) -> SeasonSummary | None:
    """A player's totals for the latest season with stats, ranked within their position group.

    None when the player has no position, or hasn't played that season."""
    grouping = position_group(player.sport, player.position)
    season = players_service._stats_season(db, player.sport)
    if grouping is None or season is None:
        return None
    group, codes = grouping

    model = players_service._STATS_MODEL_BY_SPORT[player.sport]
    stat_columns = [
        column.name
        for column in model.__table__.columns
        if column.name not in players_service._STATS_METADATA_COLUMNS
    ]
    query = (
        select(
            model.player_id,
            func.count().label("games"),
            *[func.sum(getattr(model, name)).label(name) for name in stat_columns],
        )
        .join(Game, model.game_id == Game.id)
        .join(Player, Player.id == model.player_id)
        .where(Game.season == season, Player.sport == player.sport, Player.position.in_(codes))
        .group_by(model.player_id)
    )
    if player.sport == "NBA":
        # Bench players who didn't get on the floor still have (all-zero) rows.
        query = query.where(model.minutes > 0)

    pool: dict[int, dict[str, float]] = {}
    games: dict[int, int] = {}
    for row in db.execute(query):
        games[row.player_id] = row.games
        pool[row.player_id] = {name: float(getattr(row, name)) for name in stat_columns}

    config = players_service._scoring_for(player.sport, scoring)
    points = players_service._season_points_subquery(config, season)
    for player_id, total in db.execute(
        select(points.c.player_id, points.c.fantasy_points).where(
            points.c.player_id.in_(list(pool))
        )
    ):
        pool[player_id][FANTASY_POINTS] = round(float(total), 1)

    return _summarize(season, group, pool, games, player.id, PLAYER_LOWER_IS_BETTER)


def get_defense_season_summary(
    db: Session, team: Team, scoring: ScoringConfig | None = None
) -> SeasonSummary | None:
    """A team defense's totals for the latest season with defense stats, ranked among defenses."""
    season = defenses_service._stats_season(db)
    if season is None:
        return None

    stat_columns = [
        column.name
        for column in TeamGameStatsNFL.__table__.columns
        if column.name not in defenses_service._STATS_METADATA_COLUMNS
    ]
    query = (
        select(
            TeamGameStatsNFL.team_id,
            func.count().label("games"),
            *[func.sum(getattr(TeamGameStatsNFL, name)).label(name) for name in stat_columns],
        )
        .join(Game, TeamGameStatsNFL.game_id == Game.id)
        .where(Game.season == season)
        .group_by(TeamGameStatsNFL.team_id)
    )
    pool: dict[int, dict[str, float]] = {}
    games: dict[int, int] = {}
    for row in db.execute(query):
        games[row.team_id] = row.games
        pool[row.team_id] = {name: float(getattr(row, name)) for name in stat_columns}

    config = defenses_service._scoring_for(scoring)
    points = defenses_service._season_points_subquery(config, season)
    for team_id, total in db.execute(select(points.c.team_id, points.c.fantasy_points)):
        if team_id in pool:
            pool[team_id][FANTASY_POINTS] = round(float(total), 1)

    return _summarize(season, DEFENSE_GROUP, pool, games, team.id, DEFENSE_LOWER_IS_BETTER)
