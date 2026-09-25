"""Integration tests for the projection API endpoints (real Postgres, rolled back after)."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.db.models import Game, Player, PlayerGameStatsNFL, Team
from app.db.session import SessionLocal, get_db
from app.main import app
from app.services.projections import base
from app.services.projections.sleeper import SleeperProvider
from tests.projection_sources import install

_START = datetime(2026, 9, 10, 20, 0)


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
def league(db):
    """Two Alpha receivers with finished games, and Alpha's upcoming game against Bravo."""
    alpha = Team(name="Alpha Aces", abbreviation="ALP", sport="NFL")
    bravo = Team(name="Bravo Bears", abbreviation="BRV", sport="NFL")
    db.add_all([alpha, bravo])
    db.flush()

    def game(week, status, start):
        row = Game(
            sport="NFL", season="2026", home_team_id=alpha.id, away_team_id=bravo.id,
            start_time=start, week=week, status=status,
        )  # fmt: skip
        db.add(row)
        db.flush()
        return row

    played = game(1, "final", _START)
    game(2, "scheduled", datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=3))
    players = {}
    for name, receptions in (("Wes Receiver", 8), ("Rex Reserve", 2)):
        player = Player(name=name, sport="NFL", team_id=alpha.id, position="WR")
        db.add(player)
        db.flush()
        db.add(
            PlayerGameStatsNFL(
                player_id=player.id, game_id=played.id, receptions=receptions, receiving_yards=50
            )
        )
        players[name] = player
    db.flush()
    return alpha, players


@pytest.fixture
def static(monkeypatch):
    """A source giving the two receivers fixed stat lines: 13 and 7 PPR points."""
    return install(
        monkeypatch,
        {
            "Wes Receiver": {"receptions": 8, "receiving_yards": 50},
            "Rex Reserve": {"receptions": 2, "receiving_yards": 50},
        },
    )


def test_lists_the_available_sources(client):
    body = client.get("/api/v1/projections/sources").json()

    assert [s["name"] for s in body] == ["sleeper"]  # recent form and the blend were removed
    assert all(s["label"] and s["description"] and s["sports"] for s in body)


def test_compares_players_best_first_under_the_default_scoring(client, league, static):
    _, players = league
    ids = [players["Rex Reserve"].id, players["Wes Receiver"].id]

    response = client.get(
        "/api/v1/projections", params={"sport": "NFL", "player_id": ids, "source": "static"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "static"
    assert [item["name"] for item in body["items"]] == ["Wes Receiver", "Rex Reserve"]
    best = body["items"][0]
    assert best["fantasy_points"] == 13.0  # 8 receptions + 50 yards at PPR
    assert best["status"] == "ok" and best["game"]["opponent"]["abbreviation"] == "BRV"
    assert (
        best["games_sampled"] == 1
        and best["spread_basis"] == "blended"
        or best["spread_basis"] == "position"
    )
    assert best["low"] < 13.0 < best["high"] and best["chance_best"] > 0.5


def test_the_scoring_parameter_changes_the_projection(client, league, static):
    _, players = league
    standard = '{"name":"Standard","sport":"NFL","player_weights":{"receiving_yards":0.1}}'

    response = client.get(
        f"/api/v1/players/{players['Wes Receiver'].id}/projection",
        params={"scoring": standard, "source": "static"},
    )

    assert response.status_code == 200
    assert response.json()["fantasy_points"] == 5.0


def test_a_defense_can_be_projected_and_compared(client, league, static):
    alpha, players = league
    static.lines["Alpha Aces D/ST"] = {"sacks": 3, "points_allowed": 17}

    single = client.get(f"/api/v1/defenses/{alpha.id}/projection?source=static")
    mixed = client.get(
        "/api/v1/projections",
        params={
            "sport": "NFL",
            "defense_id": [alpha.id],
            "player_id": players["Wes Receiver"].id,
            "source": "static",
        },
    )

    assert single.status_code == 200 and single.json()["kind"] == "defense"
    assert single.json()["status"] == "ok" and single.json()["fantasy_points"] is not None
    assert {item["kind"] for item in mixed.json()["items"]} == {"player", "defense"}


def test_unknown_things_are_reported_as_the_callers_mistake(client, league):
    _, players = league
    wes = players["Wes Receiver"].id

    assert client.get("/api/v1/players/0/projection").status_code == 404
    assert client.get("/api/v1/defenses/0/projection").status_code == 404
    assert client.get(f"/api/v1/players/{wes}/projection?source=oracle").status_code == 422
    assert client.get("/api/v1/projections?sport=NFL").status_code == 422
    assert client.get("/api/v1/projections?sport=NFL&player_id=0").status_code == 422
    assert client.get(f"/api/v1/projections?sport=NBA&player_id={wes}").status_code == 422
    assert client.get(f"/api/v1/players/{wes}/projection?scoring=nonsense").status_code == 422


def test_a_source_that_cannot_be_reached_is_a_502(client, league, monkeypatch):
    _, players = league
    down = SleeperProvider(
        httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    )
    monkeypatch.setitem(base.PROVIDERS, "sleeper", down)

    response = client.get(
        f"/api/v1/players/{players['Wes Receiver'].id}/projection", params={"source": "sleeper"}
    )

    assert response.status_code == 502
    assert "Sleeper" in response.json()["detail"]


def test_sleeper_projections_are_rescored_and_reported_through_the_api(client, league, monkeypatch):
    _, players = league

    def sleeper(request: httpx.Request) -> httpx.Response:
        rows = [
            {
                "player": {"first_name": "Wes", "last_name": "Receiver", "position": "WR"},
                "team": "ALP", "opponent": "BRV",
                "stats": {"rec": 6.0, "rec_yd": 80.0, "pts_ppr": 99.0},
            }
        ]  # fmt: skip
        return httpx.Response(200, json=rows)

    provider = SleeperProvider(httpx.Client(transport=httpx.MockTransport(sleeper)))
    monkeypatch.setitem(base.PROVIDERS, "sleeper", provider)

    response = client.get(
        f"/api/v1/players/{players['Wes Receiver'].id}/projection", params={"source": "sleeper"}
    )

    body = response.json()
    assert response.status_code == 200
    assert body["source"] == "sleeper" and body["fantasy_points"] == 14.0  # not Sleeper's 99
    # Sleeper gives no range, so it is our typical spread for a WR: 55% of the projection
    assert body["spread_basis"] == "position"
    assert body["low"] < body["fantasy_points"] < body["high"]
    assert "fourth_down_stops" not in body["unprojected_stats"]  # players don't have those


def test_top_projections_lists_a_slots_best_players_and_the_week(client, league, static):
    response = client.get(
        "/api/v1/projections/top",
        params={"sport": "NFL", "slot": "wr", "source": "static", "week": 1, "limit": 5},
    )

    body = response.json()
    assert response.status_code == 200 and body["week"] == 1 and body["total"] == 2
    assert [item["name"] for item in body["items"]] == ["Wes Receiver", "Rex Reserve"]
    first = body["items"][0]
    assert first["headshot_url"] is None and first["game"]["status"] in {"scheduled", "final"}


def test_top_projections_pages_with_an_offset(client, league, static):
    params = {"sport": "NFL", "slot": "WR", "source": "static", "limit": 1}

    first = client.get("/api/v1/projections/top", params=params).json()
    second = client.get("/api/v1/projections/top", params={**params, "offset": 1}).json()
    past_the_end = client.get("/api/v1/projections/top", params={**params, "offset": 5}).json()

    assert [i["name"] for i in first["items"]] == ["Wes Receiver"]
    assert [i["name"] for i in second["items"]] == ["Rex Reserve"]
    assert first["total"] == second["total"] == past_the_end["total"] == 2
    assert past_the_end["items"] == []


def test_the_week_defaults_to_the_current_one(client, league, static):
    _, players = league

    body = client.get(
        "/api/v1/projections",
        params={"sport": "NFL", "player_id": players["Wes Receiver"].id, "source": "static"},
    ).json()

    assert body["week"] == 2  # the upcoming game; week 1 is final


def test_top_projections_rejects_a_bad_slot_or_source(client, league):
    assert client.get("/api/v1/projections/top?sport=NFL&slot=IDP").status_code == 422
    assert client.get("/api/v1/projections/top?sport=NFL&slot=WR&source=oracle").status_code == 422
    assert client.get("/api/v1/projections/top?sport=NFL").status_code == 422
