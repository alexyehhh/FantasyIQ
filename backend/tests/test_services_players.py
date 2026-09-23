"""
Integration tests for app/services/players.py.

Hits a real Postgres database, same pattern as test_models.py: each
test flushes (never commits) inside a session that's rolled back at
teardown, so nothing persists between tests.
"""

from datetime import datetime, timezone

import pytest

from app.db.models import Game, Player, PlayerGameStats, PlayerGameStatsNFL, Team
from app.db.session import SessionLocal
from app.services import players as players_service


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _make_team(db, sport="NBA", name="Test Team", abbreviation="TST"):
    team = Team(name=name, abbreviation=abbreviation, sport=sport)
    db.add(team)
    db.flush()
    return team


def _make_player(db, team, sport="NBA", name="Test Player", **kwargs):
    player = Player(name=name, sport=sport, team_id=team.id, **kwargs)
    db.add(player)
    db.flush()
    return player


def _make_game(db, team, sport="NBA", start_time=None):
    game = Game(
        sport=sport,
        season="2025-26" if sport == "NBA" else "2025",
        home_team_id=team.id,
        away_team_id=team.id,
        start_time=start_time or datetime(2026, 1, 1, tzinfo=timezone.utc),
        status="final",
    )
    db.add(game)
    db.flush()
    return game


def test_list_players_returns_all_by_default(db):
    team = _make_team(db)
    _make_player(db, team, name="Alice")
    _make_player(db, team, name="Bob")

    players, total = players_service.list_players(db)

    assert total >= 2
    assert {p.name for p in players} >= {"Alice", "Bob"}


def test_list_players_filters_by_sport(db):
    nba_team = _make_team(db, sport="NBA", abbreviation="NBA1")
    nfl_team = _make_team(db, sport="NFL", abbreviation="NFL1")
    _make_player(db, nba_team, sport="NBA", name="Hooper")
    _make_player(db, nfl_team, sport="NFL", name="Gridiron")

    players, _total = players_service.list_players(db, sport="NFL")

    assert all(p.sport == "NFL" for p in players)
    assert "Gridiron" in {p.name for p in players}
    assert "Hooper" not in {p.name for p in players}


def test_list_players_search_is_case_insensitive_substring(db):
    team = _make_team(db)
    _make_player(db, team, name="Stephen Curry")

    players, total = players_service.list_players(db, search="curry")

    assert total == 1
    assert players[0].name == "Stephen Curry"


def test_list_players_pagination(db):
    team = _make_team(db)
    for i in range(5):
        _make_player(db, team, name=f"Pager {i}")

    page, total = players_service.list_players(
        db, search="Pager", limit=2, offset=0
    )
    assert total == 5
    assert len(page) == 2


def test_get_player_returns_none_for_missing_id(db):
    assert players_service.get_player(db, 0) is None


def test_get_player_returns_player(db):
    team = _make_team(db)
    player = _make_player(db, team, name="Findable")

    fetched = players_service.get_player(db, player.id)

    assert fetched is not None
    assert fetched.name == "Findable"


def test_get_player_game_stats_nba(db):
    team = _make_team(db, sport="NBA")
    player = _make_player(db, team, sport="NBA")
    game = _make_game(db, team, sport="NBA")
    db.add(PlayerGameStats(player_id=player.id, game_id=game.id, points=30))
    db.flush()

    rows = players_service.get_player_game_stats(db, player)

    assert len(rows) == 1
    stats_row, game_start_time = rows[0]
    assert stats_row.points == 30
    # start_time is stored tz-naive in Postgres, so compare naive-to-naive
    # rather than against the tz-aware value still held in memory.
    assert game_start_time == game.start_time.replace(tzinfo=None)


def test_get_player_game_stats_nfl(db):
    team = _make_team(db, sport="NFL")
    player = _make_player(db, team, sport="NFL")
    game = _make_game(db, team, sport="NFL")
    db.add(
        PlayerGameStatsNFL(player_id=player.id, game_id=game.id, passing_yards=275)
    )
    db.flush()

    rows = players_service.get_player_game_stats(db, player)

    assert len(rows) == 1
    stats_row, _ = rows[0]
    assert stats_row.passing_yards == 275


def test_get_player_game_stats_orders_most_recent_first(db):
    team = _make_team(db, sport="NBA")
    player = _make_player(db, team, sport="NBA")
    older_game = _make_game(db, team, start_time=datetime(2025, 12, 1, tzinfo=timezone.utc))
    newer_game = _make_game(db, team, start_time=datetime(2026, 1, 1, tzinfo=timezone.utc))
    db.add(PlayerGameStats(player_id=player.id, game_id=older_game.id, points=10))
    db.add(PlayerGameStats(player_id=player.id, game_id=newer_game.id, points=20))
    db.flush()

    rows = players_service.get_player_game_stats(db, player)

    assert [stats.points for stats, _ in rows] == [20, 10]


def test_get_player_game_stats_respects_limit(db):
    team = _make_team(db, sport="NBA")
    player = _make_player(db, team, sport="NBA")
    for i in range(3):
        game = _make_game(
            db, team, start_time=datetime(2026, 1, i + 1, tzinfo=timezone.utc)
        )
        db.add(PlayerGameStats(player_id=player.id, game_id=game.id, points=i))
    db.flush()

    rows = players_service.get_player_game_stats(db, player, limit=2)

    assert len(rows) == 2


def test_serialize_stats_row_excludes_identity_columns(db):
    team = _make_team(db, sport="NBA")
    player = _make_player(db, team, sport="NBA")
    game = _make_game(db, team, sport="NBA")
    stats = PlayerGameStats(player_id=player.id, game_id=game.id, points=15, assists=5)
    db.add(stats)
    db.flush()

    serialized = players_service.serialize_stats_row(stats)

    assert serialized["points"] == 15
    assert serialized["assists"] == 5
    assert "id" not in serialized
    assert "player_id" not in serialized
    assert "game_id" not in serialized
    assert "created_at" not in serialized
