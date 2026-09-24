"""
Team defense (D/ST) business logic: listing, ranking, game log and schedule.

A fantasy defense is an NFL team, so it is looked up by team id and scored from
TeamGameStatsNFL rows. Like app/services/players.py this is plain SQLAlchemy with no
knowledge of HTTP; the API layer (app/api/v1/defenses.py) and, later, the AI tool layer
both call these functions.
"""

from dataclasses import dataclass

from sqlalchemy import Subquery, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Game, Team, TeamGameStatsNFL
from app.services.players import Matchup, _matchup, _teams_for
from app.services.scoring import (
    ScoringConfig,
    default_config,
    defense_points_expression,
    score_defense_game,
)

_STATS_METADATA_COLUMNS = {"id", "team_id", "game_id", "created_at"}


def _scoring_for(scoring: ScoringConfig | None) -> ScoringConfig:
    config = scoring or default_config("NFL")
    if config.sport != "NFL":
        raise ValueError(f"A {config.sport} scoring config can't score team defenses")
    return config


def _stats_season(db: Session) -> str | None:
    """The season of the most recent game with team defense stats."""
    return db.scalar(
        select(Game.season)
        .join(TeamGameStatsNFL, TeamGameStatsNFL.game_id == Game.id)
        .order_by(Game.start_time.desc())
        .limit(1)
    )


def _season_points_subquery(config: ScoringConfig, season: str | None) -> Subquery:
    """Each team defense's fantasy points summed over one season's games under `config`."""
    return (
        select(
            TeamGameStatsNFL.team_id.label("team_id"),
            func.sum(defense_points_expression(config)).label("fantasy_points"),
        )
        .join(Game, TeamGameStatsNFL.game_id == Game.id)
        .where(Game.season == season)
        .group_by(TeamGameStatsNFL.team_id)
        .subquery()
    )


def list_defenses(
    db: Session,
    *,
    search: str | None = None,
    sort: str = "name",
    limit: int = 50,
    offset: int = 0,
    scoring: ScoringConfig | None = None,
) -> tuple[list[Team], int]:
    """Returns (page of NFL team defenses, total matching count).

    `search` matches the team's name or abbreviation (case-insensitive substring). `sort` is
    "name" or "fantasy_points" (most first, over the latest season with defense stats; teams
    with none come last, by name)."""
    query = select(Team).where(Team.sport == "NFL")
    if search:
        pattern = f"%{search}%"
        query = query.where(or_(Team.name.ilike(pattern), Team.abbreviation.ilike(pattern)))

    total = db.scalar(select(func.count()).select_from(query.subquery()))

    if sort == "fantasy_points":
        points = _season_points_subquery(_scoring_for(scoring), _stats_season(db))
        query = query.outerjoin(points, points.c.team_id == Team.id).order_by(
            func.coalesce(points.c.fantasy_points, 0).desc(), Team.name
        )
    else:
        query = query.order_by(Team.name)

    return list(db.scalars(query.offset(offset).limit(limit))), total


def get_season_fantasy_points(
    db: Session, teams: list[Team], scoring: ScoringConfig | None = None
) -> dict[int, float]:
    """Season fantasy points for these team defenses, by team id (default scoring unless given).

    Teams with no defense stats that season are absent. Uses the same season as the
    fantasy-points sort in list_defenses."""
    if not teams:
        return {}
    points = _season_points_subquery(_scoring_for(scoring), _stats_season(db))
    rows = db.execute(
        select(points.c.team_id, points.c.fantasy_points).where(
            points.c.team_id.in_([team.id for team in teams])
        )
    )
    return {team_id: round(float(total), 1) for team_id, total in rows}


def get_defense(db: Session, team_id: int) -> Team | None:
    """The NFL team with this id, or None (an NBA team has no fantasy defense)."""
    team = db.get(Team, team_id)
    return team if team is not None and team.sport == "NFL" else None


@dataclass
class DefenseLogRow(Matchup):
    """One played game: the matchup plus the defense's stat line."""

    stats_row: object = None


def get_defense_game_log(
    db: Session, team: Team, *, limit: int | None = None
) -> list[DefenseLogRow]:
    """A defense's stat lines with opponent and score, most recent game first."""
    query = (
        select(TeamGameStatsNFL, Game)
        .join(Game, TeamGameStatsNFL.game_id == Game.id)
        .where(TeamGameStatsNFL.team_id == team.id)
        .order_by(Game.start_time.desc())
    )
    if limit is not None:
        query = query.limit(limit)
    rows = list(db.execute(query).all())
    teams = _teams_for(db, [game for _, game in rows])
    return [
        DefenseLogRow(**vars(_matchup(game, team.id, teams)), stats_row=stats_row)
        for stats_row, game in rows
    ]


def serialize_defense_row(stats_row: TeamGameStatsNFL) -> dict[str, int]:
    """A team defense stat row as a flat dict of stat name -> value."""
    return {
        column.name: getattr(stats_row, column.name)
        for column in stats_row.__table__.columns
        if column.name not in _STATS_METADATA_COLUMNS
    }


def defense_game_fantasy_points(config: ScoringConfig, row: DefenseLogRow) -> float:
    """The defense's fantasy points for one game of its log under `config`."""
    return score_defense_game(config, serialize_defense_row(row.stats_row))
