"""The accuracy endpoint end to end (real Postgres, rolled back after)."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.db.models import Game, Player, PlayerGameStatsNFL, ProjectionSnapshot, Team
from app.db.session import SessionLocal, get_db
from app.main import app

KICKOFF = datetime(2026, 10, 4, 17, 0)


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
def played_game(db):
    alpha = Team(name="Alpha Aces", abbreviation="ALP", sport="NFL")
    bravo = Team(name="Bravo Bears", abbreviation="BRV", sport="NFL")
    db.add_all([alpha, bravo])
    db.flush()
    game = Game(
        sport="NFL", season="2026", home_team_id=alpha.id, away_team_id=bravo.id,
        start_time=KICKOFF, week=4, status="final", stats_final=True,
    )  # fmt: skip
    wes = Player(name="Wes Receiver", sport="NFL", team_id=alpha.id, position="WR", active=True)
    db.add_all([game, wes])
    db.flush()
    db.add(PlayerGameStatsNFL(player_id=wes.id, game_id=game.id, receptions=6, receiving_yards=50))
    for source, catches in (("sleeper", 6), ("fantasyiq", 4)):  # 11.0 and 9.0 points
        db.add(
            ProjectionSnapshot(
                source=source, sport="NFL", kind="player", entity_id=wes.id, game_id=game.id,
                origin="live", captured_at=KICKOFF - timedelta(hours=2),
                stats={"receptions": catches, "receiving_yards": 50},
            )
        )  # fmt: skip
    db.flush()
    return game


def test_reports_each_sources_error_against_the_real_result(client, played_game):
    body = client.get("/api/v1/accuracy", params={"sport": "NFL"}).json()

    assert body["sources"] == ["fantasyiq", "sleeper"]
    assert body["compared"] == 1 and body["enough_data"] is False
    assert body["overall"]["sleeper"]["mae"] == 0
    assert body["overall"]["fantasyiq"]["mae"] == pytest.approx(2.0)
    assert body["overall"]["fantasyiq"]["bias"] == pytest.approx(-2.0)
    assert body["series"] == [
        {"key": "2026-04", "label": "Week 4", "n": 1, "mae": {"fantasyiq": 2.0, "sleeper": 0.0}}
    ]
    assert body["by_position"][0]["position"] == "WR"
    assert body["coverage"]["sleeper"] == {"projected": 1, "compared": 1}


def test_follows_the_scoring_and_source_parameters(client, played_game):
    standard = '{"name":"Standard","sport":"NFL","player_weights":{"receiving_yards":0.1}}'

    body = client.get(
        "/api/v1/accuracy",
        params={"sport": "NFL", "scoring": standard, "source": ["sleeper"]},
    ).json()

    assert body["scoring"] == "Standard" and body["sources"] == ["sleeper"]
    assert body["overall"]["sleeper"]["mean_actual"] == pytest.approx(5.0)  # no points per catch


def test_with_nothing_saved_yet_it_says_so_instead_of_failing(client):
    response = client.get("/api/v1/accuracy", params={"sport": "NBA"})

    assert response.status_code == 200
    body = response.json()
    assert body["compared"] == 0 and body["overall"] == {} and body["series"] == []
    assert any("No finished games" in note for note in body["notes"])


def test_a_bad_scoring_config_is_a_422(client):
    response = client.get("/api/v1/accuracy", params={"sport": "NFL", "scoring": "nonsense"})

    assert response.status_code == 422
