import httpx
import pytest
from pydantic import ValidationError

from data_pipeline.espn import ESPNClient
from data_pipeline.espn_common import IngestionError, status_state
from data_pipeline.nfl_ingest import (
    ESPNNFLClient,
    GamePayload,
    _split_completions_attempts,
)


def _game_payload() -> dict:
    team = {
        "id": 12,
        "name": "Chiefs",
        "full_name": "Kansas City Chiefs",
        "abbreviation": "KC",
    }
    return {
        "id": "401671800",
        "season": 2024,
        "datetime": "2024-09-08T17:00:00.000Z",
        "status_state": "final",
        "home_team": team,
        "visitor_team": {
            **team,
            "id": 2,
            "full_name": "Buffalo Bills",
            "abbreviation": "BUF",
        },
    }


def test_completions_attempts_split_from_espns_combined_string():
    assert _split_completions_attempts("24/37") == (24, 37)
    assert _split_completions_attempts(None) == (0, 0)
    assert _split_completions_attempts("garbage") == (0, 0)


def test_status_accepts_espn_competition_status():
    assert status_state({"competitions": [{"status": {"type": {"state": "post"}}}]}) == "final"


def test_status_rejects_unrecognized_state():
    with pytest.raises(IngestionError):
        status_state({"status": {"type": {"state": "weird"}}})


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
        assert client.scoreboard("football", "nfl", "20240908")["events"] == []
    finally:
        client.close()

    assert requests[0].url.path == "/apis/site/v2/sports/football/nfl/scoreboard"
    assert requests[0].url.params["dates"] == "20240908"


def test_espn_client_merges_stats_across_categories():
    """A QB shows up in both the passing and rushing groups; his stat
    line should combine both rather than only keeping the last group."""
    client = ESPNNFLClient(summary_factory=lambda event_id: _summary_payload())
    game, stats = client.get_game("401671800")

    assert game.id == "401671800"
    assert game.season == 2024
    assert game.status_state == "final"

    by_id = {stat.id for stat in stats}
    assert by_id == {30, 31}

    qb = next(stat for stat in stats if stat.id == 30)
    assert qb.player.first_name == "Patrick"
    assert qb.passing_completions == 24
    assert qb.passing_attempts == 37
    assert qb.passing_yards == 291
    assert qb.passing_touchdowns == 2
    assert qb.interceptions == 1
    assert qb.rushing_attempts == 3
    assert qb.rushing_yards == 12
    assert qb.rushing_touchdowns == 0

    receiver = next(stat for stat in stats if stat.id == 31)
    assert receiver.player.first_name == "Travis"
    assert receiver.receptions == 7
    assert receiver.receiving_targets == 9
    assert receiver.receiving_yards == 89
    assert receiver.receiving_touchdowns == 1


def _summary_payload() -> dict:
    return {
        "header": {
            "id": "401671800",
            "season": {"year": 2024},
            "competitions": [{
                "date": "2024-09-08T17:00:00Z",
                "competitors": [
                    {
                        "homeAway": "home",
                        "team": {
                            "id": "12",
                            "displayName": "Kansas City Chiefs",
                            "name": "Chiefs",
                            "abbreviation": "KC",
                        },
                    },
                    {
                        "homeAway": "away",
                        "team": {
                            "id": "2",
                            "displayName": "Buffalo Bills",
                            "name": "Bills",
                            "abbreviation": "BUF",
                        },
                    },
                ],
            }],
            "status": {"type": {"state": "post"}},
        },
        "boxscore": {
            "players": [{
                "team": {"id": "12"},
                "statistics": [
                    {
                        "name": "passing",
                        "keys": ["C/ATT", "YDS", "TD", "INT"],
                        "athletes": [{
                            "athlete": _mahomes(),
                            "stats": ["24/37", "291", "2", "1"],
                        }],
                    },
                    {
                        "name": "rushing",
                        "keys": ["CAR", "YDS", "TD"],
                        "athletes": [{
                            "athlete": _mahomes(),
                            "stats": ["3", "12", "0"],
                        }],
                    },
                    {
                        "name": "receiving",
                        "keys": ["REC", "TGTS", "YDS", "TD"],
                        "athletes": [{
                            "athlete": _kelce(),
                            "stats": ["7", "9", "89", "1"],
                        }],
                    },
                ],
            }],
        },
    }


def _mahomes() -> dict:
    return {
        "id": "30",
        "firstName": "Patrick",
        "lastName": "Mahomes",
        "displayName": "Patrick Mahomes",
        "position": {"abbreviation": "QB"},
        "jersey": "15",
    }


def _kelce() -> dict:
    return {
        "id": "31",
        "firstName": "Travis",
        "lastName": "Kelce",
        "displayName": "Travis Kelce",
        "position": {"abbreviation": "TE"},
        "jersey": "87",
    }


def test_espn_client_reads_real_box_score_where_keys_are_machine_names():
    """Real ESPN payloads carry machine names in "keys" and the display names
    ("C/ATT", "YDS", ...) in "labels"; stats were silently all zero when only
    "keys" was read."""
    payload = _summary_payload()
    payload["boxscore"]["players"][0]["statistics"] = [
        {
            "name": "passing",
            "keys": ["completions/passingAttempts", "passingYards", "yardsPerPassAttempt",
                     "passingTouchdowns", "interceptions"],
            "labels": ["C/ATT", "YDS", "AVG", "TD", "INT"],
            "athletes": [{"athlete": _mahomes(), "stats": ["17/28", "131", "4.7", "1", "1"]}],
        },
        {
            "name": "receiving",
            "keys": ["receptions", "receivingYards", "yardsPerReception",
                     "receivingTouchdowns", "longReception", "receivingTargets"],
            "labels": ["REC", "YDS", "AVG", "TD", "LONG", "TGTS"],
            "athletes": [{"athlete": _kelce(), "stats": ["4", "43", "10.8", "1", "19", "5"]}],
        },
        {
            "name": "fumbles",
            "keys": ["fumbles", "fumblesLost", "fumblesRecovered"],
            "labels": ["FUM", "LOST", "REC"],
            "athletes": [{"athlete": _mahomes(), "stats": ["3", "1", "1"]}],
        },
    ]
    _, stats = ESPNNFLClient(summary_factory=lambda _: payload).get_game("401671800")

    qb = next(stat for stat in stats if stat.id == 30)
    assert (qb.passing_completions, qb.passing_attempts) == (17, 28)
    assert (qb.passing_yards, qb.passing_touchdowns, qb.interceptions) == (131, 1, 1)
    assert qb.fumbles_lost == 1
    te = next(stat for stat in stats if stat.id == 31)
    assert (te.receptions, te.receiving_targets, te.receiving_yards) == (4, 5, 43)
