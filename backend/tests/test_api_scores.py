"""Integration tests for GET /api/v1/scores (real Postgres, rolled back after)."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.db.models import Game, Team
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


def _team(db, name, abbreviation, sport="NFL"):
    team = Team(name=name, abbreviation=abbreviation, sport=sport)
    db.add(team)
    db.flush()
    return team


NOW = datetime.now(timezone.utc).replace(tzinfo=None)


def test_get_scores_returns_the_current_nfl_weeks_games(client, db):
    home = _team(db, "Mine", "MNE")
    away = _team(db, "Rival", "RIV")
    game = Game(
        sport="NFL", season="2026", week=3, home_team_id=home.id, away_team_id=away.id,
        start_time=NOW - timedelta(hours=1), status="final", home_score=24, away_score=17,
    )
    db.add(game)
    db.flush()

    response = client.get("/api/v1/scores", params={"sport": "NFL"})

    assert response.status_code == 200
    body = response.json()
    assert body["week"] == 3
    (item,) = body["games"]
    assert item["home_team"]["abbreviation"] == "MNE"
    assert item["away_team"]["abbreviation"] == "RIV"
    assert item["home_score"] == 24
    assert item["away_score"] == 17
    assert item["status"] == "final"


def test_get_scores_requires_a_sport(client):
    response = client.get("/api/v1/scores")

    assert response.status_code == 422


def test_get_scores_is_empty_before_the_season_has_any_games(client):
    response = client.get("/api/v1/scores", params={"sport": "NFL"})

    assert response.status_code == 200
    assert response.json() == {"week": None, "games": []}
