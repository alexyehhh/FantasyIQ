import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.db.models import Game, Player, PlayerGameStats, Team
from app.db.session import SessionLocal
from data_pipeline.espn import ESPNClient
from data_pipeline.nba_ingest import (
    ESPNNBAClient,
    GamePayload,
    IngestionError,
    _attempts,
    _made,
    _parse_minutes,
    _status_state,
    ingest_game,
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
    assert (game.home_score, game.visitor_score) == (112, 104)
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
                        "score": "112",
                        "team": {
                            "id": "10",
                            "displayName": "Golden State Warriors",
                            "name": "Warriors",
                            "abbreviation": "GSW",
                        },
                    },
                    {
                        "homeAway": "away",
                        "score": "104",
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


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _ingest(db):
    game, stats = ESPNNBAClient(summary_factory=lambda _: _summary_payload()).get_game("401705000")
    return ingest_game(db, game, stats)


def test_ingest_game_stores_scores_and_a_correctly_labelled_season(db):
    _ingest(db)

    record = db.scalar(select(Game).where(Game.external_id == "401705000"))
    assert (record.home_score, record.away_score) == (112, 104)
    assert record.season == "2024-25"  # ESPN's 2025 is the season *ending* in 2025


def test_ingest_game_namespaces_team_ids_by_sport(db):
    _ingest(db)

    team = db.scalar(select(Team).where(Team.abbreviation == "GSW"))
    assert team.external_id == "nba:10"


def test_ingest_game_seeds_a_new_player_from_the_box_score(db):
    _ingest(db)

    player = db.scalar(select(Player).where(Player.external_id == "70"))
    assert player.name == "Jaylen Brown"
    assert player.position == "G"
    assert player.active is True
    assert player.team.abbreviation == "GSW"


def test_ingest_game_does_not_overwrite_a_players_current_team_or_status(db):
    current = Team(name="Current Team", abbreviation="CUR", sport="NBA")
    db.add(current)
    db.flush()
    db.add(Player(external_id="70", name="Jaylen Brown", sport="NBA", team_id=current.id,
                  position="F", active=False))
    db.flush()

    _ingest(db)

    player = db.scalar(select(Player).where(Player.external_id == "70"))
    assert player.team_id == current.id
    assert player.position == "F"
    assert player.active is False


def test_attempts_come_from_the_made_attempted_string():
    assert _attempts("9-17") == 17
    assert _attempts("0-1") == 1
    assert _attempts("0-0") == 0
    assert _attempts(17) == 17
    assert _attempts(None) == 0


def test_shooting_attempts_are_read_from_real_combined_fields():
    payload = _summary_payload()
    payload["boxscore"]["players"][0]["statistics"] = [{
        "keys": ["minutes", "points", "fieldGoalsMade-fieldGoalsAttempted",
                 "threePointFieldGoalsMade-threePointFieldGoalsAttempted", "rebounds"],
        "athletes": [{
            "athlete": _live_player_for_espn(),
            "stats": ["34", "23", "9-17", "2-6", "9"],
        }],
    }]

    _, stats = ESPNNBAClient(summary_factory=lambda _: payload).get_game("401705000")

    assert (stats[0].fga, stats[0].fg3a) == (17, 6)


def test_made_and_attempted_are_split_from_espns_shooting_strings():
    assert (_made("9-17"), _attempts("9-17")) == (9, 17)
    assert (_made("0-0"), _attempts("0-0")) == (0, 0)
    assert _made(None) == 0
    assert _made(4) == 4  # older payloads sent a bare number


def _real_box_score_payload() -> dict:
    """The stat layout of a real ESPN NBA box score, one player line included."""
    payload = _summary_payload()
    payload["boxscore"]["players"][0]["statistics"] = [{
        "keys": [
            "minutes", "points", "fieldGoalsMade-fieldGoalsAttempted",
            "threePointFieldGoalsMade-threePointFieldGoalsAttempted",
            "freeThrowsMade-freeThrowsAttempted", "rebounds", "assists", "turnovers",
            "steals", "blocks", "offensiveRebounds", "defensiveRebounds", "fouls", "plusMinus",
        ],
        "athletes": [{
            "athlete": _live_player_for_espn(),
            "stats": ["26", "24", "8-15", "3-8", "5-6", "6", "2", "0", "1", "0", "3", "3", "3",
                      "-8"],
        }],
    }]
    return payload


def test_espn_client_reads_makes_and_free_throws_from_a_real_box_score():
    _, stats = ESPNNBAClient(summary_factory=lambda _: _real_box_score_payload()).get_game("1")

    line = stats[0]
    assert (line.pts, line.fgm, line.fga) == (24, 8, 15)
    assert (line.fg3m, line.fg3a) == (3, 8)
    assert (line.ftm, line.fta) == (5, 6)


def test_a_line_with_more_makes_than_attempts_is_rejected():
    payload = _real_box_score_payload()
    payload["boxscore"]["players"][0]["statistics"][0]["athletes"][0]["stats"][4] = "7-6"

    with pytest.raises(IngestionError):
        ESPNNBAClient(summary_factory=lambda _: payload).get_game("1")


def test_ingest_game_stores_makes_and_free_throws_and_upserts_on_rerun(db):
    def ingest(payload):
        game, stats = ESPNNBAClient(summary_factory=lambda _: payload).get_game("401705000")
        ingest_game(db, game, stats)

    ingest(_real_box_score_payload())
    line = db.scalar(select(PlayerGameStats).join(Player).where(Player.external_id == "70"))
    assert (line.field_goals_made, line.field_goal_attempts) == (8, 15)
    assert (line.three_pointers_made, line.three_point_attempts) == (3, 8)
    assert (line.free_throws_made, line.free_throw_attempts) == (5, 6)

    corrected = _real_box_score_payload()
    corrected["boxscore"]["players"][0]["statistics"][0]["athletes"][0]["stats"][4] = "6-6"
    ingest(corrected)  # a re-run updates the same row instead of adding a second one
    rows = db.scalars(select(PlayerGameStats).join(Player).where(Player.external_id == "70")).all()
    assert len(rows) == 1
    assert rows[0].free_throws_made == 6


def _stats_final_after_ingesting(db, mutate=None):
    payload = _summary_payload()
    if mutate:
        mutate(payload)
    game, stats = ESPNNBAClient(summary_factory=lambda _: payload).get_game("401705000")
    ingest_game(db, game, stats)
    return db.scalar(select(Game).where(Game.external_id == "401705000"))


def test_stats_are_final_only_once_a_finished_game_has_a_box_score(db):
    assert _stats_final_after_ingesting(db).stats_final is True


def test_stats_taken_while_a_game_is_on_are_not_final(db):
    def live(payload):
        payload["header"]["status"] = {"type": {"state": "in"}}

    record = _stats_final_after_ingesting(db, live)

    assert (record.status, record.stats_final) == ("in_progress", False)


def test_a_finished_game_whose_box_score_is_not_posted_yet_is_not_final(db):
    def no_box_score(payload):
        payload["boxscore"] = {"players": []}

    record = _stats_final_after_ingesting(db, no_box_score)

    assert (record.status, record.stats_final) == ("final", False)
