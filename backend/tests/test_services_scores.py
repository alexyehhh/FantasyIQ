"""Integration tests for app/services/scores.py (real Postgres, rolled back after)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import Game, Team
from app.db.session import SessionLocal
from app.services import scores as scores_service


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


def _game(db, home, away, *, sport="NFL", season="2026", week=None, status="final", start):
    game = Game(
        sport=sport, season=season, home_team_id=home.id, away_team_id=away.id,
        start_time=start, week=week, status=status,
    )
    db.add(game)
    db.flush()
    return game


NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc).replace(tzinfo=None)


def test_nfl_defaults_to_the_current_week_and_orders_by_kickoff(db):
    alpha, bravo = _team(db, "Alpha", "ALP"), _team(db, "Bravo", "BRV")
    for week in (1, 2, 3):
        _game(db, alpha, bravo, week=week, start=NOW - timedelta(days=7 * (4 - week)))
    later = _game(db, bravo, alpha, week=4, status="scheduled", start=NOW + timedelta(days=4))
    earlier = _game(db, alpha, bravo, week=4, status="scheduled", start=NOW + timedelta(days=2))

    week, games = scores_service.get_scoreboard(db, sport="NFL", now=NOW)

    assert week == 4
    assert [g.id for g in games] == [earlier.id, later.id]


def test_nfl_includes_games_of_every_status_in_the_week(db):
    alpha, bravo = _team(db, "Alpha", "ALP"), _team(db, "Bravo", "BRV")
    final = _game(db, alpha, bravo, week=3, status="final", start=NOW - timedelta(days=1))
    live = _game(db, bravo, alpha, week=3, status="in_progress", start=NOW)
    upcoming = _game(db, alpha, bravo, week=4, status="scheduled", start=NOW + timedelta(days=6))

    week, games = scores_service.get_scoreboard(db, sport="NFL", now=NOW)

    # week 3 has an unfinished (in_progress) game, so it's still current
    assert week == 3
    assert {g.id for g in games} == {final.id, live.id}
    assert upcoming.id not in {g.id for g in games}


def test_nfl_an_explicit_week_overrides_the_current_one(db):
    alpha, bravo = _team(db, "Alpha", "ALP"), _team(db, "Bravo", "BRV")
    week1 = _game(db, alpha, bravo, week=1, start=NOW - timedelta(days=21))
    _game(db, alpha, bravo, week=3, start=NOW - timedelta(days=7))

    week, games = scores_service.get_scoreboard(db, sport="NFL", week=1, now=NOW)

    assert week == 1
    assert [g.id for g in games] == [week1.id]


def test_nfl_is_empty_before_the_season_has_any_games(db):
    week, games = scores_service.get_scoreboard(db, sport="NFL", now=NOW)

    assert week is None
    assert games == []


def test_nba_shows_only_the_next_days_games(db):
    alpha, bravo = _team(db, "Alpha", "ALP", sport="NBA"), _team(db, "Bravo", "BRV", sport="NBA")
    # 7:30pm Eastern on the 28th is 23:30 UTC
    tonight = _game(db, alpha, bravo, sport="NBA", season="2025-26",
                     start=NOW.replace(hour=23, minute=30), status="scheduled")
    _game(db, bravo, alpha, sport="NBA", season="2025-26",
          start=NOW + timedelta(days=1, hours=1), status="scheduled")

    week, games = scores_service.get_scoreboard(db, sport="NBA", now=NOW)

    assert week is None
    assert [g.id for g in games] == [tonight.id]


def test_nba_falls_back_to_the_latest_day_once_the_schedule_is_exhausted(db):
    alpha, bravo = _team(db, "Alpha", "ALP", sport="NBA"), _team(db, "Bravo", "BRV", sport="NBA")
    _game(db, alpha, bravo, sport="NBA", season="2025-26", start=NOW - timedelta(days=10))
    last = _game(db, bravo, alpha, sport="NBA", season="2025-26", start=NOW - timedelta(days=2))

    _, games = scores_service.get_scoreboard(db, sport="NBA", now=NOW)

    assert [g.id for g in games] == [last.id]


def test_nba_is_empty_before_the_season_has_any_games(db):
    week, games = scores_service.get_scoreboard(db, sport="NBA", now=NOW)

    assert week is None
    assert games == []
