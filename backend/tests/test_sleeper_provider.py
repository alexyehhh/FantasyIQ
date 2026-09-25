"""The Sleeper source, against canned Sleeper responses (no network, no database)."""

from datetime import datetime

import httpx
import pytest

from app.db.models import Game, Player, Team
from app.db.session import SessionLocal
from app.services.projections.base import (
    PROVIDERS,
    ProjectionError,
    StatProjection,
    Target,
    Unavailable,
)
from app.services.projections.expected_scoring import score_expected_player
from app.services.projections.sleeper import SleeperProvider
from app.services.scoring import ScoringConfig, default_config

NFL = default_config("NFL")
NBA = default_config("NBA")


def _row(first, last, position, team, opponent, stats, **extra):
    return {
        "player": {"first_name": first, "last_name": last, "position": position},
        "team": team,
        "opponent": opponent,
        "stats": stats,
        **extra,
    }


def _nfl_rows():
    return [
        _row(
            "Marvin",
            "Harrison",
            "WR",
            "ARI",
            "WAS",
            {
                "rec": 5.0,
                "rec_tgt": 8.0,
                "rec_yd": 70.0,
                "rec_td": 0.5,
                "pts_ppr": 15.0,
                "pr_td": 0.0,
                "adp_dd_ppr": 40.0,
            },
        ),
        _row(
            "Patrick",
            "Mahomes",
            "QB",
            "KC",
            "MIA",
            {
                "pass_att": 30.0,
                "pass_cmp": 20.0,
                "pass_yd": 250.0,
                "pass_td": 2.0,
                "pass_int": 0.5,
                "rush_yd": 20.0,
                "pts_ppr": 21.0,
            },
        ),
        _row(
            "Harrison",
            "Butker",
            "K",
            "KC",
            "MIA",
            {
                "fga": 2.0,
                "fgm": 1.8,
                "fgm_30_39": 0.6,
                "fgm_40_49": 0.8,
                "fgm_50p": 0.4,
                "fgmiss_40_49": 0.2,
                "xpm": 2.5,
                "xpa": 2.6,
                "pts_ppr": 9.0,
            },
        ),
        _row(
            "Kansas City",
            "Chiefs",
            "DEF",
            "KC",
            "MIA",
            {
                "sack": 3.0,
                "int": 0.8,
                "fum_rec": 0.6,
                "def_td": 0.2,
                "def_kr_td": 0.03,
                "def_pr_td": 0.04,
                "pts_allow": 17.5,
                "yds_allow": 320.0,
                "pts_ppr": 9.0,
            },
        ),
        # Sleeper lists many players with only a draft ranking: no projection
        _row("Nobody", "Special", "WR", "KC", "MIA", {"adp_dd_ppr": 900.0}),
    ]


def _nba_rows():
    return [
        _row(
            "Shai",
            "Gilgeous-Alexander",
            "PG",
            "OKC",
            "SAS",
            {
                "pts": 30.0,
                "reb": 5.0,
                "ast": 6.0,
                "stl": 1.5,
                "blk": 0.8,
                "to": 2.5,
                "fgm": 10.0,
                "fga": 20.0,
                "tpm": 1.5,
                "tpa": 4.0,
                "ftm": 8.0,
                "fta": 9.0,
                "sp": 1980.0,
            },
            date="2026-10-20",
        ),
        _row(
            "Shai",
            "Gilgeous-Alexander",
            "PG",
            "OKC",
            "DEN",
            {"pts": 28.0, "sp": 1900.0},
            date="2026-10-22",
        ),
    ]


class FakeSleeper:
    """A transport answering like Sleeper and counting the requests it gets."""

    def __init__(self, nfl=None, nba=None, fail=False):
        self.requests: list[httpx.Request] = []
        self.nfl, self.nba, self.fail = nfl, nba, fail

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail:
            return httpx.Response(503)
        path = request.url.path
        if path.endswith("/state/nba"):
            return httpx.Response(200, json={"season_start_date": "2026-10-20"})
        if "/projections/nfl/" in path:
            return httpx.Response(200, json=self.nfl if self.nfl is not None else _nfl_rows())
        if "/projections/nba/" in path:
            return httpx.Response(200, json=self.nba if self.nba is not None else _nba_rows())
        return httpx.Response(404)


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def _provider(fake, clock=None):
    client = httpx.Client(transport=httpx.MockTransport(fake))
    return SleeperProvider(client, clock=clock or Clock(), ttl_seconds=600)


def _target(kind, name, position, team, opponent, sport="NFL", start=None, week=3):
    game = Game(
        sport=sport,
        season="2026" if sport == "NFL" else "2026-27",
        start_time=start or datetime(2026, 9, 27, 17, 0),
        week=week if sport == "NFL" else None,
    )
    return Target(
        kind=kind,
        sport=sport,
        entity_id=hash((name, opponent)) % 1000,
        name=name,
        team=Team(abbreviation=team, sport=sport),
        position=position,
        game=game,
        opponent=Team(abbreviation=opponent, sport=sport),
        is_home=True,
        player=None,
    )


def _one(provider, target, config=NFL):
    answer = provider.project(None, [target], config)[target.key]
    return answer


def test_a_players_row_is_matched_by_name_team_and_opponent_despite_naming_differences():
    # ESPN says "Marvin Harrison Jr." and Washington "WSH"; Sleeper says "Marvin Harrison", "WAS"
    target = _target("player", "Marvin Harrison Jr.", "WR", "ARI", "WSH")

    answer = _one(_provider(FakeSleeper()), target)

    assert isinstance(answer, StatProjection)
    assert answer.stats["receptions"] == 5
    assert answer.stats["receiving_targets"] == 8
    assert answer.stats["receiving_yards"] == 70
    assert answer.stats["receiving_touchdowns"] == 0.5
    assert "Sleeper" in answer.notes[0]


def test_sleepers_own_fantasy_points_are_not_used_the_stats_are_rescored_by_our_config():
    provider = _provider(FakeSleeper())
    target = _target("player", "Marvin Harrison Jr.", "WR", "ARI", "WSH")

    answer = _one(provider, target)
    standard = ScoringConfig(
        name="Standard",
        sport="NFL",
        player_weights={"receiving_yards": 0.1, "receiving_touchdowns": 6},
    )
    ppr = score_expected_player(NFL, answer.stats).points
    no_ppr = score_expected_player(standard, answer.stats).points

    assert ppr == pytest.approx(5 * 1 + 7 + 3)  # not Sleeper's pts_ppr of 15
    assert no_ppr == pytest.approx(7 + 3)


def test_kick_return_touchdowns_are_not_reported_even_though_sleeper_does_not_project_them():
    config = ScoringConfig(
        name="Return game",
        sport="NFL",
        player_weights={"receptions": 1, "kick_return_touchdowns": 6, "fumbles_lost": -2},
    )
    target = _target("player", "Marvin Harrison Jr.", "WR", "ARI", "WSH")

    answer = _one(_provider(FakeSleeper()), target, config)

    assert answer.unprojected == []  # they almost never happen: counted as zero, quietly
    assert "kick_return_touchdowns" not in answer.stats


def test_a_player_sleeper_gives_no_projection_is_unavailable():
    target = _target("player", "Nobody Special", "WR", "KC", "MIA")

    answer = _one(_provider(FakeSleeper()), target)

    assert isinstance(answer, Unavailable) and "no projection" in answer.reason


def test_a_row_for_a_different_opponent_is_rejected_not_used():
    target = _target("player", "Patrick Mahomes", "QB", "KC", "DEN")  # Sleeper has him vs MIA

    answer = _one(_provider(FakeSleeper()), target)

    assert isinstance(answer, Unavailable) and "different game" in answer.reason


@pytest.mark.parametrize("position", ["K", "PK"])  # our data calls kickers PK
def test_a_kickers_distance_ranges_come_through_as_expected_kicks(position):
    target = _target("player", "Harrison Butker", position, "KC", "MIA")

    answer = _one(_provider(FakeSleeper()), target)

    made = {(b.low, b.high): (b.made, b.missed) for b in answer.kicks}
    assert made == {(30, 39): (0.6, 0.0), (40, 49): (0.8, 0.2), (50, 65): (0.4, 0.0)}


def test_a_defense_is_matched_by_team_and_its_return_touchdowns_are_summed():
    target = _target("defense", "Kansas City Chiefs D/ST", "DEF", "KC", "MIA")

    answer = _one(_provider(FakeSleeper()), target)

    assert answer.stats["sacks"] == 3 and answer.stats["points_allowed"] == 17.5
    assert answer.stats["return_touchdowns"] == pytest.approx(0.07)
    assert answer.stats["defensive_touchdowns"] == 0.2
    assert (
        "fourth_down_stops" in answer.unprojected
    )  # the default league scores them; Sleeper doesn't


def test_nba_rows_are_matched_by_date_and_minutes_are_converted_from_seconds():
    # 01:30 UTC on Oct 21 is the evening of Oct 20 in the US
    target = _target(
        "player",
        "Shai Gilgeous-Alexander",
        "G",
        "OKC",
        "SA",
        sport="NBA",
        start=datetime(2026, 10, 21, 1, 30),
    )

    answer = _one(_provider(FakeSleeper()), target, NBA)

    assert answer.stats["points"] == 30 and answer.stats["minutes"] == 33
    assert answer.stats["three_pointers_made"] == 1.5
    assert answer.unprojected == []


def test_nba_picks_the_game_against_the_scheduled_opponent_when_a_week_has_several():
    target = _target(
        "player",
        "Shai Gilgeous-Alexander",
        "G",
        "OKC",
        "DEN",
        sport="NBA",
        start=datetime(2026, 10, 22, 23, 0),
    )

    answer = _one(_provider(FakeSleeper()), target, NBA)

    assert answer.stats["points"] == 28


def test_nba_weeks_run_monday_to_sunday_from_the_week_the_season_starts_in():
    fake = FakeSleeper()
    provider = _provider(fake)
    week_two = _target(
        "player",
        "Shai Gilgeous-Alexander",
        "G",
        "OKC",
        "SA",
        sport="NBA",
        start=datetime(2026, 10, 27, 1, 0),  # Monday 26th in the US: week 2
    )
    before_season = _target(
        "player",
        "Shai Gilgeous-Alexander",
        "G",
        "OKC",
        "SA",
        sport="NBA",
        start=datetime(2026, 10, 10, 23, 0),
    )

    provider.project(None, [week_two], NBA)
    answer = _one(provider, before_season, NBA)

    assert any(r.url.path.endswith("/projections/nba/2026/2") for r in fake.requests)
    assert isinstance(answer, Unavailable) and "yet" in answer.reason


def test_a_weeks_file_is_fetched_once_and_reused_until_it_expires():
    fake, clock = FakeSleeper(), Clock()
    provider = _provider(fake, clock)
    harrison = _target("player", "Marvin Harrison Jr.", "WR", "ARI", "WSH")
    mahomes = _target("player", "Patrick Mahomes", "QB", "KC", "MIA")

    provider.project(None, [harrison, mahomes], NFL)
    provider.project(None, [harrison], NFL)
    assert len(fake.requests) == 1

    clock.now = 601
    provider.project(None, [harrison], NFL)
    assert len(fake.requests) == 2


def test_the_request_asks_for_regular_season_fantasy_positions():
    fake = FakeSleeper()

    _one(_provider(fake), _target("player", "Marvin Harrison Jr.", "WR", "ARI", "WSH"))

    query = fake.requests[0].url.params
    assert query["season_type"] == "regular"
    assert set(query.get_list("position[]")) >= {"QB", "RB", "WR", "TE", "K", "DEF"}
    assert fake.requests[0].url.path.endswith("/projections/nfl/2026/3")


def test_sleeper_being_down_is_a_projection_error_not_wrong_numbers():
    target = _target("player", "Marvin Harrison Jr.", "WR", "ARI", "WSH")

    with pytest.raises(ProjectionError, match="Sleeper"):
        _one(_provider(FakeSleeper(fail=True)), target)


def test_an_unexpected_shape_is_a_projection_error():
    target = _target("player", "Marvin Harrison Jr.", "WR", "ARI", "WSH")

    with pytest.raises(ProjectionError, match="unexpected shape"):
        _one(_provider(FakeSleeper(nfl={"message": "moved"})), target)  # type: ignore[arg-type]


def test_it_is_registered_as_a_source():
    assert PROVIDERS["sleeper"].name == "sleeper"


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _our_league(db, sport="NFL"):
    kc = Team(name="Kansas City Chiefs", abbreviation="KC", sport=sport)
    ari = Team(name="Arizona Cardinals", abbreviation="ARI", sport=sport)
    db.add_all([kc, ari])
    db.flush()
    players = {}
    for name, position, team in (
        ("Patrick Mahomes", "QB", kc),
        ("Harrison Butker", "PK", kc),
        ("Marvin Harrison Jr.", "WR", ari),
        ("Nobody Special", "WR", kc),
    ):
        player = Player(name=name, sport=sport, team_id=team.id, position=position)
        db.add(player)
        players[name] = player
    db.flush()
    return kc, ari, players


def _rank(provider, db, **kwargs):
    kwargs.setdefault("sport", "NFL")
    kwargs.setdefault("season", "2026")
    kwargs.setdefault("week", 3)
    kwargs.setdefault("day", None)
    kwargs.setdefault("positions", None)
    kwargs.setdefault("defenses", False)
    kwargs.setdefault("config", NFL)
    return provider.rank(db, **kwargs)


def test_ranking_lists_everyone_sleeper_projects_that_we_have_best_first(db):
    _, _, players = _our_league(db)

    ranked = _rank(_provider(FakeSleeper()), db)

    # best projected line first; "Nobody Special" has no projection so isn't ranked
    assert [c.entity_id for c in ranked] == [
        players["Patrick Mahomes"].id,
        players["Marvin Harrison Jr."].id,
        players["Harrison Butker"].id,
    ]
    assert ranked == sorted(ranked, key=lambda c: -c.points)
    assert all(c.kind == "player" for c in ranked)


def test_ranking_scores_the_projected_stats_with_our_scoring_not_sleepers_points(db):
    _, _, players = _our_league(db)
    standard = ScoringConfig(name="Standard", sport="NFL", player_weights={"receiving_yards": 0.1})

    ranked = _rank(_provider(FakeSleeper()), db, config=standard, positions=["WR"])

    assert [(c.entity_id, c.points) for c in ranked] == [(players["Marvin Harrison Jr."].id, 7.0)]


def test_ranking_keeps_only_the_slots_positions(db):
    _, _, players = _our_league(db)

    kickers = _rank(_provider(FakeSleeper()), db, positions=["PK"])

    assert [c.entity_id for c in kickers] == [players["Harrison Butker"].id]


def test_ranking_defenses_matches_teams_by_abbreviation(db):
    kc, *_ = _our_league(db)

    ranked = _rank(_provider(FakeSleeper()), db, defenses=True)

    assert [(c.kind, c.entity_id) for c in ranked] == [("defense", kc.id)]


def test_ranking_carries_each_players_injury_status_and_skips_inactive_ones(db):
    _, _, players = _our_league(db)
    players["Patrick Mahomes"].injury_status = "Questionable"
    players["Harrison Butker"].active = False
    db.flush()

    ranked = _rank(_provider(FakeSleeper()), db)

    assert {c.entity_id: c.injury_status for c in ranked}[
        players["Patrick Mahomes"].id
    ] == "Questionable"
    assert players["Harrison Butker"].id not in [c.entity_id for c in ranked]


def test_nba_ranking_covers_the_players_with_a_game_that_day(db):
    from datetime import date

    _, _, players = _our_league(db, sport="NBA")
    okc = Team(name="Oklahoma City Thunder", abbreviation="OKC", sport="NBA")
    db.add(okc)
    db.flush()
    shai = Player(name="Shai Gilgeous-Alexander", sport="NBA", team_id=okc.id, position="G")
    db.add(shai)
    db.flush()
    provider = _provider(FakeSleeper())

    that_day = _rank(
        provider, db, sport="NBA", season="2026-27", week=None, day=date(2026, 10, 20), config=NBA
    )
    other_day = _rank(
        provider, db, sport="NBA", season="2026-27", week=None, day=date(2026, 10, 22), config=NBA
    )
    before_season = _rank(
        provider, db, sport="NBA", season="2026-27", week=None, day=date(2026, 10, 1), config=NBA
    )

    assert [c.entity_id for c in that_day] == [shai.id]
    assert [c.entity_id for c in other_day] == [shai.id]  # his second game, on the 22nd
    assert before_season == [] and players
