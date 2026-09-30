"""The `fantasyiq` source end to end (real Postgres, rolled back after), with a stand-in for the
trained model so the tests are about the history it is given, not about what a fit learned."""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.db.models import Game, Player, PlayerGameStatsNFL, Team
from app.db.session import SessionLocal
from app.ml.dataset import STATS
from app.services.projections import base, fantasyiq, service
from app.services.scoring import default_config

NFL = default_config("NFL")


class AverageOfLastThree:
    """Predicts each stat as the mean of the player's last three games."""

    trained_through = "2026-01-01"

    def predict(self, features):
        return pd.DataFrame({s: features[f"{s}__m3"] for s in STATS["NFL"]}, index=features.index)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(autouse=True)
def trained(monkeypatch):
    monkeypatch.setattr(fantasyiq.ml_model, "load_cached", lambda sport: AverageOfLastThree())


def _team(db, name, abbreviation):
    team = Team(name=name, abbreviation=abbreviation, sport="NFL")
    db.add(team)
    db.flush()
    return team


def _game(db, home, away, week, status="final", days_ago=None):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    start = now - timedelta(days=days_ago) if days_ago else now + timedelta(days=3)
    game = Game(
        sport="NFL", season="2026", home_team_id=home.id, away_team_id=away.id,
        start_time=start, week=week, status=status, stats_final=status == "final",
    )  # fmt: skip
    db.add(game)
    db.flush()
    return game


def _player(db, team, name, position="WR"):
    player = Player(name=name, sport="NFL", team_id=team.id, position=position, active=True)
    db.add(player)
    db.flush()
    return player


def _stats(db, player, game, receptions):
    db.add(PlayerGameStatsNFL(player_id=player.id, game_id=game.id, receptions=receptions))
    db.flush()


@pytest.fixture
def league(db):
    alpha, bravo = _team(db, "Alpha Aces", "ALP"), _team(db, "Bravo Bears", "BRV")
    past = [_game(db, alpha, bravo, week, days_ago=7 * (4 - week)) for week in (1, 2, 3)]
    upcoming = _game(db, alpha, bravo, 4, status="scheduled")
    return alpha, bravo, past, upcoming


def _project(db, **kwargs):
    return service.project(db, sport="NFL", source="fantasyiq", config=NFL, **kwargs)


def test_it_is_a_listed_source():
    assert "fantasyiq" in base.PROVIDERS


def test_projects_from_the_players_earlier_games_and_scores_them(db, league):
    alpha, _, past, _ = league
    wes = _player(db, alpha, "Wes Receiver")
    for game, receptions in zip(past, (4, 5, 9), strict=True):
        _stats(db, wes, game, receptions)

    (result,) = _project(db, player_ids=[wes.id])

    assert result.status == "ok"
    assert result.stats["receptions"] == 6  # mean of 4, 5, 9
    assert result.fantasy_points == 6.0  # one point per reception, nothing else
    assert "games to 2026-01-01" in result.notes[0]


def test_games_after_the_one_projected_are_not_used(db, league):
    alpha, bravo, past, upcoming = league
    wes = _player(db, alpha, "Wes Receiver")
    for game, receptions in zip(past, (4, 5, 6), strict=True):
        _stats(db, wes, game, receptions)
    # A finished game dated *after* the upcoming one would leak the future if it were read.
    later = _game(db, alpha, bravo, 9, days_ago=1)
    later.start_time = upcoming.start_time + timedelta(days=30)
    _stats(db, wes, later, 40)

    (result,) = _project(db, player_ids=[wes.id])

    assert result.stats["receptions"] == 5


def test_a_player_with_too_little_history_is_unavailable(db, league):
    alpha, _, past, _ = league
    rookie = _player(db, alpha, "Rory Rookie")
    _stats(db, rookie, past[0], 3)

    (result,) = _project(db, player_ids=[rookie.id])

    assert result.status == "unavailable"
    assert "games of history" in result.notes[0]


def test_kickers_and_defenses_are_not_modelled(db, league):
    alpha, *_ = league
    kicker = _player(db, alpha, "Kip Kicker", position="PK")

    results = _project(db, player_ids=[kicker.id], defense_ids=[alpha.id])

    assert [r.status for r in results] == ["unavailable", "unavailable"]
    assert all("doesn't project" in r.notes[0] for r in results)


def test_an_untrained_model_is_an_error_not_a_guess(db, league, monkeypatch):
    alpha, *_ = league
    wes = _player(db, alpha, "Wes Receiver")
    monkeypatch.setattr(fantasyiq.ml_model, "load_cached", lambda sport: None)

    with pytest.raises(base.ProjectionError, match="hasn't been trained"):
        _project(db, player_ids=[wes.id])


def test_ranking_orders_the_weeks_players_by_projected_points(db, league):
    alpha, bravo, past, _ = league
    star, role = _player(db, alpha, "Sam Star"), _player(db, bravo, "Ray Role")
    kicker = _player(db, alpha, "Kip Kicker", position="PK")
    for game in past:
        _stats(db, star, game, 9)
        _stats(db, role, game, 2)
        _stats(db, kicker, game, 0)

    def rank(positions):
        return fantasyiq.FANTASYIQ.rank(
            db, sport="NFL", season="2026", week=4, day=None, positions=positions,
            defenses=False, config=NFL,
        )  # fmt: skip

    assert [c.entity_id for c in rank(["WR"])] == [star.id, role.id]
    assert rank(["PK"]) == []
    assert rank(None)[0].points == 9.0
