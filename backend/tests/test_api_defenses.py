"""Integration tests for the team defense API endpoints (real Postgres, rolled back after)."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.db.models import Game, Team, TeamGameStatsNFL
from app.db.session import SessionLocal, get_db
from app.main import app

_START = datetime(2026, 9, 10, 20, 0, tzinfo=timezone.utc)


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


def _game(db, home, away, week, home_score=None, away_score=None, status="final", start=None):
    game = Game(
        sport="NFL",
        season="2026",
        home_team_id=home.id,
        away_team_id=away.id,
        start_time=start or _START + timedelta(days=7 * week),
        week=week,
        status=status,
        home_score=home_score,
        away_score=away_score,
    )
    db.add(game)
    db.flush()
    return game


@pytest.fixture
def league(db):
    """Alpha beats Bravo 24-7 (9 fantasy points), then has an upcoming game against Charlie."""
    alpha = _team(db, "Alpha Aces", "ALP")
    bravo = _team(db, "Bravo Bears", "BRV")
    charlie = _team(db, "Charlie Chiefs", "CHA")
    played = _game(db, alpha, bravo, 1, 24, 7)
    soon = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=3)
    upcoming = _game(db, alpha, charlie, 2, status="scheduled", start=soon)
    db.add(TeamGameStatsNFL(team_id=alpha.id, game_id=played.id, sacks=3, interceptions=1,
                            points_allowed=7))
    db.add(TeamGameStatsNFL(team_id=bravo.id, game_id=played.id, sacks=1, points_allowed=31))
    db.flush()
    return {"alpha": alpha, "bravo": bravo, "charlie": charlie, "upcoming": upcoming}


def test_list_defenses_ranks_by_fantasy_points_and_reports_them(client, league):
    response = client.get("/api/v1/defenses", params={"sort": "fantasy_points"})

    assert response.status_code == 200
    body = response.json()
    # Bravo scores 0 (1 sack, -1 for allowing 31), tying Charlie who has no stats; ties go by name.
    assert [item["abbreviation"] for item in body["items"][:3]] == ["ALP", "BRV", "CHA"]
    alpha, bravo = body["items"][0], body["items"][1]
    assert bravo["fantasy_points"] == 0
    assert (alpha["name"], alpha["fantasy_points"]) == ("Alpha Aces", 9)
    assert "bye_week" in alpha and "logo_url" in alpha
    charlie = next(item for item in body["items"] if item["abbreviation"] == "CHA")
    assert charlie["fantasy_points"] is None  # no stats yet
    assert body["total"] >= 3


def test_list_defenses_searches_and_pages(client, league):
    found = client.get("/api/v1/defenses", params={"search": "alpha"}).json()
    page = client.get("/api/v1/defenses", params={"limit": 1, "offset": 1}).json()

    assert [item["abbreviation"] for item in found["items"]] == ["ALP"]
    assert (page["limit"], page["offset"], len(page["items"])) == (1, 1, 1)


def test_list_defenses_scores_with_an_inline_config(client, league):
    config = {"name": "Sacks only", "sport": "NFL", "defense_weights": {"sacks": 10}}

    body = client.get(
        "/api/v1/defenses", params={"sort": "fantasy_points", "scoring": json.dumps(config)}
    ).json()

    assert body["items"][0]["abbreviation"] == "ALP"
    assert body["items"][0]["fantasy_points"] == 30


def test_a_bad_scoring_parameter_is_a_422_that_says_why(client, league):
    typo = json.dumps({"name": "Typo", "sport": "NFL", "defense_weights": {"sacksz": 1}})
    wrong_sport = json.dumps({"name": "Hoops", "sport": "NBA"})

    unknown_preset = client.get("/api/v1/defenses", params={"scoring": "standard"})
    bad_config = client.get("/api/v1/defenses", params={"scoring": typo})
    nba_config = client.get("/api/v1/defenses", params={"scoring": wrong_sport})

    assert unknown_preset.status_code == 422
    assert "Unknown scoring preset" in unknown_preset.json()["detail"]
    assert bad_config.status_code == 422
    assert "unknown defense stats" in json.dumps(bad_config.json()["detail"])
    assert nba_config.status_code == 422


def test_get_defense_returns_the_team_and_its_next_game(client, league):
    response = client.get(f"/api/v1/defenses/{league['alpha'].id}")

    assert response.status_code == 200
    body = response.json()
    assert (body["id"], body["abbreviation"]) == (league["alpha"].id, "ALP")
    assert body["next_game"]["game_id"] == league["upcoming"].id
    assert body["next_game"]["opponent"]["abbreviation"] == "CHA"
    assert body["next_game"]["is_home"] is True
    assert body["next_game"]["start_time"].endswith(("Z", "+00:00"))  # explicit UTC


def test_get_defense_is_404_for_a_missing_team_and_an_nba_team(client, db):
    hoops = _team(db, "Hoops", "HPS", sport="NBA")

    assert client.get("/api/v1/defenses/999999").status_code == 404
    assert client.get(f"/api/v1/defenses/{hoops.id}").status_code == 404
    assert client.get(f"/api/v1/defenses/{hoops.id}/stats").status_code == 404
    assert client.get(f"/api/v1/defenses/{hoops.id}/schedule").status_code == 404


def test_defense_stats_have_the_line_fantasy_points_opponent_and_result(client, league):
    response = client.get(f"/api/v1/defenses/{league['alpha'].id}/stats")

    assert response.status_code == 200
    (game,) = response.json()
    assert game["week"] == 1
    assert game["stats"]["sacks"] == 3 and game["stats"]["points_allowed"] == 7
    assert "id" not in game["stats"] and "team_id" not in game["stats"]
    assert game["fantasy_points"] == 9  # 3 sacks + 2 for the interception + 4 for 7 allowed
    assert game["opponent"]["abbreviation"] == "BRV"
    assert (game["is_home"], game["team_score"], game["opponent_score"], game["result"]) == (
        True, 24, 7, "W",
    )


def test_defense_stats_respect_the_scoring_parameter_and_limit(client, league):
    config = json.dumps({"name": "Sacks only", "sport": "NFL", "defense_weights": {"sacks": 10}})

    (game,) = client.get(
        f"/api/v1/defenses/{league['alpha'].id}/stats", params={"scoring": config, "limit": 5}
    ).json()

    assert game["fantasy_points"] == 30
    assert client.get(
        f"/api/v1/defenses/{league['alpha'].id}/stats", params={"scoring": "nope"}
    ).status_code == 422


def test_defense_schedule_lists_played_and_upcoming_games(client, league):
    response = client.get(f"/api/v1/defenses/{league['alpha'].id}/schedule")

    assert response.status_code == 200
    schedule = response.json()
    assert [(g["week"], g["status"]) for g in schedule] == [(1, "final"), (2, "scheduled")]
    assert schedule[0]["result"] == "W" and schedule[1]["result"] is None
    assert schedule[1]["opponent"]["abbreviation"] == "CHA"
