"""Integration tests for season totals and ranks (real Postgres, rolled back after each test)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import (
    Game,
    Player,
    PlayerGameStats,
    PlayerGameStatsNFL,
    Team,
    TeamGameStatsNFL,
)
from app.db.session import SessionLocal
from app.services import season_summary as summaries
from app.services.scoring import ScoringConfig

_START = datetime(2026, 9, 10, 20, 0, tzinfo=timezone.utc)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _team(db, sport="NFL", name="Team", abbreviation="TST"):
    team = Team(name=name, abbreviation=abbreviation, sport=sport)
    db.add(team)
    db.flush()
    return team


def _games(db, team, sport="NFL", season="2026", count=2):
    games = []
    for week in range(1, count + 1):
        game = Game(
            sport=sport,
            season=season,
            home_team_id=team.id,
            away_team_id=team.id,
            start_time=_START + timedelta(days=7 * week),
            week=week,
            status="final",
        )
        db.add(game)
        games.append(game)
    db.flush()
    return games


def _player(db, team, name, position, sport="NFL"):
    player = Player(name=name, sport=sport, team_id=team.id, position=position)
    db.add(player)
    db.flush()
    return player


def _nfl(db, player, game, **stats):
    db.add(PlayerGameStatsNFL(player_id=player.id, game_id=game.id, **stats))
    db.flush()


@pytest.fixture
def quarterbacks(db):
    """Three QBs (and a WR who must not count) over two 2026 games, plus a 2025 game."""
    team = _team(db)
    g1, g2 = _games(db, team)
    (old,) = _games(db, team, season="2025", count=1)
    qb1 = _player(db, team, "QB One", "QB")
    qb2 = _player(db, team, "QB Two", "QB")
    qb3 = _player(db, team, "QB Three", "QB")
    wr = _player(db, team, "The WR", "WR")
    _nfl(db, qb1, g1, passing_yards=300, interceptions=1)
    _nfl(db, qb1, g2, passing_yards=250)
    _nfl(db, qb2, g1, passing_yards=400, interceptions=3)
    _nfl(db, qb3, g1, passing_yards=550)
    _nfl(db, wr, g1, receiving_yards=900, passing_yards=999)
    _nfl(db, qb2, old, passing_yards=5000)  # last season: must not count
    return qb1, qb2, qb3, wr


def test_totals_are_summed_over_the_latest_season_and_ranked_among_the_position(db, quarterbacks):
    qb1, qb2, qb3, _ = quarterbacks

    one = summaries.get_player_season_summary(db, qb1)
    two = summaries.get_player_season_summary(db, qb2)

    assert (one.season, one.games, one.position_group, one.pool_size) == ("2026", 2, "QB", 3)
    assert one.stats["passing_yards"].total == 550
    # QB One and QB Three tie on 550; QB Two (400) has two players ahead of him.
    assert (one.stats["passing_yards"].rank, one.stats["passing_yards"].tied) == (1, True)
    assert (two.stats["passing_yards"].rank, two.stats["passing_yards"].tied) == (3, False)
    assert two.stats["passing_yards"].total == 400  # not 5,400: last season is left out
    assert two.games == 1


def test_stats_where_fewer_is_better_rank_the_lowest_first(db, quarterbacks):
    qb1, qb2, qb3, _ = quarterbacks

    ranks = {
        qb.name: summaries.get_player_season_summary(db, qb).stats["interceptions"].rank
        for qb in (qb1, qb2, qb3)
    }

    assert ranks == {"QB One": 2, "QB Two": 3, "QB Three": 1}  # 1, 3 and 0 thrown


def test_fantasy_points_are_ranked_under_the_default_scoring(db, quarterbacks):
    qb1, qb2, qb3, _ = quarterbacks

    points = {
        qb.name: summaries.get_player_season_summary(db, qb).stats["fantasy_points"]
        for qb in (qb1, qb2, qb3)
    }

    # 550 yards at 0.04 is 22, less 2 for an interception; 400 yards less 3 interceptions.
    assert [(name, p.total, p.rank) for name, p in points.items()] == [
        ("QB One", 20, 2),
        ("QB Two", 10, 3),
        ("QB Three", 22, 1),
    ]


def test_fantasy_points_are_ranked_under_a_custom_config(db, quarterbacks):
    qb1, qb2, qb3, _ = quarterbacks
    yards_only = ScoringConfig(name="Yards", sport="NFL", player_weights={"passing_yards": 0.1})

    one = summaries.get_player_season_summary(db, qb1, scoring=yards_only)
    two = summaries.get_player_season_summary(db, qb2, scoring=yards_only)

    assert (one.stats["fantasy_points"].total, one.stats["fantasy_points"].tied) == (55, True)
    assert (two.stats["fantasy_points"].total, two.stats["fantasy_points"].rank) == (40, 3)


def test_only_players_at_the_same_position_are_in_the_pool(db, quarterbacks):
    *_, wr = quarterbacks

    summary = summaries.get_player_season_summary(db, wr)

    assert (summary.position_group, summary.pool_size, summary.stats["receiving_yards"].rank) == (
        "WR", 1, 1,
    )


def test_running_backs_and_fullbacks_share_a_group_as_do_the_nbas_guards(db):
    team = _team(db)
    g1, _ = _games(db, team)
    rb = _player(db, team, "Back", "RB")
    fb = _player(db, team, "Fullback", "FB")
    _nfl(db, rb, g1, rushing_yards=100)
    _nfl(db, fb, g1, rushing_yards=20)

    nba = _team(db, sport="NBA", name="Hoops", abbreviation="HPS")
    n1, _ = _games(db, nba, sport="NBA", season="2025-26")
    codes = ["G", "PG", "SG"]
    guards = [_player(db, nba, f"G{i}", code, sport="NBA") for i, code in enumerate(codes)]
    for index, guard in enumerate(guards):
        points = 10 * (index + 1)
        db.add(PlayerGameStats(player_id=guard.id, game_id=n1.id, minutes=30, points=points))
    db.flush()

    fullback = summaries.get_player_season_summary(db, fb)
    assert (fullback.position_group, fullback.pool_size, fullback.stats["rushing_yards"].rank) == (
        "RB", 2, 2,
    )
    first_guard = summaries.get_player_season_summary(db, guards[0])
    assert (first_guard.position_group, first_guard.pool_size) == ("G", 3)
    assert first_guard.stats["points"].rank == 3


def test_an_nba_player_who_never_got_on_the_floor_is_not_ranked(db):
    team = _team(db, sport="NBA", name="Hoops", abbreviation="HPS")
    game, _ = _games(db, team, sport="NBA", season="2025-26")
    starter = _player(db, team, "Starter", "G", sport="NBA")
    bench = _player(db, team, "Bench", "G", sport="NBA")
    db.add(PlayerGameStats(player_id=starter.id, game_id=game.id, minutes=30, points=12))
    db.add(PlayerGameStats(player_id=bench.id, game_id=game.id, minutes=0))  # a DNP row
    db.flush()

    assert summaries.get_player_season_summary(db, bench) is None
    assert summaries.get_player_season_summary(db, starter).pool_size == 1


def test_no_summary_for_a_player_without_a_position_or_without_stats(db, quarterbacks):
    team = _team(db, abbreviation="OTH")
    nameless = _player(db, team, "No Position", None)
    unused = _player(db, team, "Never Played", "QB")

    assert summaries.get_player_season_summary(db, nameless) is None
    assert summaries.get_player_season_summary(db, unused) is None


def test_no_summary_at_all_before_any_stats_exist(db):
    team = _team(db)
    qb = _player(db, team, "Lonely", "QB")

    assert summaries.get_player_season_summary(db, qb) is None


def _defense_lines(db):
    a = _team(db, name="Alpha", abbreviation="ALP")
    b = _team(db, name="Bravo", abbreviation="BRV")
    c = _team(db, name="Charlie", abbreviation="CHA")
    g1, g2 = _games(db, a)
    lines = [
        (a, g1, {"sacks": 3, "interceptions": 1, "points_allowed": 7, "yards_allowed": 300}),
        (a, g2, {"sacks": 5, "points_allowed": 0, "yards_allowed": 200}),
        (b, g1, {"sacks": 8, "points_allowed": 31, "yards_allowed": 450}),
        (c, g1, {"sacks": 3, "points_allowed": 7, "yards_allowed": 300}),
    ]
    db.add_all(TeamGameStatsNFL(team_id=t.id, game_id=g.id, **stats) for t, g, stats in lines)
    db.flush()
    return a, b, c


def test_a_defense_is_ranked_among_the_defenses_with_fewer_points_allowed_better(db):
    alpha, bravo, charlie = _defense_lines(db)

    a = summaries.get_defense_season_summary(db, alpha)
    b = summaries.get_defense_season_summary(db, bravo)

    assert (a.position_group, a.pool_size, a.games, a.season) == ("DEF", 3, 2, "2026")
    assert a.stats["sacks"].total == 8
    assert (a.stats["sacks"].rank, a.stats["sacks"].tied) == (1, True)  # ties Bravo on 8
    assert (a.stats["points_allowed"].total, a.stats["points_allowed"].rank) == (7, 1)
    assert b.stats["points_allowed"].rank == 3  # allowed the most
    # Yards allowed: Charlie 300, Bravo 450, Alpha 500 (300 + 200), fewest first.
    assert (b.stats["yards_allowed"].total, b.stats["yards_allowed"].rank) == (450, 2)
    assert a.stats["yards_allowed"].rank == 3


def test_defense_fantasy_points_are_ranked_and_a_team_without_stats_has_no_summary(db):
    alpha, bravo, charlie = _defense_lines(db)
    idle = _team(db, name="Idle", abbreviation="IDL")

    a = summaries.get_defense_season_summary(db, alpha)

    # Alpha: game 1 = 3 sacks + 2 + 4 (7 allowed) = 9; game 2 = 5 sacks + 10 (shutout) = 15.
    assert (a.stats["fantasy_points"].total, a.stats["fantasy_points"].rank) == (24, 1)
    assert summaries.get_defense_season_summary(db, bravo).stats["fantasy_points"].total == 7
    assert summaries.get_defense_season_summary(db, idle) is None


def test_no_defense_summary_before_any_defense_stats_exist(db):
    assert summaries.get_defense_season_summary(db, _team(db)) is None
