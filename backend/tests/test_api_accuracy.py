"""The accuracy endpoint end to end (real Postgres, rolled back after)."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.db.models import (
    FieldGoalKick,
    Game,
    Player,
    PlayerGameStatsNFL,
    ProjectionSnapshot,
    Team,
    TeamGameStatsNFL,
)
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


def test_lists_a_players_actual_points_beside_each_sources_projection(client, played_game, db):
    wes = db.query(Player).filter_by(name="Wes Receiver").one()

    body = client.get(
        "/api/v1/accuracy/players", params={"sport": "NFL", "player_id": wes.id}
    ).json()

    [item] = body["items"]
    assert item["player_name"] == "Wes Receiver" and item["week"] == 4
    assert item["team"] == "ALP" and item["opponent"] == "BRV" and item["home"] is True
    assert item["played"] is True and item["actual"] == pytest.approx(11.0)
    assert item["projected"] == {"sleeper": pytest.approx(11.0), "fantasyiq": pytest.approx(9.0)}


def test_without_a_player_it_lists_the_latest_games(client, played_game):
    body = client.get("/api/v1/accuracy/players", params={"sport": "NFL"}).json()

    assert [i["player_name"] for i in body["items"]] == ["Wes Receiver"]
    assert client.get("/api/v1/accuracy/players", params={"sport": "NBA"}).json()["items"] == []


def test_lists_a_team_defenses_real_points_beside_each_sources_projection(client, played_game, db):
    alpha = db.get(Team, played_game.home_team_id)
    db.add(TeamGameStatsNFL(team_id=alpha.id, game_id=played_game.id, sacks=3, points_allowed=10))
    for source, sacks in (("sleeper", 3.0), ("fantasyiq", 1.0)):
        db.add(
            ProjectionSnapshot(
                source=source, sport="NFL", kind="defense", entity_id=alpha.id,
                game_id=played_game.id, origin="live",
                captured_at=KICKOFF - timedelta(hours=2),
                stats={"sacks": sacks, "points_allowed": 10.0},
            )
        )  # fmt: skip
    db.flush()

    body = client.get(f"/api/v1/accuracy/defenses/{alpha.id}").json()

    [item] = body["items"]
    assert item["position"] == "DEF" and item["team"] == "ALP" and item["opponent"] == "BRV"
    assert item["played"] is True and item["week"] == 4
    # Points allowed are projected as an expected value, so compare the sources with each other:
    # two fewer sacks projected is two fewer points.
    assert item["actual"] is not None
    assert item["projected"]["sleeper"] - item["projected"]["fantasyiq"] == pytest.approx(2.0)


def test_a_kickers_points_are_scored_by_distance_on_both_sides(client, played_game, db):
    kip = Player(
        name="Kip Kicker", sport="NFL", team_id=played_game.home_team_id, position="PK", active=True
    )
    db.add(kip)
    db.flush()
    db.add(
        PlayerGameStatsNFL(
            player_id=kip.id, game_id=played_game.id, field_goal_attempts=2, field_goals_made=1,
            extra_point_attempts=2, extra_points_made=2,
        )
    )  # fmt: skip
    for n, (distance, result) in enumerate([(52, "made"), (33, "missed")]):
        db.add(
            FieldGoalKick(
                player_id=kip.id, game_id=played_game.id, distance=distance, result=result,
                external_play_id=f"kip-{n}",
            )
        )  # fmt: skip
    # The same 52-yard make and 33-yard miss, projected as expected kicks.
    kicks = [
        {"low": 30, "high": 39, "made": 0.0, "missed": 1.0},
        {"low": 50, "high": 65, "made": 1.0, "missed": 0.0},
    ]
    for source in ("sleeper", "fantasyiq"):
        db.add(
            ProjectionSnapshot(
                source=source, sport="NFL", kind="player", entity_id=kip.id,
                game_id=played_game.id, origin="live", captured_at=KICKOFF - timedelta(hours=2),
                stats={"extra_point_attempts": 2, "extra_points_made": 2}, kicks=kicks,
            )
        )  # fmt: skip
    db.flush()

    [item] = client.get(
        "/api/v1/accuracy/players", params={"sport": "NFL", "player_id": kip.id}
    ).json()["items"]

    # 2 extra points (+2), a 52-yard make (+5) and a 33-yard miss (-3).
    assert item["actual"] == pytest.approx(4.0)
    assert item["projected"] == {"sleeper": pytest.approx(4.0), "fantasyiq": pytest.approx(4.0)}
