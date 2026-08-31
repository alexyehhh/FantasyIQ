"""
Integration tests for the DB models.

These hit a real Postgres database (not mocked/sqlite), because the
thing we actually care about here — the unique constraint enforcing
idempotent ingestion — is DB-engine behavior, not Python behavior.
An in-memory sqlite test could pass while the real Postgres constraint
was misconfigured.

Each test wraps its work in a transaction that's rolled back at the
end, so tests don't leave data behind or depend on each other.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import Game, Player, PlayerGameStats, Team
from app.db.session import SessionLocal


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _make_game_and_player(db):
    team = Team(name="Test Team", abbreviation="TST", sport="NBA")
    db.add(team)
    db.flush()

    player = Player(name="Test Player", sport="NBA", team_id=team.id)
    db.add(player)
    db.flush()

    game = Game(
        sport="NBA",
        season="2025-26",
        home_team_id=team.id,
        away_team_id=team.id,
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        status="final",
    )
    db.add(game)
    db.flush()

    return player, game


def test_insert_and_query_player_game_stats(db):
    player, game = _make_game_and_player(db)

    stats = PlayerGameStats(player_id=player.id, game_id=game.id, points=20)
    db.add(stats)
    db.flush()

    fetched = (
        db.query(PlayerGameStats)
        .filter_by(player_id=player.id, game_id=game.id)
        .one()
    )
    assert fetched.points == 20


def test_duplicate_player_game_stats_rejected(db):
    """This is the idempotency guarantee: re-ingesting the same
    player+game must fail at the DB level, not silently duplicate."""
    player, game = _make_game_and_player(db)

    db.add(PlayerGameStats(player_id=player.id, game_id=game.id, points=20))
    db.flush()

    db.add(PlayerGameStats(player_id=player.id, game_id=game.id, points=99))
    with pytest.raises(IntegrityError):
        db.flush()
