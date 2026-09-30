"""Saving what sources say before games (real Postgres, rolled back after)."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.models import Game, Player, ProjectionSnapshot, Team
from app.db.session import SessionLocal
from app.services.projections import snapshots
from app.services.projections.base import KickBucket, ProjectionError, Unavailable
from app.services.projections.sleeper import et_date
from tests.projection_sources import install

NOW = datetime(2026, 10, 1, 12, 0)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _team(db, name, abbreviation, sport="NFL"):
    team = Team(name=name, abbreviation=abbreviation, sport=sport)
    db.add(team)
    db.flush()
    return team


def _game(db, home, away, start, sport="NFL", week=4, status="scheduled", season="2026"):
    game = Game(
        sport=sport, season=season, home_team_id=home.id, away_team_id=away.id,
        start_time=start, week=week if sport == "NFL" else None, status=status,
    )  # fmt: skip
    db.add(game)
    db.flush()
    return game


def _player(db, team, name, position="WR", sport="NFL"):
    player = Player(name=name, sport=sport, team_id=team.id, position=position, active=True)
    db.add(player)
    db.flush()
    return player


@pytest.fixture
def league(db):
    alpha, bravo = _team(db, "Alpha Aces", "ALP"), _team(db, "Bravo Bears", "BRV")
    game = _game(db, alpha, bravo, NOW + timedelta(days=2))
    return alpha, bravo, game


def _rows(db):
    return list(db.scalars(select(ProjectionSnapshot).order_by(ProjectionSnapshot.id)))


def test_saves_each_sources_raw_stat_line_for_upcoming_games(db, league, monkeypatch):
    alpha, _, game = league
    wes = _player(db, alpha, "Wes Receiver")
    install(monkeypatch, {"Wes Receiver": {"receptions": 8.0, "receiving_yards": 50.0}})

    report = snapshots.capture(db, now=NOW, sources=["static"])

    (row,) = _rows(db)
    assert (row.source, row.kind, row.entity_id, row.game_id) == (
        "static",
        "player",
        wes.id,
        game.id,
    )
    assert row.stats == {"receptions": 8.0, "receiving_yards": 50.0}
    assert row.origin == "live" and row.captured_at == NOW and row.sport == "NFL"
    assert report.sources["static"].captured == 1


def test_a_repeat_with_the_same_stat_line_is_skipped_and_a_change_is_saved(db, league, monkeypatch):
    alpha, *_ = league
    _player(db, alpha, "Wes Receiver")
    source = install(monkeypatch, {"Wes Receiver": {"receptions": 8.0}})

    snapshots.capture(db, now=NOW, sources=["static"])
    repeat = snapshots.capture(db, now=NOW + timedelta(hours=6), sources=["static"])
    source.lines["Wes Receiver"] = {"receptions": 6.0}
    changed = snapshots.capture(db, now=NOW + timedelta(hours=12), sources=["static"])

    assert repeat.sources["static"].unchanged == 1 and repeat.sources["static"].captured == 0
    assert changed.sources["static"].captured == 1
    assert [r.stats["receptions"] for r in _rows(db)] == [8.0, 6.0]
    assert _rows(db)[-1].captured_at == NOW + timedelta(hours=12)


def test_games_already_started_or_too_far_off_are_not_captured(db, monkeypatch):
    alpha, bravo = _team(db, "Alpha Aces", "ALP"), _team(db, "Bravo Bears", "BRV")
    _player(db, alpha, "Wes Receiver")
    _game(db, alpha, bravo, NOW - timedelta(hours=1), week=3, status="in_progress")
    _game(db, alpha, bravo, NOW - timedelta(days=3), week=2, status="final")
    _game(db, alpha, bravo, NOW + timedelta(days=30), week=9)
    install(monkeypatch, {"Wes Receiver": {"receptions": 8.0}})

    report = snapshots.capture(db, now=NOW, sources=["static"])

    assert _rows(db) == [] and report.sources == {}


def test_a_player_the_source_cannot_project_is_counted_not_saved(db, league, monkeypatch):
    alpha, *_ = league
    _player(db, alpha, "Wes Receiver")
    _player(db, alpha, "Rory Rookie")
    install(monkeypatch, {"Wes Receiver": {"receptions": 8.0}, "Rory Rookie": Unavailable("x")})

    report = snapshots.capture(db, now=NOW, sources=["static"])

    assert len(_rows(db)) == 1
    assert report.sources["static"].captured == 1


def test_kicks_and_the_sources_own_notes_are_kept(db, league, monkeypatch):
    alpha, *_ = league
    _player(db, alpha, "Kip Kicker", position="PK")
    install(
        monkeypatch,
        {"Kip Kicker": {"extra_points_made": 2.0}},
        kicks={"Kip Kicker": [KickBucket(40, 49, 0.6, 0.15)]},
    )

    snapshots.capture(db, now=NOW, sources=["static"])

    (row,) = _rows(db)
    assert row.kicks == [{"low": 40, "high": 49, "made": 0.6, "missed": 0.15}]


def test_one_source_failing_does_not_stop_the_others(db, league, monkeypatch):
    alpha, *_ = league
    _player(db, alpha, "Wes Receiver")
    install(monkeypatch, {"Wes Receiver": {"receptions": 8.0}})

    class Down:
        name, label, description, sports = "down", "Down", "", frozenset({"NFL"})

        def rank(self, *args, **kwargs):
            raise ProjectionError("Sleeper could not be reached")

    monkeypatch.setitem(snapshots.PROVIDERS, "down", Down())

    report = snapshots.capture(db, now=NOW, sources=["down", "static"])

    assert report.sources["static"].captured == 1
    assert report.errors and "could not be reached" in report.errors[0]


def test_nba_games_are_captured_by_day(db, monkeypatch):
    hawks, nets = _team(db, "Some Hawks", "SOM", "NBA"), _team(db, "Other Nets", "OTH", "NBA")
    tonight = NOW + timedelta(hours=8)
    game = _game(db, hawks, nets, tonight, sport="NBA", season="2026-27")
    guard = _player(db, hawks, "Gus Guard", position="G", sport="NBA")
    source = install(monkeypatch, {"Gus Guard": {"points": 20.0}})

    snapshots.capture(db, now=NOW, sources=["static"], sports=["NBA"])

    (row,) = _rows(db)
    assert (row.entity_id, row.game_id, row.sport) == (guard.id, game.id, "NBA")
    assert source.ranked_for[2] == et_date(tonight)  # asked about that day's games
