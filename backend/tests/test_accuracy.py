"""Scoring sources' saved projections against real results (real Postgres, rolled back after)."""

from datetime import datetime, timedelta

import pytest

from app.db.models import Game, Player, PlayerGameStatsNFL, ProjectionSnapshot, Team
from app.db.session import SessionLocal
from app.services import accuracy
from app.services.scoring import default_config

NFL = default_config("NFL")
KICKOFF = datetime(2026, 10, 4, 17, 0)
# Under the default PPR scoring: one point per reception, a tenth per receiving yard.
ACTUAL = {"receptions": 6, "receiving_yards": 50}  # 11.0 points


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def league(db):
    alpha = Team(name="Alpha Aces", abbreviation="ALP", sport="NFL")
    bravo = Team(name="Bravo Bears", abbreviation="BRV", sport="NFL")
    db.add_all([alpha, bravo])
    db.flush()
    return alpha, bravo


def _game(db, league, week=4, status="final", kickoff=KICKOFF, stats_final=True):
    alpha, bravo = league
    game = Game(
        sport="NFL", season="2026", home_team_id=alpha.id, away_team_id=bravo.id,
        start_time=kickoff, week=week, status=status, stats_final=stats_final,
    )  # fmt: skip
    db.add(game)
    db.flush()
    return game


def _player(db, league, name, position="WR"):
    player = Player(name=name, sport="NFL", team_id=league[0].id, position=position, active=True)
    db.add(player)
    db.flush()
    return player


def _played(db, player, game, **stats):
    db.add(PlayerGameStatsNFL(player_id=player.id, game_id=game.id, **(stats or ACTUAL)))
    db.flush()


def _project(db, source, player, game, stats, *, before=timedelta(hours=3), origin="live"):
    db.add(
        ProjectionSnapshot(
            source=source, sport="NFL", kind="player", entity_id=player.id, game_id=game.id,
            origin=origin, captured_at=game.start_time - before, stats=stats,
        )
    )  # fmt: skip
    db.flush()


def _run(db, **kwargs):
    return accuracy.compute(db, sport="NFL", config=NFL, **kwargs)


def test_scores_each_source_against_the_real_result_in_fantasy_points(db, league):
    game = _game(db, league)
    wes, tom = _player(db, league, "Wes Receiver"), _player(db, league, "Tom Tight", "TE")
    _played(db, wes, game)
    _played(db, tom, game)
    # Source a: exact for Wes (11.0), 5 points high for Tom (16.0). Source b: 2 high, 1 low.
    _project(db, "a", wes, game, {"receptions": 6, "receiving_yards": 50})
    _project(db, "a", tom, game, {"receptions": 10, "receiving_yards": 60})
    _project(db, "b", wes, game, {"receptions": 8, "receiving_yards": 50})
    _project(db, "b", tom, game, {"receptions": 5, "receiving_yards": 50})

    report = _run(db)

    a, b = report.overall["a"], report.overall["b"]
    assert (report.compared, a.n, b.n) == (2, 2, 2)
    assert a.mae == pytest.approx(2.5) and a.bias == pytest.approx(2.5)  # (0 + 5) / 2
    assert b.mae == pytest.approx(1.5) and b.bias == pytest.approx(0.5)  # (2 - 1) / 2... abs 2, 1
    assert a.rmse == pytest.approx((25 / 2) ** 0.5)
    assert a.mean_actual == 11.0 and report.scoring == NFL.name


def test_sources_are_compared_only_on_the_player_games_both_projected(db, league):
    game = _game(db, league)
    wes, tom = _player(db, league, "Wes Receiver"), _player(db, league, "Tom Tight", "TE")
    _played(db, wes, game)
    _played(db, tom, game)
    _project(db, "a", wes, game, ACTUAL)
    _project(db, "a", tom, game, {"receptions": 20})  # a wild miss, but b never projected Tom
    _project(db, "b", wes, game, {"receptions": 7, "receiving_yards": 50})

    report = _run(db)

    assert report.compared == 1
    assert report.overall["a"].mae == 0  # Tom's bad miss isn't held against a
    assert report.coverage["a"].projected == 2 and report.coverage["a"].compared == 1
    assert report.coverage["b"].projected == 1 and report.coverage["b"].compared == 1


def test_a_source_is_judged_on_its_last_projection_before_kickoff_only(db, league):
    game = _game(db, league)
    wes = _player(db, league, "Wes Receiver")
    _played(db, wes, game)
    _project(db, "a", wes, game, {"receptions": 2}, before=timedelta(days=2))
    _project(
        db, "a", wes, game, {"receptions": 6, "receiving_yards": 50}, before=timedelta(hours=2)
    )
    _project(
        db, "a", wes, game, {"receptions": 6, "receiving_yards": 50}, before=-timedelta(hours=1)
    )
    # The last two are right on the money, but the later one was saved after kickoff.
    _project(
        db, "b", wes, game, {"receptions": 5, "receiving_yards": 50}, before=timedelta(hours=1)
    )

    report = _run(db)

    assert report.overall["a"].mae == pytest.approx(0)  # the 2-hours-before one, not the first
    assert report.overall["a"].n == 1


def test_players_who_did_not_play_are_counted_and_left_out_unless_asked(db, league):
    game = _game(db, league)
    wes, inactive = _player(db, league, "Wes Receiver"), _player(db, league, "Ian Inactive")
    _played(db, wes, game)
    for source in ("a", "b"):
        _project(db, source, wes, game, ACTUAL)
        _project(db, source, inactive, game, {"receptions": 5})  # 5 points

    default = _run(db)
    scored_as_zero = _run(db, include_dnp=True)

    assert default.compared == 1 and default.did_not_play == 1
    assert scored_as_zero.compared == 2 and scored_as_zero.overall["a"].mae == pytest.approx(2.5)


def test_position_filter_and_a_breakdown_by_position_with_enough_data_flags(db, league):
    game = _game(db, league)
    wes, tom = _player(db, league, "Wes Receiver"), _player(db, league, "Tom Tight", "TE")
    fran = _player(db, league, "Fran Fullback", "FB")
    for player in (wes, tom, fran):
        _played(db, player, game)
        for source in ("a", "b"):
            _project(db, source, player, game, ACTUAL)

    everyone, only_te = _run(db), _run(db, position="te")

    assert [p.position for p in everyone.by_position] == ["RB", "TE", "WR"]  # a fullback is an RB
    assert not any(p.enough_data for p in everyone.by_position)
    assert only_te.compared == 1 and [p.position for p in only_te.by_position] == ["TE"]
    assert everyone.enough_data is False
    assert any("too few" in note for note in everyone.notes)


def test_errors_are_grouped_by_week_in_order(db, league):
    week_5 = _game(db, league, week=5, kickoff=KICKOFF + timedelta(days=7))
    week_4 = _game(db, league, week=4)
    wes = _player(db, league, "Wes Receiver")
    # Actual is 11.0. Source a is 2 low in week 4 (4 catches = 9.0) and 3 low in week 5 (8.0).
    for game, catches in ((week_5, 3), (week_4, 4)):
        _played(db, wes, game)
        _project(db, "a", wes, game, {"receptions": catches, "receiving_yards": 50})
        _project(db, "b", wes, game, ACTUAL)

    report = _run(db)

    assert [p.label for p in report.series] == ["Week 4", "Week 5"]
    assert [p.n for p in report.series] == [1, 1]
    assert report.series[0].mae == {"a": pytest.approx(2.0), "b": pytest.approx(0.0)}
    assert report.series[1].mae["a"] == pytest.approx(3.0)


def test_only_finished_games_with_complete_box_scores_count(db, league):
    scheduled = _game(db, league, status="scheduled")
    unfinished_stats = _game(db, league, week=5, stats_final=False)
    wes = _player(db, league, "Wes Receiver")
    for game in (scheduled, unfinished_stats):
        _played(db, wes, game)
        _project(db, "a", wes, game, ACTUAL)

    report = _run(db)

    assert report.compared == 0 and report.overall == {}
    assert any("No finished games" in note for note in report.notes)


def test_live_and_backtest_snapshots_are_kept_apart(db, league):
    game = _game(db, league)
    wes = _player(db, league, "Wes Receiver")
    _played(db, wes, game)
    _project(db, "a", wes, game, {"receptions": 6, "receiving_yards": 50}, origin="live")
    _project(db, "a", wes, game, {"receptions": 0}, origin="backtest")
    _project(db, "b", wes, game, ACTUAL, origin="live")

    live, backtest = _run(db), _run(db, origin="backtest")

    assert live.origin == "live" and live.overall["a"].mae == 0
    assert backtest.origin == "backtest" and backtest.overall["a"].mae == pytest.approx(11.0)


def test_asking_for_named_sources_compares_just_those(db, league):
    game = _game(db, league)
    wes = _player(db, league, "Wes Receiver")
    _played(db, wes, game)
    for source in ("a", "b", "c"):
        _project(db, source, wes, game, ACTUAL)
    _project(db, "c", _player(db, league, "Tom Tight", "TE"), game, {"receptions": 1})

    report = _run(db, sources=["a", "b"])

    assert report.sources == ["a", "b"] and set(report.overall) == {"a", "b"}


def test_spearman_is_one_for_the_same_order_and_minus_one_for_the_reverse():
    values = [float(i) for i in range(12)]
    assert accuracy._spearman(values, [v * 3 for v in values]) == pytest.approx(1.0)
    assert accuracy._spearman(values, values[::-1]) == pytest.approx(-1.0)
    assert accuracy._spearman(values[:5], values[:5]) is None  # too short to mean anything
    assert accuracy._spearman(values, [1.0] * 12) is None  # no spread at all
