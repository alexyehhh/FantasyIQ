"""How a game in progress shows up through the API: a status and running score, no result yet.

The worker keeps those games' stats current (data_pipeline/worker.py); the API only reads them.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.db.models import Game, Player, PlayerGameStatsNFL, Team, TeamGameStatsNFL
from app.db.session import SessionLocal, get_db
from app.main import app

NOW = datetime(2026, 9, 25, 3, 0)  # naive UTC, as stored


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


@pytest.fixture
def world(db):
    """A home team leading 14-10 in a game that is on, with its QB's and its defense's lines."""
    home = Team(name="Home Hawks", abbreviation="HAW", sport="NFL")
    away = Team(name="Away Ants", abbreviation="ANT", sport="NFL")
    db.add_all([home, away])
    db.flush()
    qb = Player(name="Live QB", sport="NFL", team_id=home.id, position="QB")
    game = Game(
        sport="NFL",
        season="2026",
        home_team_id=home.id,
        away_team_id=away.id,
        start_time=NOW - timedelta(hours=1),
        week=3,
        status="in_progress",
        home_score=14,
        away_score=10,
    )
    db.add_all([qb, game])
    db.flush()
    db.add_all(
        [
            PlayerGameStatsNFL(player_id=qb.id, game_id=game.id, passing_yards=150),
            TeamGameStatsNFL(team_id=home.id, game_id=game.id, sacks=2, points_allowed=10),
        ]
    )
    db.flush()
    return SimpleNamespace(home=home, away=away, qb=qb, game=game)


def test_a_players_line_from_a_game_in_progress_has_the_running_score_but_no_result(client, world):
    (entry,) = client.get(f"/api/v1/players/{world.qb.id}/stats?season=current").json()

    assert entry["status"] == "in_progress"
    assert entry["stats"]["passing_yards"] == 150
    assert (entry["team_score"], entry["opponent_score"]) == (14, 10)
    assert entry["result"] is None


def test_a_defense_line_from_a_game_in_progress_has_the_running_score_but_no_result(client, world):
    (entry,) = client.get(f"/api/v1/defenses/{world.home.id}/stats?season=current").json()

    assert entry["status"] == "in_progress"
    assert entry["stats"]["sacks"] == 2
    assert (entry["team_score"], entry["opponent_score"], entry["result"]) == (14, 10, None)


def test_the_schedule_shows_a_game_in_progress_with_its_score_but_no_result(client, world):
    (game,) = client.get(f"/api/v1/players/{world.qb.id}/schedule").json()

    assert game["status"] == "in_progress"
    assert (game["team_score"], game["opponent_score"], game["result"]) == (14, 10, None)


def test_a_finished_game_has_its_result(client, db, world):
    world.game.status = "final"
    db.flush()

    (entry,) = client.get(f"/api/v1/players/{world.qb.id}/stats").json()

    assert (entry["status"], entry["result"]) == ("final", "W")


def test_season_totals_include_the_game_in_progress_so_far(client, world):
    season = client.get(f"/api/v1/players/{world.qb.id}/season").json()

    assert season["games"] == 1
    assert season["stats"]["passing_yards"]["total"] == 150
