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


def test_list_players_includes_team_and_headshot(client, db):
    team = _make_team(db, name="Listed Team", abbreviation="LST")
    db.flush()
    _make_player(
        db, team, name="Pictured", headshot_url="https://img.example/1.png",
        injury_status="Questionable",
    )

    response = client.get("/api/v1/players", params={"search": "Pictured"})

    (item,) = response.json()["items"]
    assert item["team"]["abbreviation"] == "LST"
    assert item["headshot_url"] == "https://img.example/1.png"
    assert item["injury_status"] == "Questionable"


def test_get_player_returns_bio_injury_and_next_game(client, db):
    team = _make_team(db, name="Mine", abbreviation="MNE")
    rival = _make_team(db, name="Rival", abbreviation="RIV")
    player = _make_player(
        db, team, name="Detailed", height_inches=77, weight_lbs=215, college="State",
        injury_status="Out", injury_type="Knee", injury_note="Sprained knee.",
    )
    db.add(
        Game(
            sport="NBA", season="2026-27", home_team_id=rival.id, away_team_id=team.id,
            start_time=datetime(2999, 1, 1), status="scheduled",
        )
    )
    db.flush()

    body = client.get(f"/api/v1/players/{player.id}").json()

    assert (body["height_inches"], body["weight_lbs"], body["college"]) == (77, 215, "State")
    assert body["team"]["name"] == "Mine"
    assert body["injury"]["status"] == "Out"
    assert body["injury"]["type"] == "Knee"
    assert body["injury"]["note"] == "Sprained knee."
    assert body["next_game"]["opponent"]["abbreviation"] == "RIV"
    assert body["next_game"]["is_home"] is False


def test_get_player_has_no_injury_or_next_game_when_healthy_and_unscheduled(client, db):
    team = _make_team(db)
    player = _make_player(db, team)

    body = client.get(f"/api/v1/players/{player.id}").json()

    assert body["injury"] is None
    assert body["next_game"] is None


def test_get_player_stats_includes_opponent_and_result(client, db):
    team = _make_team(db, name="Mine", abbreviation="MNE")
    rival = _make_team(db, name="Rival", abbreviation="RIV")
    player = _make_player(db, team)
    game = Game(
        sport="NBA", season="2025-26", home_team_id=team.id, away_team_id=rival.id,
        start_time=datetime(2026, 1, 1), status="final", home_score=101, away_score=99,
    )
    db.add(game)
    db.flush()
    db.add(PlayerGameStats(player_id=player.id, game_id=game.id, points=12))
    db.flush()

    (entry,) = client.get(f"/api/v1/players/{player.id}/stats").json()

    assert entry["opponent"]["abbreviation"] == "RIV"
    assert entry["is_home"] is True
    assert (entry["team_score"], entry["opponent_score"], entry["result"]) == (101, 99, "W")


def test_timestamps_are_serialized_as_explicit_utc(client, db):
    team = _make_team(db, name="Mine", abbreviation="MNE")
    rival = _make_team(db, name="Rival", abbreviation="RIV")
    player = _make_player(db, team)
    game = Game(
        sport="NBA", season="2025-26", home_team_id=team.id, away_team_id=rival.id,
        start_time=datetime(2026, 1, 1, 0, 20), status="final",
    )
    db.add(game)
    db.flush()
    db.add(PlayerGameStats(player_id=player.id, game_id=game.id, points=1))
    db.flush()

    (entry,) = client.get(f"/api/v1/players/{player.id}/stats").json()

    assert entry["game_date"] == "2026-01-01T00:20:00Z"


def test_list_players_accepts_a_repeated_position_param(client, db):
    team = _make_team(db, sport="NFL", abbreviation="NFL3")
    for name, position in [("A Quarterback", "QB"), ("A Runner", "RB"), ("A Receiver", "WR")]:
        _make_player(db, team, sport="NFL", name=name, position=position)

    response = client.get(
        "/api/v1/players", params=[("sport", "NFL"), ("position", "RB"), ("position", "WR"),
                                   ("search", "A ")]
    )

    assert {item["name"] for item in response.json()["items"]} == {"A Runner", "A Receiver"}


def test_team_includes_bye_week(client, db):
    team = Team(name="Bye Team", abbreviation="BYE", sport="NFL", bye_week=9)
    db.add(team)
    db.flush()
    player = _make_player(db, team, sport="NFL")

    body = client.get(f"/api/v1/players/{player.id}").json()

    assert body["team"]["bye_week"] == 9


def test_get_player_schedule_returns_played_and_upcoming_games(client, db):
    team = _make_team(db, sport="NFL", name="Mine", abbreviation="MNE")
    rival = _make_team(db, sport="NFL", name="Rival", abbreviation="RIV")
    player = _make_player(db, team, sport="NFL")
    db.add_all([
        Game(sport="NFL", season="2026", home_team_id=team.id, away_team_id=rival.id,
             start_time=datetime(2026, 9, 6, 17), status="final", week=1,
             home_score=24, away_score=17),
        Game(sport="NFL", season="2026", home_team_id=rival.id, away_team_id=team.id,
             start_time=datetime(2999, 9, 13, 17), status="scheduled", week=2),
    ])
    db.flush()

    played, upcoming = client.get(f"/api/v1/players/{player.id}/schedule").json()

    assert (played["week"], played["status"], played["result"]) == (1, "final", "W")
    assert (played["team_score"], played["opponent_score"]) == (24, 17)
    assert played["game_date"] == "2026-09-06T17:00:00Z"
    assert (upcoming["week"], upcoming["status"], upcoming["result"]) == (2, "scheduled", None)
    assert upcoming["is_home"] is False
    assert upcoming["opponent"]["abbreviation"] == "RIV"


def test_get_player_schedule_returns_404_for_missing_player(client):
    assert client.get("/api/v1/players/999999/schedule").status_code == 404


def test_get_player_stats_includes_the_games_week(client, db):
    team = _make_team(db, sport="NFL")
    player = _make_player(db, team, sport="NFL")
    game = Game(sport="NFL", season="2026", home_team_id=team.id, away_team_id=team.id,
                start_time=datetime(2026, 9, 6), status="final", week=3)
    db.add(game)
    db.flush()
    db.add(PlayerGameStatsNFL(player_id=player.id, game_id=game.id, passing_yards=1))
    db.flush()

    (entry,) = client.get(f"/api/v1/players/{player.id}/stats").json()

    assert entry["week"] == 3


def test_list_players_can_sort_by_fantasy_points_and_reports_them(client, db):
    team = _make_team(db, sport="NFL", abbreviation="NFL9")
    ranked = []
    for name, catches in [("Sorted Low", 1), ("Sorted High", 9), ("Sorted None", None)]:
        player = _make_player(db, team, sport="NFL", name=name, position="WR")
        ranked.append(player)
        if catches:
            game = Game(sport="NFL", season="2026", home_team_id=team.id, away_team_id=team.id,
                        start_time=datetime(2026, 9, 6), status="final")
            db.add(game)
            db.flush()
            db.add(PlayerGameStatsNFL(player_id=player.id, game_id=game.id, receptions=catches))
    db.flush()

    body = client.get("/api/v1/players", params={
        "sport": "NFL", "position": "WR", "search": "Sorted", "sort": "fantasy_points",
    }).json()

    assert [(i["name"], i["fantasy_points"]) for i in body["items"]] == [
        ("Sorted High", 9), ("Sorted Low", 1), ("Sorted None", None),
    ]


def test_list_players_pages_through_a_fantasy_points_ranking(client, db):
    team = _make_team(db, sport="NBA", abbreviation="NBA9")
    for index in range(4):
        player = _make_player(db, team, name=f"Paged {index}")
        game = Game(sport="NBA", season="2025-26", home_team_id=team.id, away_team_id=team.id,
                    start_time=datetime(2026, 1, index + 1), status="final")
        db.add(game)
        db.flush()
        db.add(PlayerGameStats(player_id=player.id, game_id=game.id, points=10 * (index + 1)))
    db.flush()
    params = {"sport": "NBA", "search": "Paged", "sort": "fantasy_points", "limit": 2}

    page_one = client.get("/api/v1/players", params=params).json()
    page_two = client.get("/api/v1/players", params={**params, "offset": 2}).json()

    assert [i["name"] for i in page_one["items"]] == ["Paged 3", "Paged 2"]
    assert [i["name"] for i in page_two["items"]] == ["Paged 1", "Paged 0"]
    assert page_one["total"] == page_two["total"] == 4


def test_sorting_by_fantasy_points_without_a_sport_is_rejected(client):
    assert client.get("/api/v1/players", params={"sort": "fantasy_points"}).status_code == 422


def test_unknown_sort_is_rejected(client):
    assert client.get("/api/v1/players", params={"sort": "salary"}).status_code == 422
