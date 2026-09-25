import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.db.models import (
    FieldGoalKick,
    Game,
    Player,
    PlayerGameStatsNFL,
    Team,
    TeamGameStatsNFL,
)
from app.db.session import SessionLocal
from data_pipeline.espn import ESPNClient
from data_pipeline.espn_common import IngestionError, status_state
from data_pipeline.nfl_ingest import (
    ESPNNFLClient,
    GamePayload,
    _split_completions_attempts,
    ingest_game,
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
    game, stats, _, _ = client.get_game("401671800")

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
    _, stats, _, _ = ESPNNFLClient(summary_factory=lambda _: payload).get_game("401671800")

    qb = next(stat for stat in stats if stat.id == 30)
    assert (qb.passing_completions, qb.passing_attempts) == (17, 28)
    assert (qb.passing_yards, qb.passing_touchdowns, qb.interceptions) == (131, 1, 1)
    assert qb.fumbles_lost == 1
    te = next(stat for stat in stats if stat.id == 31)
    assert (te.receptions, te.receiving_targets, te.receiving_yards) == (4, 5, 43)


def _zvada() -> dict:
    return {
        "id": "40",
        "firstName": "Dominic",
        "lastName": "Zvada",
        "displayName": "Dominic Zvada",
        "position": {"abbreviation": "PK"},
        "jersey": "3",
    }


def _kicker_payload() -> dict:
    """A real ESPN kicking/return layout: the kicker has FG/XP, a returner has TDs."""
    payload = _summary_payload()
    payload["boxscore"]["players"][0]["statistics"] = [
        {
            "name": "kicking",
            "keys": ["fieldGoalsMade/fieldGoalAttempts", "fieldGoalPct", "longFieldGoalMade",
                     "extraPointsMade/extraPointAttempts", "totalKickingPoints"],
            "labels": ["FG", "PCT", "LONG", "XP", "PTS"],
            "athletes": [{"athlete": _zvada(), "stats": ["2/3", "66.7", "52", "3/3", "9"]}],
        },
        {
            "name": "kickReturns",
            "keys": ["kickReturns", "kickReturnYards", "yardsPerKickReturn", "longKickReturn",
                     "kickReturnTouchdowns"],
            "labels": ["NO", "YDS", "AVG", "LONG", "TD"],
            "athletes": [{"athlete": _kelce(), "stats": ["2", "153", "76.5", "98", "1"]}],
        },
        {
            "name": "puntReturns",
            "keys": ["puntReturns", "puntReturnYards", "yardsPerPuntReturn", "longPuntReturn",
                     "puntReturnTouchdowns"],
            "labels": ["NO", "YDS", "AVG", "LONG", "TD"],
            "athletes": [{"athlete": _kelce(), "stats": ["1", "70", "70.0", "70", "1"]}],
        },
    ]
    return payload


def test_espn_client_reads_kicking_and_return_touchdowns_from_a_real_box_score():
    client = ESPNNFLClient(summary_factory=lambda _: _kicker_payload())
    _, stats, _, _ = client.get_game("401671800")

    kicker = next(stat for stat in stats if stat.id == 40)
    assert (kicker.field_goals_made, kicker.field_goal_attempts) == (2, 3)
    assert (kicker.extra_points_made, kicker.extra_point_attempts) == (3, 3)
    assert (kicker.kick_return_touchdowns, kicker.punt_return_touchdowns) == (0, 0)
    # Both return groups label their touchdowns "TD"; each must land in its own column.
    returner = next(stat for stat in stats if stat.id == 31)
    assert (returner.kick_return_touchdowns, returner.punt_return_touchdowns) == (1, 1)
    assert returner.field_goal_attempts == 0


def test_a_kick_line_with_more_makes_than_attempts_is_rejected():
    payload = _kicker_payload()
    payload["boxscore"]["players"][0]["statistics"][0]["athletes"][0]["stats"][0] = "4/3"

    with pytest.raises(IngestionError):
        ESPNNFLClient(summary_factory=lambda _: payload).get_game("401671800")


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def test_ingest_game_stores_kicking_and_upserts_on_rerun(db):
    def ingest(payload):
        client = ESPNNFLClient(summary_factory=lambda _: payload)
        game, stats, kicks, _ = client.get_game("401671800")
        ingest_game(db, game, stats, kicks)

    def kicker_rows():
        return db.scalars(
            select(PlayerGameStatsNFL).join(Player).where(Player.external_id == "40")
        ).all()

    ingest(_kicker_payload())
    (row,) = kicker_rows()
    assert (row.field_goals_made, row.field_goal_attempts) == (2, 3)
    assert (row.extra_points_made, row.extra_point_attempts) == (3, 3)

    corrected = _kicker_payload()
    corrected["boxscore"]["players"][0]["statistics"][0]["athletes"][0]["stats"][0] = "3/3"
    ingest(corrected)  # re-running the game updates the row rather than duplicating it
    (row,) = kicker_rows()
    assert row.field_goals_made == 3


def _kick_play(play_id: str, kind: str, text: str, distance: int, team_id: str = "12") -> dict:
    """A field goal play as ESPN sends it. `teamParticipants` lists both teams with the
    kicking team not necessarily first, so the kicking team must come from `start.team`."""
    return {
        "id": play_id,
        "type": {"text": kind},
        "text": text,
        "statYardage": distance,
        "start": {"team": {"id": team_id}},
        "teamParticipants": [{"id": "2"}, {"id": "12"}],
    }


def _with_plays(payload: dict, plays: list[dict]) -> dict:
    payload["drives"] = {"previous": [{"plays": plays}]}
    return payload


_MADE_24 = _kick_play("p1", "Field Goal Good", "D.Zvada 24 yard field goal is GOOD, Center", 24)
_MADE_52 = _kick_play("p2", "Field Goal Good", "D.Zvada 52 yard field goal is GOOD, Center", 52)
_MISSED_43 = _kick_play(
    "p3", "Field Goal Missed", "D.Zvada 43 yard field goal is No Good, Wide Left", 43
)
# ESPN reports a blocked kick's yardage as 0; its distance is only in the text.
_BLOCKED_49 = _kick_play(
    "p4", "Blocked Field Goal", "D.Zvada 49 yard field goal is BLOCKED (C.Granderson)", 0
)


def _kicks(payload: dict):
    return ESPNNFLClient(summary_factory=lambda _: payload).get_game("401671800")[2]


def test_kicks_carry_distance_result_and_the_kicker_from_the_plays():
    kicks = _kicks(_with_plays(_kicker_payload(), [_MADE_24, _MADE_52, _MISSED_43]))

    assert [(k.play_id, k.kicker_id, k.distance, k.result) for k in kicks] == [
        ("p1", 40, 24, "made"),
        ("p2", 40, 52, "made"),
        ("p3", 40, 43, "missed"),
    ]


def test_a_blocked_kick_takes_its_distance_from_the_text_and_counts_as_an_attempt():
    kicks = _kicks(_with_plays(_kicker_payload(), [_MADE_24, _MADE_52, _BLOCKED_49]))

    assert (kicks[2].distance, kicks[2].result) == (49, "blocked")


def test_a_game_with_no_play_data_has_no_kicks_rather_than_an_empty_list():
    assert _kicks(_kicker_payload()) is None


def test_kicks_that_do_not_add_up_to_the_box_score_are_rejected():
    payload = _with_plays(_kicker_payload(), [_MADE_24, _MADE_52])  # box score says 2/3

    with pytest.raises(IngestionError, match="do not match the box score"):
        _kicks(payload)


def _second_kicker() -> dict:
    return {
        **_zvada(),
        "id": "41",
        "firstName": "Harrison",
        "lastName": "Mevis",
        "displayName": "Harrison Mevis",
    }


def test_two_kickers_on_a_team_are_told_apart_by_the_name_in_the_play_text():
    payload = _kicker_payload()
    kicking = payload["boxscore"]["players"][0]["statistics"][0]
    kicking["athletes"][0]["stats"] = ["2/2", "100.0", "52", "2/2", "8"]
    kicking["athletes"].append(
        {"athlete": _second_kicker(), "stats": ["0/1", "0.0", "0", "1/1", "1"]}
    )
    mevis_miss = _kick_play(
        "p5", "Field Goal Missed", "H.Mevis 43 yard field goal is No Good, Wide Left", 43
    )

    kicks = _kicks(_with_plays(payload, [_MADE_24, _MADE_52, mevis_miss]))

    assert {(k.play_id, k.kicker_id) for k in kicks} == {("p1", 40), ("p2", 40), ("p5", 41)}


def test_a_kick_that_cannot_be_attributed_is_rejected():
    payload = _kicker_payload()
    kicking = payload["boxscore"]["players"][0]["statistics"][0]
    kicking["athletes"].append(
        {"athlete": _second_kicker(), "stats": ["0/0", "0.0", "0", "0/0", "0"]}
    )
    stranger = _kick_play("p9", "Field Goal Good", "J.Nobody 30 yard field goal is GOOD", 30)

    with pytest.raises(IngestionError, match="Cannot attribute"):
        _kicks(_with_plays(payload, [_MADE_24, _MADE_52, stranger]))


def _stored_kicks(db):
    return sorted(
        (k.external_play_id, k.distance, k.result)
        for k in db.scalars(select(FieldGoalKick).join(Player).where(Player.external_id == "40"))
    )


def _ingest_plays(db, payload):
    game, stats, kicks, _ = ESPNNFLClient(summary_factory=lambda _: payload).get_game("401671800")
    ingest_game(db, game, stats, kicks)


def test_ingest_game_mirrors_kicks_upserting_and_dropping_stale_ones(db):
    _ingest_plays(db, _with_plays(_kicker_payload(), [_MADE_24, _MADE_52, _MISSED_43]))
    assert _stored_kicks(db) == [("p1", 24, "made"), ("p2", 52, "made"), ("p3", 43, "missed")]

    # A re-run is idempotent, and a correction updates the row and removes a kick ESPN dropped.
    corrected = _kicker_payload()
    corrected["boxscore"]["players"][0]["statistics"][0]["athletes"][0]["stats"] = [
        "2/2", "100.0", "52", "3/3", "9"
    ]
    _ingest_plays(db, _with_plays(corrected, [{**_MADE_24, "statYardage": 25}, _MADE_52]))
    assert _stored_kicks(db) == [("p1", 25, "made"), ("p2", 52, "made")]


def test_ingest_game_leaves_stored_kicks_alone_when_the_payload_has_no_play_data(db):
    _ingest_plays(db, _with_plays(_kicker_payload(), [_MADE_24, _MADE_52, _MISSED_43]))

    _ingest_plays(db, _kicker_payload())  # a summary without drives must not wipe the kicks

    assert len(_stored_kicks(db)) == 3


def _play(play_id, kind, team_id, home, away, text=""):
    return {
        "id": play_id,
        "type": {"text": kind},
        "text": text,
        "start": {"team": {"id": str(team_id)}},
        "homeScore": home,
        "awayScore": away,
    }


def _drive(team_id, result, *plays):
    return {"team": {"id": str(team_id)}, "result": result, "plays": list(plays)}


def _team_box(team_id, yards, sacks_taken, interceptions_thrown, fumbles_lost, def_tds):
    """Team totals as ESPN lists them, including the duplicated "interceptions" entry."""
    totals = [
        ("totalYards", yards),
        ("sacksYardsLost", sacks_taken),
        ("interceptions", interceptions_thrown),
        ("fumblesLost", fumbles_lost),
        ("interceptions", interceptions_thrown),
        ("defensiveTouchdowns", def_tds),
    ]
    return {
        "team": {"id": str(team_id)},
        "statistics": [{"name": name, "displayValue": str(value)} for name, value in totals],
    }


def _defense_payload() -> dict:
    """KC (12, home) beats BUF (2) 17-9. KC's defense scores on a BUF interception, stops BUF
    on downs and blocks a punt; BUF scores a safety on a KC drive. A play typed "Safety" that
    was nullified by a penalty must not count."""
    payload = _summary_payload()
    home, away = payload["header"]["competitions"][0]["competitors"]
    home["score"], away["score"] = "17", "9"
    payload["boxscore"]["teams"] = [
        _team_box(12, 400, "2-10", 0, 0, 1),
        _team_box(2, 300, "3-20", 1, 1, 0),
    ]
    payload["drives"] = {"previous": [
        _drive(12, "TD", _play("d1", "Rushing Touchdown", 12, 7, 0)),
        _drive(2, "INT TD", _play("d2", "Interception Return Touchdown", 2, 14, 0)),
        _drive(
            2, "DOWNS",
            _play("d3a", "Blocked Punt", 2, 14, 0),
            _play("d3b", "Safety", 2, 14, 0, "SAFETY NULLIFIED by Penalty"),
        ),
        _drive(12, "SF", _play("d4", "Pass Incompletion", 12, 14, 2, "Team Safety")),
        _drive(2, "TD", _play("d5", "Passing Touchdown", 2, 14, 9)),
        _drive(12, "FG", _play("d6", "Field Goal Good", 12, 17, 9)),
    ]}
    payload["scoringPlays"] = [{"scoringType": {"name": "safety"}, "team": {"id": "2"}}]
    # The defensive-touchdown check needs the FG play's kicker; keep the box score kicker-free.
    payload["drives"]["previous"][5]["plays"][0]["type"]["text"] = "Punt"
    return payload


def _defense(payload):
    client = ESPNNFLClient(summary_factory=lambda _: payload)
    return {line.team_id: line for line in client.get_game("401671800")[3]}


def test_team_defense_lines_for_both_teams_from_box_totals_and_drives():
    kc, buf = _defense(_defense_payload())[12], _defense(_defense_payload())[2]

    assert (kc.sacks, kc.interceptions, kc.fumble_recoveries) == (3, 1, 1)  # BUF's turnovers
    assert (kc.defensive_touchdowns, kc.return_touchdowns, kc.safeties) == (1, 0, 0)
    assert (kc.fourth_down_stops, kc.blocked_kicks, kc.yards_allowed) == (1, 1, 300)
    assert (buf.sacks, buf.interceptions, buf.fumble_recoveries) == (2, 0, 0)
    assert (buf.defensive_touchdowns, buf.safeties, buf.fourth_down_stops) == (0, 1, 0)
    assert (buf.blocked_kicks, buf.yards_allowed) == (0, 400)


def test_points_allowed_leave_out_the_defensive_touchdown_and_the_safety():
    lines = _defense(_defense_payload())

    # BUF scored 9, but 2 of it was the safety: only its 7-point touchdown counts against KC.
    assert lines[12].points_allowed == 7
    # KC scored 17, but 7 was the interception return with its extra point.
    assert lines[2].points_allowed == 10


def test_a_penalized_safety_play_is_not_counted():
    payload = _defense_payload()  # the "Safety" play in drive 3 was nullified by a penalty

    assert _defense(payload)[2].safeties == 1  # only the real one, from drive 4


def test_return_touchdowns_are_split_from_the_teams_defensive_touchdowns():
    payload = _defense_payload()
    payload["boxscore"]["teams"][0] = _team_box(12, 400, "2-10", 0, 0, 2)  # 1 defense + 1 return
    payload["boxscore"]["players"][0]["statistics"].append({
        "name": "kickReturns",
        "keys": ["kickReturns", "kickReturnYards", "yardsPerKickReturn", "longKickReturn",
                 "kickReturnTouchdowns"],
        "labels": ["NO", "YDS", "AVG", "LONG", "TD"],
        "athletes": [{"athlete": _kelce(), "stats": ["2", "153", "76.5", "98", "1"]}],
    })

    kc = _defense(payload)[12]

    assert (kc.defensive_touchdowns, kc.return_touchdowns) == (1, 1)


def test_a_defensive_score_the_drives_do_not_explain_is_rejected():
    payload = _defense_payload()
    payload["boxscore"]["teams"][0] = _team_box(12, 400, "2-10", 0, 0, 2)  # no return TD to match

    with pytest.raises(IngestionError, match="defensive touchdowns"):
        _defense(payload)


def test_a_safety_the_scoring_plays_do_not_confirm_is_rejected():
    payload = _defense_payload()
    payload["scoringPlays"] = []

    with pytest.raises(IngestionError, match="safeties"):
        _defense(payload)


def test_an_unexpected_defensive_score_size_is_rejected():
    payload = _defense_payload()
    payload["drives"]["previous"][1]["plays"][0]["homeScore"] = 17  # a 10-point "touchdown"

    with pytest.raises(IngestionError, match="Unexpected"):
        _defense(payload)


def test_a_game_without_play_data_or_a_final_score_has_no_defense_lines():
    no_plays = _defense_payload()
    del no_plays["drives"]
    no_score = _defense_payload()
    del no_score["header"]["competitions"][0]["competitors"][0]["score"]

    for payload in (no_plays, no_score):
        client = ESPNNFLClient(summary_factory=lambda _, p=payload: p)
        assert client.get_game("1")[3] is None


def _ingest_defense(db, payload):
    client = ESPNNFLClient(summary_factory=lambda _: payload)
    game, stats, kicks, defense = client.get_game("401671800")
    ingest_game(db, game, stats, kicks, defense)


def _stored_defense(db):
    query = select(Team.abbreviation, TeamGameStatsNFL).join(
        Team, TeamGameStatsNFL.team_id == Team.id
    )
    return {abbreviation: row for abbreviation, row in db.execute(query)}


def test_ingest_game_stores_team_defense_and_upserts_on_rerun(db):
    _ingest_defense(db, _defense_payload())
    stored = _stored_defense(db)
    assert stored["KC"].points_allowed == 7
    assert stored["BUF"].safeties == 1

    corrected = _defense_payload()
    corrected["boxscore"]["teams"][1] = _team_box(2, 350, "3-20", 1, 1, 0)
    _ingest_defense(db, corrected)  # a re-run updates the same rows instead of adding more
    rows = db.scalars(select(TeamGameStatsNFL)).all()
    assert len(rows) == 2
    assert _stored_defense(db)["KC"].yards_allowed == 350


def test_ingest_game_leaves_stored_defense_alone_without_play_data(db):
    _ingest_defense(db, _defense_payload())

    no_plays = _defense_payload()
    del no_plays["drives"]
    _ingest_defense(db, no_plays)

    assert _stored_defense(db)["KC"].points_allowed == 7


def _in_progress(payload: dict) -> dict:
    payload["header"]["status"] = {"type": {"state": "in"}}
    return payload


def test_a_live_game_whose_plays_do_not_add_up_yet_keeps_its_stat_lines_and_skips_the_kicks():
    # The box score says 2/3 but only two kicks are in the plays yet: fatal for a finished game
    # (see the test above), but for a game being played it must not cost the players' lines.
    payload = _in_progress(_with_plays(_kicker_payload(), [_MADE_24, _MADE_52]))

    game, stats, kicks, _ = ESPNNFLClient(summary_factory=lambda _: payload).get_game("401671800")

    assert game.status_state == "in_progress"
    assert any(stat.id == 40 for stat in stats)
    assert kicks is None


def test_a_live_game_whose_drives_do_not_explain_a_defensive_score_still_stores_the_players():
    payload = _in_progress(_defense_payload())
    payload["boxscore"]["teams"][0] = _team_box(12, 400, "2-10", 0, 0, 2)  # no return TD to match

    game, stats, _, defense = ESPNNFLClient(summary_factory=lambda _: payload).get_game("g")

    assert game.status_state == "in_progress"
    assert stats
    assert defense is None


def test_ingest_game_marks_stats_final_only_for_a_finished_game(db):
    def ingest(payload):
        game, stats, kicks, defense = ESPNNFLClient(summary_factory=lambda _: payload).get_game("g")
        ingest_game(db, game, stats, kicks, defense)
        return db.scalar(select(Game).where(Game.external_id == "401671800"))

    live = ingest(_in_progress(_kicker_payload()))
    assert (live.status, live.stats_final) == ("in_progress", False)

    final = ingest(_kicker_payload())  # the same game, once it has ended
    assert (final.status, final.stats_final) == ("final", True)
