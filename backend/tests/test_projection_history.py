"""The game-to-game swing of a player's scores, which sizes the range around a projection."""

from datetime import datetime, timedelta

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
from app.services.projections.base import Target
from app.services.projections.history import DECAY, points_spread
from app.services.scoring import default_config

NFL = default_config("NFL")
NBA = default_config("NBA")
_START = datetime(2026, 9, 10, 20, 0)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _setup(db, sport="NFL", games=4, statuses=None):
    home = Team(name="Alpha", abbreviation="ALP", sport=sport)
    away = Team(name="Bravo", abbreviation="BRV", sport=sport)
    db.add_all([home, away])
    db.flush()
    rows = []
    for i in range(games):
        game = Game(
            sport=sport,
            season="2026",
            home_team_id=home.id,
            away_team_id=away.id,
            start_time=_START + timedelta(days=7 * i),
            status=(statuses or {}).get(i, "final"),
            week=i + 1,
        )
        db.add(game)
        rows.append(game)
    player = Player(name="Wes", sport=sport, team_id=home.id, position="WR")
    db.add(player)
    db.flush()
    target = Target("player", sport, player.id, "Wes", home, "WR", rows[-1], away, True, player)
    return home, away, rows, player, target


def _std(values):
    """Recency-weighted standard deviation of `values` (most recent first)."""
    weights = [DECAY**i for i in range(len(values))]
    mean = sum(v * w for v, w in zip(values, weights, strict=True)) / sum(weights)
    variance = sum(w * (v - mean) ** 2 for v, w in zip(values, weights, strict=True)) / sum(weights)
    return round(variance**0.5, 1)


def test_the_spread_is_the_recency_weighted_swing_of_recent_fantasy_points(db):
    _, _, games, player, target = _setup(db)
    receptions = [4, 10, 2, 7]  # oldest to newest; a reception is a point under the default
    for game, count in zip(games, receptions, strict=True):
        db.add(PlayerGameStatsNFL(player_id=player.id, game_id=game.id, receptions=count))
    db.flush()

    spread, played = points_spread(db, target, NFL)

    assert played == 4
    assert spread == _std([7, 2, 10, 4])  # most recent first


def test_fewer_than_three_games_say_nothing_about_the_spread(db):
    _, _, games, player, target = _setup(db, games=2)
    for game in games:
        db.add(PlayerGameStatsNFL(player_id=player.id, game_id=game.id, receptions=5))
    db.flush()

    assert points_spread(db, target, NFL) == (None, 2)


def test_games_not_finished_do_not_count(db):
    _, _, games, player, target = _setup(db, games=4, statuses={3: "in_progress"})
    for game in games:
        db.add(PlayerGameStatsNFL(player_id=player.id, game_id=game.id, receptions=5))
    db.flush()

    assert points_spread(db, target, NFL)[1] == 3


def test_nba_games_a_player_sat_out_do_not_count(db):
    _, _, games, player, target = _setup(db, sport="NBA")
    for game, minutes in zip(games, (30, 0, 34, 28), strict=True):
        db.add(PlayerGameStats(player_id=player.id, game_id=game.id, minutes=minutes, points=20))
    db.flush()

    assert points_spread(db, target, NBA)[1] == 3


def test_a_player_with_no_games_has_no_history(db):
    *_, target = _setup(db, games=1)

    assert points_spread(db, target, NFL) == (None, 0)


def test_a_defenses_spread_comes_from_its_own_lines(db):
    home, away, games, _, _ = _setup(db)
    sacks = [1, 5, 2, 6]
    for game, count in zip(games, sacks, strict=True):
        db.add(TeamGameStatsNFL(team_id=home.id, game_id=game.id, sacks=count, points_allowed=30))
    db.flush()
    target = Target("defense", "NFL", home.id, "Alpha D/ST", home, "DEF", games[-1], away, True)

    spread, played = points_spread(db, target, NFL)

    assert played == 4 and spread == _std([6, 2, 5, 1])  # a sack is a point; 30 allowed is -1
