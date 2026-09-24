"""
Player business logic: search, lookup, and game-stat retrieval.

Pure SQLAlchemy queries against Postgres, no LLM calls and no
knowledge of HTTP — the API layer (app/api/v1/players.py) and, later,
the AI tool layer both call these functions rather than querying the
DB directly.
"""

import operator
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import reduce

from sqlalchemy import Select, Subquery, and_, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import Game, Player, PlayerGameStats, PlayerGameStatsNFL, Team
from app.services.scoring import DEFAULT_SCORING

# Which stats table a player's game log comes from depends on their sport.
_STATS_MODEL_BY_SPORT = {
    "NBA": PlayerGameStats,
    "NFL": PlayerGameStatsNFL,
}

# Columns that describe the row itself rather than a stat value, so
# they're excluded when a stats row is flattened into a response dict.
_STATS_METADATA_COLUMNS = {"id", "player_id", "game_id", "created_at"}


def _player_query(
    *,
    sport: str | None,
    team_id: int | None,
    search: str | None,
    positions: list[str] | None,
) -> Select:
    query = select(Player)
    if sport is not None:
        query = query.where(Player.sport == sport)
    if positions:
        query = query.where(Player.position.in_(positions))
    if team_id is not None:
        query = query.where(Player.team_id == team_id)
    if search:
        query = query.where(Player.name.ilike(f"%{search}%"))
    return query


def _stats_season(db: Session, sport: str) -> str | None:
    """The season fantasy points are totalled over: the latest one with any stats."""
    model = _STATS_MODEL_BY_SPORT[sport]
    return db.scalar(
        select(Game.season)
        .join(model, model.game_id == Game.id)
        .order_by(Game.start_time.desc())
        .limit(1)
    )


def _season_points_subquery(sport: str, season: str | None) -> Subquery:
    """Each player's fantasy points summed over one season's games (default scoring)."""
    model = _STATS_MODEL_BY_SPORT[sport]
    points = reduce(
        operator.add,
        (weight * getattr(model, stat) for stat, weight in DEFAULT_SCORING[sport].items()),
    )
    return (
        select(model.player_id.label("player_id"), func.sum(points).label("fantasy_points"))
        .join(Game, model.game_id == Game.id)
        .where(Game.season == season)
        .group_by(model.player_id)
        .subquery()
    )


def list_players(
    db: Session,
    *,
    sport: str | None = None,
    team_id: int | None = None,
    search: str | None = None,
    positions: list[str] | None = None,
    sort: str = "name",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Player], int]:
    """Returns (page of players, total matching count) for search/pagination.

    `positions` matches any of the given position codes (e.g. ["RB", "WR"]).
    `sort` is "name" or "fantasy_points" (most first, over the latest season with
    stats; players with none come last, by name). Fantasy points are only
    comparable within one sport, so that sort needs `sport`."""
    base_query = _player_query(
        sport=sport, team_id=team_id, search=search, positions=positions
    )

    # Counted separately (before LIMIT/OFFSET) so pagination doesn't affect it.
    total = db.scalar(select(func.count()).select_from(base_query.subquery()))

    page_query = base_query.options(joinedload(Player.team))
    if sort == "fantasy_points":
        if sport is None:
            raise ValueError("Sorting by fantasy points needs a sport")
        points = _season_points_subquery(sport, _stats_season(db, sport))
        page_query = page_query.outerjoin(points, points.c.player_id == Player.id).order_by(
            func.coalesce(points.c.fantasy_points, 0).desc(), Player.name
        )
    else:
        page_query = page_query.order_by(Player.name)

    players = db.scalars(page_query.offset(offset).limit(limit)).unique().all()
    return list(players), total


def get_season_fantasy_points(db: Session, players: list[Player]) -> dict[int, float]:
    """Season fantasy points (default scoring) for these players, by player id.

    Players with no stats that season are absent. Uses the same season as the
    fantasy-points sort in list_players."""
    totals: dict[int, float] = {}
    for sport in {player.sport for player in players}:
        points = _season_points_subquery(sport, _stats_season(db, sport))
        ids = [player.id for player in players if player.sport == sport]
        for player_id, total in db.execute(
            select(points.c.player_id, points.c.fantasy_points).where(points.c.player_id.in_(ids))
        ):
            totals[player_id] = round(float(total), 1)
    return totals


def get_player(db: Session, player_id: int) -> Player | None:
    return db.get(Player, player_id)


@dataclass
class Matchup:
    """A game seen from a player's (current) team: who they play, where, and the score."""

    game: Game
    opponent: Team | None
    is_home: bool | None
    team_score: int | None
    opponent_score: int | None

    @property
    def result(self) -> str | None:
        if self.team_score is None or self.opponent_score is None:
            return None
        if self.team_score == self.opponent_score:
            return "T"
        return "W" if self.team_score > self.opponent_score else "L"


@dataclass
class GameLogRow(Matchup):
    """One played game: the matchup plus the player's stat line."""

    stats_row: object = None


def _matchup(game: Game, team_id: int | None, teams: dict[int, Team]) -> Matchup:
    """The game from `team_id`'s side; a game that team didn't play has no opponent."""
    if game.home_team_id == team_id:
        return Matchup(
            game, teams.get(game.away_team_id), True, game.home_score, game.away_score
        )
    if game.away_team_id == team_id:
        return Matchup(
            game, teams.get(game.home_team_id), False, game.away_score, game.home_score
        )
    return Matchup(game, None, None, None, None)


def _teams_for(db: Session, games: list[Game]) -> dict[int, Team]:
    team_ids = {tid for game in games for tid in (game.home_team_id, game.away_team_id)}
    return {team.id: team for team in db.scalars(select(Team).where(Team.id.in_(team_ids)))}


def get_player_game_log(
    db: Session, player: Player, *, limit: int | None = None
) -> list[GameLogRow]:
    """A player's stat lines with opponent and score, most recent game first.

    The stats row's shape (NBA vs. NFL columns) depends on player.sport —
    there is no single "PlayerGameStats" for both, per the DB schema. The
    opponent is worked out from the player's *current* team, so a game played
    for a former team has no opponent (the stats tables don't record a team).
    """
    model = _STATS_MODEL_BY_SPORT[player.sport]
    query = (
        select(model, Game)
        .join(Game, model.game_id == Game.id)
        .where(model.player_id == player.id)
        .order_by(Game.start_time.desc())
    )
    if limit is not None:
        query = query.limit(limit)
    rows = list(db.execute(query).all())

    teams = _teams_for(db, [game for _, game in rows])
    return [
        GameLogRow(**vars(_matchup(game, player.team_id, teams)), stats_row=stats_row)
        for stats_row, game in rows
    ]


# Fantasy seasons end in week 17; ESPN's 18th NFL week isn't played for fantasy.
_LAST_FANTASY_WEEK = 17


def get_player_schedule(db: Session, player: Player) -> list[Matchup]:
    """The player's team's games this season, played and upcoming, in date order.

    "This season" is the season of the next game, or of the latest game once the
    schedule has run out. NFL schedules stop at the last fantasy week.
    """
    if player.team_id is None:
        return []
    involves_team = or_(
        Game.home_team_id == player.team_id, Game.away_team_id == player.team_id
    )
    upcoming = get_next_game(db, player)
    season = (
        upcoming[0].season
        if upcoming
        else db.scalar(
            select(Game.season).where(involves_team).order_by(Game.start_time.desc()).limit(1)
        )
    )
    if season is None:
        return []

    query = select(Game).where(involves_team, Game.season == season)
    if player.sport == "NFL":
        query = query.where(or_(Game.week.is_(None), Game.week <= _LAST_FANTASY_WEEK))
    games = list(db.scalars(query.order_by(Game.start_time)))
    teams = _teams_for(db, games)
    return [_matchup(game, player.team_id, teams) for game in games]


def get_next_game(
    db: Session, player: Player, *, now: datetime | None = None
) -> tuple[Game, Team, bool] | None:
    """The player's team's next game: (game, opponent, player_team_is_home).

    A game that's currently in progress counts as the "next" one until it ends.
    Times are naive UTC, as stored.
    """
    if player.team_id is None:
        return None
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    game = db.scalars(
        select(Game)
        .where(
            or_(Game.home_team_id == player.team_id, Game.away_team_id == player.team_id),
            or_(
                and_(Game.status == "scheduled", Game.start_time >= now),
                Game.status == "in_progress",
            ),
        )
        .order_by(Game.start_time)
        .limit(1)
    ).first()
    if game is None:
        return None
    is_home = game.home_team_id == player.team_id
    opponent = db.get(Team, game.away_team_id if is_home else game.home_team_id)
    return (game, opponent, is_home) if opponent else None


def serialize_stats_row(stats_row) -> dict[str, int | float]:
    """Flattens a PlayerGameStats/PlayerGameStatsNFL row into a plain dict
    of stat name -> value, dropping row-identity columns."""
    return {
        column.name: getattr(stats_row, column.name)
        for column in stats_row.__table__.columns
        if column.name not in _STATS_METADATA_COLUMNS
    }
