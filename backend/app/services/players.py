"""
Player business logic: search, lookup, and game-stat retrieval.

Pure SQLAlchemy queries against Postgres, no LLM calls and no
knowledge of HTTP — the API layer (app/api/v1/players.py) and, later,
the AI tool layer both call these functions rather than querying the
DB directly.
"""

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.db.models import Game, Player, PlayerGameStats, PlayerGameStatsNFL

# Which stats table a player's game log comes from depends on their sport.
_STATS_MODEL_BY_SPORT = {
    "NBA": PlayerGameStats,
    "NFL": PlayerGameStatsNFL,
}

# Columns that describe the row itself rather than a stat value, so
# they're excluded when a stats row is flattened into a response dict.
_STATS_METADATA_COLUMNS = {"id", "player_id", "game_id", "created_at"}


def _player_query(
    *, sport: str | None, team_id: int | None, search: str | None
) -> Select:
    query = select(Player)
    if sport is not None:
        query = query.where(Player.sport == sport)
    if team_id is not None:
        query = query.where(Player.team_id == team_id)
    if search:
        query = query.where(Player.name.ilike(f"%{search}%"))
    return query


def list_players(
    db: Session,
    *,
    sport: str | None = None,
    team_id: int | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Player], int]:
    """Returns (page of players, total matching count) for search/pagination."""
    base_query = _player_query(sport=sport, team_id=team_id, search=search)

    # Counted separately (before LIMIT/OFFSET) so pagination doesn't affect it.
    total = db.scalar(select(func.count()).select_from(base_query.subquery()))

    players = (
        db.scalars(base_query.order_by(Player.name).offset(offset).limit(limit))
        .all()
    )
    return list(players), total


def get_player(db: Session, player_id: int) -> Player | None:
    return db.get(Player, player_id)


def get_player_game_stats(
    db: Session, player: Player, *, limit: int | None = None
) -> list[tuple[object, object]]:
    """Returns (stats_row, game_start_time) tuples, most recent game first.

    The stats row's shape (NBA vs. NFL columns) depends on player.sport —
    there is no single "PlayerGameStats" for both, per the DB schema.
    """
    model = _STATS_MODEL_BY_SPORT[player.sport]
    query = (
        select(model, Game.start_time)
        .join(Game, model.game_id == Game.id)
        .where(model.player_id == player.id)
        .order_by(Game.start_time.desc())
    )
    if limit is not None:
        query = query.limit(limit)
    return list(db.execute(query).all())


def serialize_stats_row(stats_row) -> dict[str, int | float]:
    """Flattens a PlayerGameStats/PlayerGameStatsNFL row into a plain dict
    of stat name -> value, dropping row-identity columns."""
    return {
        column.name: getattr(stats_row, column.name)
        for column in stats_row.__table__.columns
        if column.name not in _STATS_METADATA_COLUMNS
    }
