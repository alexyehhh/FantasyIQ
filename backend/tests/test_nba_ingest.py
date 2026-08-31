import httpx
import pytest
from pydantic import ValidationError

from data_pipeline.espn import ESPNClient
from data_pipeline.nba_ingest import (
    ESPNNBAClient,
    GamePayload,
    IngestionError,
    _parse_minutes,
    _status_state,
)


def _game_payload() -> dict:
    team = {
        "id": 10,
        "name": "Warriors",
        "full_name": "Golden State Warriors",
        "abbreviation": "GSW",
    }
    return {
        "id": "401705000",
        "season": 2024,
        "datetime": "2025-01-05T23:00:00.000Z",
        "status_state": "final",
        "home_team": team,
        "visitor_team": {
            **team,
            "id": 6,
            "full_name": "Cleveland Cavaliers",
            "abbreviation": "CLE",
        },
    }


def test_minutes_are_normalized_to_decimal_minutes():
    assert _parse_minutes("30:30") == 30.5
    assert _parse_minutes("PT25M01.00S") == 25 + 1 / 60
    assert _parse_minutes("12") == 12.0
    assert _parse_minutes(0) == 0.0
    assert _parse_minutes(None) == 0.0


def test_invalid_minutes_are_rejected():
    with pytest.raises(IngestionError):
        _parse_minutes("not-a-minute-value")


def test_status_accepts_espn_competition_status():
    assert _status_state({"competitions": [{"status": {"type": {"state": "post"}}}]}) == "final"


def test_game_payload_requires_both_teams():
    payload = _game_payload()
    del payload["visitor_team"]
    with pytest.raises(ValidationError):
        GamePayload.model_validate(payload)


def test_espn_client_builds_documented_scoreboard_request():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"events": []})

    transport_client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://site.api.espn.com"
    )
    client = ESPNClient(client=transport_client)
    try:
        assert client.scoreboard("football", "nfl", "20250907")["events"] == []
    finally:
        client.close()

    assert requests[0].url.path == "/apis/site/v2/sports/football/nfl/scoreboard"
    assert requests[0].url.params["dates"] == "20250907"


def test_espn_client_normalizes_summary():
    client = ESPNNBAClient(summary_factory=lambda event_id: _summary_payload())
    game, stats = client.get_game("401705000")

    assert game.id == "401705000"
    assert game.season == 2025
    assert game.status_state == "final"
    assert stats[0].player.first_name == "Jaylen"
    assert stats[0].min == "PT25M01.00S"


def _summary_payload() -> dict:
    return {
        "header": {
            "id": "401705000",
            "season": {"year": 2025},
            "competitions": [{
                "date": "2025-01-05T23:00:00Z",
                "competitors": [
                    {
                        "homeAway": "home",
                        "team": {
                            "id": "10",
                            "displayName": "Golden State Warriors",
                            "name": "Warriors",
                            "abbreviation": "GSW",
                        },
                    },
                    {
                        "homeAway": "away",
                        "team": {
                            "id": "6",
                            "displayName": "Cleveland Cavaliers",
                            "name": "Cavaliers",
                            "abbreviation": "CLE",
                        },
                    },
                ],
            }],
            "status": {"type": {"state": "post"}},
        },
        "boxscore": {
            "players": [{
                "team": {"id": "10"},
                "statistics": [{
                    "keys": ["MIN", "PTS", "REB", "AST", "STL", "BLK", "TO", "FGA", "3PA"],
                    "athletes": [{
                        "athlete": _live_player_for_espn(),
                        "statistics": ["PT25M01.00S", 23, 7, 1, 1, 0, 1, 18, 9],
                    }],
                }],
            }],
        },
    }


def _live_player_for_espn() -> dict:
    return {
        "id": "70",
        "firstName": "Jaylen",
        "lastName": "Brown",
        "displayName": "Jaylen Brown",
        "position": {"abbreviation": "G"},
        "jersey": "7",
    }
