"""Tests for the ESPN directory sync (data_pipeline/espn_directory.py).

Payload fixtures are trimmed copies of the shapes ESPN really returns. The
database tests follow test_models.py: flush inside a session that is rolled
back at teardown, against a real Postgres.
"""

from datetime import date, datetime

import httpx
import pytest
from sqlalchemy import select

from app.db.models import Game, Player, Team
from app.db.session import SessionLocal
from data_pipeline.espn import ESPNClient, ESPNError
from data_pipeline.espn_common import (
    IngestionError,
    competitor_score,
    season_label,
    team_external_id,
)
from data_pipeline.espn_directory import (
    InjuryRecord,
    RosterPlayer,
    ScheduledGame,
    TeamRecord,
    deactivate_unlisted,
    parse_bye_week,
    parse_injuries,
    parse_roster,
    parse_schedule,
    parse_teams,
    sync_games,
    sync_injuries,
    sync_roster,
    sync_sport,
    sync_teams,
)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _teams_payload() -> dict:
    return {
        "sports": [
            {
                "leagues": [
                    {
                        "teams": [
                            {
                                "team": {
                                    "id": "22",
                                    "displayName": "Arizona Cardinals",
                                    "abbreviation": "ARI",
                                    "color": "a40227",
                                    "logos": [
                                        {"href": "https://img/dark.png", "rel": ["full", "dark"]},
                                        {"href": "https://img/ari.png", "rel": ["full", "default"]},
                                    ],
                                }
                            },
                            {"team": {"id": "bad"}},
                        ]
                    }
                ]
            }
        ]
    }


def _athlete(**overrides) -> dict:
    athlete = {
        "id": "4912218",
        "fullName": "Cyrus Allen",
        "displayName": "Cyrus Allen",
        "weight": 180.0,
        "height": 71.0,
        "dateOfBirth": "2003-02-11T08:00Z",
        "college": {"name": "Cincinnati"},
        "headshot": {"href": "https://img/4912218.png"},
        "jersey": "13",
        "position": {"abbreviation": "WR"},
        "experience": {"years": 0},
        "status": {"type": "active"},
    }
    athlete.update(overrides)
    return athlete


def test_parse_teams_reads_default_logo_and_prefixes_color():
    (team,) = parse_teams(_teams_payload())  # the malformed second entry is dropped

    assert team == TeamRecord(
        id=22,
        name="Arizona Cardinals",
        abbreviation="ARI",
        logo_url="https://img/ari.png",
        primary_color="#a40227",
    )


def test_parse_teams_rejects_unexpected_payload():
    with pytest.raises(IngestionError):
        parse_teams({"nope": []})


def test_parse_roster_reads_full_athlete_bio():
    (player,) = parse_roster({"athletes": [_athlete()]})

    assert player == RosterPlayer(
        id=4912218,
        name="Cyrus Allen",
        position="WR",
        jersey_number=13,
        headshot_url="https://img/4912218.png",
        height_inches=71,
        weight_lbs=180,
        birth_date=date(2003, 2, 11),
        college="Cincinnati",
        experience_years=0,
        active=True,
    )


def test_parse_roster_flattens_grouped_nfl_rosters():
    raw = {
        "athletes": [
            {"position": "offense", "items": [_athlete(id="1")]},
            {"position": "practiceSquad", "items": [_athlete(id="2")]},
            {"position": "suspended", "items": []},
        ]
    }

    assert [p.id for p in parse_roster(raw)] == [1, 2]


def test_parse_roster_tolerates_missing_optional_fields():
    sparse = {"id": "7", "displayName": "No Jersey", "status": {"type": "active"}}

    (player,) = parse_roster({"athletes": [sparse]})

    assert player.jersey_number is None
    assert player.headshot_url is None
    assert player.position is None
    assert player.birth_date is None


def test_parse_roster_marks_non_active_statuses_inactive_and_skips_bad_entries():
    raw = {"athletes": [_athlete(id="1", status={"type": "injured-reserve"}), {"id": "x"}]}

    (player,) = parse_roster(raw)

    assert player.active is False


def _injury(status="Questionable", **overrides) -> dict:
    item = {
        "status": status,
        "date": "2026-09-24T00:20Z",
        "shortComment": "Taylor-Demerson is questionable for Sunday with a back injury.",
        "longComment": "A much longer write-up.",
        "athlete": {
            "links": [{"href": "https://www.espn.com/nfl/player/_/id/4363408/some-player"}],
            "headshot": {"href": "https://a.espncdn.com/i/headshots/nfl/players/full/999.png"},
        },
        "details": {"type": "Back"},
    }
    item.update(overrides)
    return item


def test_parse_injuries_takes_player_id_from_profile_link_and_ignores_active():
    raw = {"injuries": [{"injuries": [_injury(), _injury(status="Active")]}]}

    (injury,) = parse_injuries(raw)

    assert injury == InjuryRecord(
        player_id=4363408,
        status="Questionable",
        type="Back",
        note="Taylor-Demerson is questionable for Sunday with a back injury.",
        reported_at=datetime(2026, 9, 24, 0, 20),
    )


def test_parse_injuries_falls_back_to_headshot_for_player_id():
    item = _injury()
    item["athlete"] = {"headshot": item["athlete"]["headshot"]}

    (injury,) = parse_injuries({"injuries": [{"injuries": [item]}]})

    assert injury.player_id == 999


def test_parse_injuries_prefers_long_comment_when_short_one_is_just_the_status():
    item = _injury(shortComment="questionable", longComment="Full detail about the ankle.")

    (injury,) = parse_injuries({"injuries": [{"injuries": [item]}]})

    assert injury.note == "Full detail about the ankle."


def test_parse_injuries_drops_note_that_only_repeats_the_status():
    item = _injury(shortComment="questionable", longComment=None)

    (injury,) = parse_injuries({"injuries": [{"injuries": [item]}]})

    assert injury.note is None


def test_parse_injuries_skips_entries_without_a_player_id():
    item = _injury()
    item["athlete"] = {}

    assert parse_injuries({"injuries": [{"injuries": [item]}]}) == []


def _event(event_id="401", state="post", home_score=None, away_score=None, year=2027,
           week=None) -> dict:
    def competitor(side, team_id, score):
        entry = {"homeAway": side, "team": {"id": str(team_id)}}
        if score is not None:
            entry["score"] = {"value": float(score), "displayValue": str(score)}
        return entry

    event = {
        "id": event_id,
        "date": "2026-10-22T02:00Z",
        "season": {"year": year},
        "competitions": [
            {
                "date": "2026-10-22T02:00Z",
                "status": {"type": {"state": state}},
                "competitors": [
                    competitor("home", 1, home_score),
                    competitor("away", 2, away_score),
                ],
            }
        ],
    }
    if week is not None:
        event["week"] = {"number": week, "text": f"Week {week}"}
    return event


def test_parse_schedule_reads_scores_status_and_season_label():
    events = [_event("1", "post", 110, 104), _event("2", "pre")]

    played, upcoming = parse_schedule("NBA", {"events": events})

    assert (played.status, played.home_score, played.away_score) == ("final", 110, 104)
    assert played.season == "2026-27"
    assert played.start_time == datetime(2026, 10, 22, 2, 0)
    assert (played.home_team_id, played.away_team_id) == (1, 2)
    assert (upcoming.status, upcoming.home_score) == ("scheduled", None)


def test_parse_schedule_skips_malformed_events():
    events = [_event("1"), {"id": "broken"}, _event("2", state="weird")]

    assert [g.id for g in parse_schedule("NFL", {"events": events})] == ["1"]


def test_season_label_differs_by_sport():
    assert season_label("NBA", 2027) == "2026-27"
    assert season_label("NFL", 2026) == "2026"


def test_competitor_score_handles_summary_and_schedule_shapes():
    assert competitor_score({"score": "31"}) == 31
    assert competitor_score({"score": {"value": 31.0}}) == 31
    assert competitor_score({}) is None
    assert competitor_score({"score": ""}) is None


def test_espn_client_schedule_requests_the_regular_season_and_sends_no_browser_ua():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"events": []})

    client = ESPNClient(client=httpx.Client(transport=httpx.MockTransport(handler),
                                            base_url="https://site.api.espn.com"))
    client.schedule("basketball", "nba", "13")

    assert requests[0].url.path == "/apis/site/v2/sports/basketball/nba/teams/13/schedule"
    assert requests[0].url.params["seasontype"] == "2"

    real = ESPNClient()
    try:
        assert "mozilla" not in real._client.headers["User-Agent"].lower()
    finally:
        real.close()


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _team_record(espn_id=1, abbreviation="ATL") -> TeamRecord:
    return TeamRecord(id=espn_id, name="Atlanta Hawks", abbreviation=abbreviation,
                      logo_url="https://img/atl.png", primary_color="#c8102e")


def test_sync_teams_namespaces_external_id_by_sport(db):
    nba = sync_teams(db, "NBA", [_team_record()])
    nfl = sync_teams(db, "NFL", [_team_record(abbreviation="ATL")])  # NFL's Atlanta is id 1 too

    assert nba[1].external_id == team_external_id("NBA", 1)
    assert nfl[1].external_id == team_external_id("NFL", 1)
    assert nba[1].id != nfl[1].id


def test_sync_teams_is_idempotent_and_updates_fields(db):
    sync_teams(db, "NBA", [_team_record()])
    sync_teams(db, "NBA", [TeamRecord(id=1, name="Atlanta Hawks", abbreviation="ATL",
                                      logo_url="https://img/new.png", primary_color="#000000")])

    teams = db.scalars(select(Team).where(Team.external_id == "nba:1")).all()

    assert len(teams) == 1
    assert teams[0].logo_url == "https://img/new.png"
    assert teams[0].primary_color == "#000000"


def _roster_player(espn_id=10, **overrides) -> RosterPlayer:
    return RosterPlayer(id=espn_id, name="Sample Player", position="G", jersey_number=3,
                        headshot_url="https://img/10.png", height_inches=75, weight_lbs=200,
                        birth_date=date(2000, 1, 2), college="State", experience_years=2,
                        **overrides)


def test_sync_roster_creates_then_updates_without_duplicating(db):
    team = sync_teams(db, "NBA", [_team_record()])[1]
    players: dict[str, Player] = {}

    sync_roster(db, "NBA", team, [_roster_player()], players)
    sync_roster(db, "NBA", team, [_roster_player().model_copy(update={"jersey_number": 11})],
                players)

    rows = db.scalars(select(Player).where(Player.external_id == "10")).all()
    assert len(rows) == 1
    assert rows[0].team_id == team.id
    assert rows[0].jersey_number == 11  # a re-sync overwrites, it doesn't append
    assert rows[0].height_inches == 75
    assert rows[0].headshot_url == "https://img/10.png"


def test_sync_roster_moves_a_traded_player_to_the_new_team(db):
    teams = sync_teams(db, "NBA", [_team_record(1, "ATL"), _team_record(2, "BOS")])
    players: dict[str, Player] = {}

    sync_roster(db, "NBA", teams[1], [_roster_player()], players)
    sync_roster(db, "NBA", teams[2], [_roster_player().model_copy(update={"jersey_number": None})],
                players)

    assert players["10"].team_id == teams[2].id
    assert players["10"].jersey_number is None


def test_deactivate_unlisted_only_touches_players_missing_from_every_roster(db):
    team = sync_teams(db, "NBA", [_team_record()])[1]
    players: dict[str, Player] = {}
    sync_roster(db, "NBA", team, [_roster_player(10), _roster_player(11)], players)

    count = deactivate_unlisted(players, seen={"10"})

    assert count == 1
    assert players["10"].active is True
    assert players["11"].active is False
    assert players["11"].team_id == team.id  # team kept so old game logs still resolve


def test_sync_injuries_replaces_the_previous_report(db):
    team = sync_teams(db, "NBA", [_team_record()])[1]
    players: dict[str, Player] = {}
    sync_roster(db, "NBA", team, [_roster_player(10), _roster_player(11)], players)

    first = [InjuryRecord(player_id=10, status="Out", type="Knee", note="ACL.",
                          reported_at=datetime(2026, 9, 1))]
    assert sync_injuries(first, players) == 1
    assert players["10"].injury_status == "Out"
    assert players["10"].injury_note == "ACL."

    second = [InjuryRecord(player_id=11, status="Day-To-Day")]
    assert sync_injuries(second, players) == 1

    assert players["10"].injury_status is None  # healthy again: cleared
    assert players["10"].injury_note is None
    assert players["11"].injury_status == "Day-To-Day"


def test_sync_injuries_ignores_players_not_in_the_database():
    assert sync_injuries([InjuryRecord(player_id=999, status="Out")], {}) == 0


def _scheduled(game_id="401", home=1, away=2, status="scheduled", **kwargs) -> ScheduledGame:
    return ScheduledGame(id=game_id, season="2026-27", start_time=datetime(2026, 10, 22, 2),
                         status=status, home_team_id=home, away_team_id=away, **kwargs)


def test_sync_games_upserts_scores_as_a_game_is_played(db):
    teams = sync_teams(db, "NBA", [_team_record(1, "ATL"), _team_record(2, "BOS")])
    games: dict[str, Game] = {}

    sync_games(db, "NBA", [_scheduled()], teams, games)
    assert games["401"].status == "scheduled" and games["401"].home_score is None

    sync_games(db, "NBA", [_scheduled(status="final", home_score=101, away_score=99)],
               teams, games)

    rows = db.scalars(select(Game).where(Game.external_id == "401")).all()
    assert len(rows) == 1
    assert (rows[0].status, rows[0].home_score, rows[0].away_score) == ("final", 101, 99)
    assert rows[0].home_team_id == teams[1].id


def test_sync_games_skips_games_involving_unknown_teams(db):
    teams = sync_teams(db, "NBA", [_team_record(1, "ATL")])

    assert sync_games(db, "NBA", [_scheduled(away=99)], teams, {}) == 0


def test_parse_schedule_reads_the_nfl_week_and_leaves_it_empty_for_the_nba():
    nfl, nba = (
        parse_schedule("NFL", {"events": [_event(week=3, year=2026)]})[0],
        parse_schedule("NBA", {"events": [_event()]})[0],
    )

    assert nfl.week == 3
    assert nba.week is None


def _schedule_without(*byes: int):
    weeks = [w for w in range(1, 19) if w not in byes]
    return parse_schedule(
        "NFL", {"events": [_event(f"4{w:02d}", "pre", week=w, year=2026) for w in weeks]}
    )


def test_parse_bye_week_is_the_one_week_with_no_game():
    assert parse_bye_week(_schedule_without(11)) == 11


def test_parse_bye_week_is_unknown_when_the_schedule_is_not_a_full_season_with_one_bye():
    assert parse_bye_week(_schedule_without()) is None  # every week has a game
    assert parse_bye_week(_schedule_without(6, 11)) is None  # a game missing from the payload
    assert parse_bye_week([]) is None
    assert parse_bye_week(parse_schedule("NBA", {"events": [_event()]})) is None  # no NBA bye


def test_sync_games_stores_the_week(db):
    teams = sync_teams(db, "NFL", [_team_record(1, "ATL"), _team_record(2, "BOS")])
    games: dict[str, Game] = {}

    sync_games(db, "NFL", [_scheduled(week=7)], teams, games)

    assert games["401"].week == 7


class _FakeESPN:
    """Just enough of ESPNClient for sync_sport, serving canned payloads."""

    def __init__(self, fail_roster_for: str | None = None):
        self.fail_roster_for = fail_roster_for

    def teams(self, sport, league):
        return {"sports": [{"leagues": [{"teams": [
            {"team": {"id": "1", "displayName": "Team One", "abbreviation": "ONE"}},
            {"team": {"id": "2", "displayName": "Team Two", "abbreviation": "TWO"}},
        ]}]}]}

    def roster(self, sport, league, team_id):
        if team_id == self.fail_roster_for:
            raise ESPNError("boom")
        return {"athletes": [_athlete(id=team_id)]}

    def schedule(self, sport, league, team_id, season_type=2):
        # Team One's bye is week 5 and Team Two's week 6; the payload's own byeWeek is wrong
        weeks = [w for w in range(1, 19) if w != 4 + int(team_id)]
        return {"byeWeek": 1, "events": [
            _event(f"9{team_id}{w:02d}", "pre", week=w, year=2026) for w in weeks
        ]}

    def injuries(self, sport, league):
        return {"injuries": []}


def test_sync_sport_derives_each_teams_bye_week_from_its_games_not_the_payloads_field(db):
    report = sync_sport(db, _FakeESPN(), "NFL")

    byes = {t.abbreviation: t.bye_week for t in db.scalars(select(Team).where(Team.sport == "NFL"))}
    assert byes == {"ONE": 5, "TWO": 6}
    assert (report.teams, report.players, report.failures) == (2, 2, [])


def test_sync_sport_reports_a_failed_roster_and_deactivates_nobody(db):
    stale = Player(external_id="777", name="Long Gone", sport="NFL", active=True)
    db.add(stale)
    db.flush()

    report = sync_sport(db, _FakeESPN(fail_roster_for="2"), "NFL")

    assert report.failures == ["TWO roster"]
    assert report.deactivated == 0
    assert stale.active is True


def test_sync_sport_deactivates_players_missing_from_every_roster_when_all_load(db):
    stale = Player(external_id="777", name="Long Gone", sport="NFL", active=True)
    db.add(stale)
    db.flush()

    report = sync_sport(db, _FakeESPN(), "NFL")

    assert report.deactivated == 1
    assert stale.active is False


class _InjuryFeed:
    def __init__(self, payload):
        self.payload = payload
        self.asked = []

    def injuries(self, sport, league):
        self.asked.append((sport, league))
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def test_refresh_injuries_applies_the_report_with_one_request(db):
    from data_pipeline.espn_directory import refresh_injuries

    team = Team(name="T", abbreviation="TTT", sport="NFL")
    db.add(team)
    db.flush()
    hurt = Player(external_id="9001", name="Hurt", sport="NFL", team_id=team.id)
    healed = Player(
        external_id="9002", name="Healed", sport="NFL", team_id=team.id, injury_status="Out"
    )
    db.add_all([hurt, healed])
    db.flush()
    athlete = {"links": [{"href": "https://www.espn.com/nfl/player/_/id/9001/hurt"}]}
    feed = _InjuryFeed({"injuries": [{"injuries": [_injury(athlete=athlete)]}]})

    assert refresh_injuries(db, feed, "NFL") == 1

    assert feed.asked == [("football", "nfl")]
    assert (hurt.injury_status, healed.injury_status) == ("Questionable", None)


def test_refresh_injuries_leaves_the_stored_report_alone_when_the_feed_fails(db):
    from data_pipeline.espn_directory import refresh_injuries

    team = Team(name="T", abbreviation="TTT", sport="NFL")
    db.add(team)
    db.flush()
    hurt = Player(
        external_id="9001", name="Hurt", sport="NFL", team_id=team.id, injury_status="Out"
    )
    db.add(hurt)
    db.flush()

    with pytest.raises(ESPNError):
        refresh_injuries(db, _InjuryFeed(ESPNError("down")), "NFL")

    assert hurt.injury_status == "Out"
