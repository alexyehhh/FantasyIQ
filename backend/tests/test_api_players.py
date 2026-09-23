"""
Integration tests for the player API endpoints.

Hits a real Postgres database, like test_models.py and
test_services_players.py. The FastAPI `get_db` dependency is
overridden to hand out the same session the test uses, so data
inserted via `db.flush()` in the test is visible to the request
without needing a cross-connection commit — the session (and its
uncommitted work) is rolled back at teardown either way.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.db.models import Game, Player, PlayerGameStats, PlayerGameStatsNFL, Team
from app.db.session import SessionLocal, get_db
from app.main import app


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


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


def test_list_players_returns_200_with_expected_shape(client, db):
    team = _make_team(db)
    _make_player(db, team, name="Listable")

    response = client.get("/api/v1/players")

    assert response.status_code == 200
    body = response.json()
    assert "items" in body and "total" in body and "limit" in body and "offset" in body
    assert any(item["name"] == "Listable" for item in body["items"])


def test_list_players_filters_by_sport_query_param(client, db):
    nfl_team = _make_team(db, sport="NFL", abbreviation="NFL2")
    _make_player(db, nfl_team, sport="NFL", name="QB Guy")

    response = client.get("/api/v1/players", params={"sport": "NFL"})

    assert response.status_code == 200
    assert all(item["sport"] == "NFL" for item in response.json()["items"])


def test_list_players_rejects_invalid_sport(client):
    response = client.get("/api/v1/players", params={"sport": "MLB"})

    assert response.status_code == 422


def test_get_player_returns_404_for_missing_player(client):
    response = client.get("/api/v1/players/999999")

    assert response.status_code == 404


def test_get_player_returns_player_detail(client, db):
    team = _make_team(db)
    player = _make_player(db, team, name="Detail Guy", position="G")

    response = client.get(f"/api/v1/players/{player.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == player.id
    assert body["name"] == "Detail Guy"
    assert body["position"] == "G"


def test_get_player_stats_returns_404_for_missing_player(client):
    response = client.get("/api/v1/players/999999/stats")

    assert response.status_code == 404


def test_get_player_stats_nba_shape(client, db):
    team = _make_team(db, sport="NBA")
    player = _make_player(db, team, sport="NBA")
    game = _make_game(db, team, sport="NBA")
    db.add(PlayerGameStats(player_id=player.id, game_id=game.id, points=25, assists=8))
    db.flush()

    response = client.get(f"/api/v1/players/{player.id}/stats")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["game_id"] == game.id
    assert body[0]["stats"]["points"] == 25
    assert body[0]["stats"]["assists"] == 8


def test_get_player_stats_nfl_shape(client, db):
    team = _make_team(db, sport="NFL")
    player = _make_player(db, team, sport="NFL")
    game = _make_game(db, team, sport="NFL")
    db.add(
        PlayerGameStatsNFL(player_id=player.id, game_id=game.id, passing_yards=310)
    )
    db.flush()

    response = client.get(f"/api/v1/players/{player.id}/stats")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["stats"]["passing_yards"] == 310
    assert "points" not in body[0]["stats"]


def test_get_player_stats_respects_limit(client, db):
    team = _make_team(db, sport="NBA")
    player = _make_player(db, team, sport="NBA")
    for i in range(3):
        game = _make_game(
            db, team, start_time=datetime(2026, 1, i + 1, tzinfo=timezone.utc)
        )
        db.add(PlayerGameStats(player_id=player.id, game_id=game.id, points=i))
    db.flush()

    response = client.get(f"/api/v1/players/{player.id}/stats", params={"limit": 2})

    assert response.status_code == 200
    assert len(response.json()) == 2
