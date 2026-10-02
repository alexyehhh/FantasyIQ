"""The `fantasyiq` source end to end (real Postgres, rolled back after), with a stand-in for the
trained model so the tests are about the history it is given, not about what a fit learned."""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.db.models import Game, Player, PlayerGameStatsNFL, Team, TeamGameStatsNFL
from app.db.session import SessionLocal
from app.ml import defense as defense_model
from app.ml import kicker as kicker_model
from app.ml.dataset import STATS
from app.services.projections import (
    base,
    fantasyiq,
    fantasyiq_defense,
    fantasyiq_kicker,
    service,
)
from app.services.projections.news import TeamNews
from app.services.scoring import default_config

NFL = default_config("NFL")


class AverageOfLastThree:
    """Predicts each stat as the mean of the player's last three games."""

    trained_through = "2026-01-01"

    def predict(self, features):
        return pd.DataFrame({s: features[f"{s}__m3"] for s in STATS["NFL"]}, index=features.index)


class NoKicks:
    """A stand-in kicker model; these tests are about who gets projected, not what it predicts."""

    trained_through = "2026-01-01"
    league = kicker_model.LeagueRates({b: 0.8 for b in kicker_model.BUCKETS}, 0.95)

    def predict(self, features):
        return pd.DataFrame(0.0, index=features.index, columns=kicker_model.ATTEMPTS)


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
    fantasyiq._data_cache.clear()  # each test has its own games, which the cache can't tell apart
    monkeypatch.setattr(fantasyiq, "team_news", lambda db, sport, teams: TeamNews())
    monkeypatch.setattr(fantasyiq_kicker.model, "load_cached", lambda *args: NoKicks())
    fantasyiq_kicker._cache.clear()


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


def test_a_kicker_with_no_kicking_history_is_unavailable(db, league):
    alpha, *_ = league
    kicker = _player(db, alpha, "Kip Kicker", position="PK")

    (result,) = _project(db, player_ids=[kicker.id])

    assert result.status == "unavailable" and "games of history" in result.notes[0]


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


class RushesWhatTeammatesLeave:
    """Projects the rushing attempts a player inherits: shows injury news reaching the model."""

    trained_through = "2026-01-01"

    def predict(self, features):
        lines = {s: features[f"{s}__m3"] for s in STATS["NFL"]}
        lines["rushing_attempts"] = features["inherit__rushing_attempts"].fillna(0)
        return pd.DataFrame(lines, index=features.index)


def test_a_teammate_listed_out_raises_the_backups_workload(db, league, monkeypatch):
    alpha, _, past, _ = league
    starter = _player(db, alpha, "Sid Starter", position="RB")
    backup = _player(db, alpha, "Ben Backup", position="RB")
    for game in past:
        db.add(PlayerGameStatsNFL(player_id=starter.id, game_id=game.id, rushing_attempts=15))
        db.add(PlayerGameStatsNFL(player_id=backup.id, game_id=game.id, rushing_attempts=5))
    db.flush()
    monkeypatch.setattr(fantasyiq.ml_model, "load_cached", lambda sport: RushesWhatTeammatesLeave())

    (healthy,) = _project(db, player_ids=[backup.id])
    starter.injury_status = "Out"
    db.flush()
    (hurt,) = _project(db, player_ids=[backup.id])

    assert healthy.stats["rushing_attempts"] == 0
    assert hurt.stats["rushing_attempts"] == pytest.approx(15)  # the whole load: no other back


def test_the_depth_chart_decides_who_is_next_in_line(db, league, monkeypatch):
    alpha, _, past, _ = league
    starter = _player(db, alpha, "Sid Starter", position="RB")
    usual_backup = _player(db, alpha, "Ula Usual", position="RB")
    promoted = _player(db, alpha, "Pat Promoted", position="RB")
    for game in past:
        db.add(PlayerGameStatsNFL(player_id=starter.id, game_id=game.id, rushing_attempts=15))
        db.add(PlayerGameStatsNFL(player_id=usual_backup.id, game_id=game.id, rushing_attempts=7))
        db.add(PlayerGameStatsNFL(player_id=promoted.id, game_id=game.id, rushing_attempts=3))
    starter.injury_status = "Out"
    db.flush()

    class ReportsRank:
        trained_through = "2026-01-01"

        def predict(self, features):
            lines = {s: features[f"{s}__m3"] for s in STATS["NFL"]}
            lines["rushing_attempts"] = features["group_rank"].fillna(0)
            return pd.DataFrame(lines, index=features.index)

    monkeypatch.setattr(fantasyiq.ml_model, "load_cached", lambda sport: ReportsRank())

    def ranks(depth):
        monkeypatch.setattr(fantasyiq, "team_news", lambda db, sport, teams: TeamNews(depth=depth))
        fantasyiq._data_cache.clear()
        results = _project(db, player_ids=[usual_backup.id, promoted.id])
        return {r.name: r.stats["rushing_attempts"] for r in results}

    by_workload = ranks({})
    by_depth_chart = ranks({promoted.id: 1, usual_backup.id: 2, starter.id: 3})

    assert by_workload == {"Ula Usual": 1, "Pat Promoted": 2}
    assert by_depth_chart == {"Pat Promoted": 1, "Ula Usual": 2}


class DefenseFromOpponentOffense:
    """Projects points allowed as the opponent's recent scoring, sacks as the defense's own."""

    trained_through = "2026-01-01"

    def predict(self, features):
        lines = {s: features[f"{s}__ewm"].fillna(0) for s in defense_model.STATS}
        lines["points_allowed"] = features["opp_points_scored__ewm"].fillna(0)
        return pd.DataFrame(lines, index=features.index)


def _team_stats(db, team, game, **stats):
    db.add(TeamGameStatsNFL(team_id=team.id, game_id=game.id, **stats))
    db.flush()


def test_a_defense_is_projected_from_its_games_and_the_opponents_offense(db, league, monkeypatch):
    alpha, bravo, past, _ = league
    for game in past:
        # Alpha's defense: 3 sacks, allowing 10. Bravo's defense allows 31 to Alpha's offense.
        _team_stats(db, alpha, game, sacks=3, points_allowed=10)
        _team_stats(db, bravo, game, sacks=1, points_allowed=31)
    monkeypatch.setattr(
        fantasyiq_defense.model, "load_cached", lambda *args: DefenseFromOpponentOffense()
    )
    fantasyiq_defense._cache.clear()

    (result,) = _project(db, player_ids=[], defense_ids=[alpha.id])

    assert result.status == "ok" and result.kind == "defense"
    assert result.stats["sacks"] == pytest.approx(3)
    # Bravo's offense scored 10 on Alpha each time, so that is what Alpha is expected to allow.
    assert result.stats["points_allowed"] == pytest.approx(10)
    assert "opponent's recent offense" in result.notes[0]


def test_a_defense_with_too_few_games_is_unavailable(db, league, monkeypatch):
    alpha, bravo, past, _ = league
    _team_stats(db, alpha, past[0], sacks=3, points_allowed=10)
    _team_stats(db, bravo, past[0], sacks=1, points_allowed=31)
    monkeypatch.setattr(
        fantasyiq_defense.model, "load_cached", lambda *args: DefenseFromOpponentOffense()
    )
    fantasyiq_defense._cache.clear()

    (result,) = _project(db, player_ids=[], defense_ids=[alpha.id])

    assert result.status == "unavailable" and "games of history" in result.notes[0]


def test_an_untrained_defense_model_is_an_error(db, league, monkeypatch):
    alpha, *_ = league
    monkeypatch.setattr(fantasyiq_defense.model, "load_cached", lambda *args: None)

    with pytest.raises(base.ProjectionError, match="defense model hasn't been trained"):
        _project(db, player_ids=[], defense_ids=[alpha.id])


def test_defenses_are_ranked_by_the_week(db, league, monkeypatch):
    alpha, bravo, past, _ = league
    for game in past:
        _team_stats(db, alpha, game, sacks=5, points_allowed=10)
        _team_stats(db, bravo, game, sacks=0, points_allowed=30)
    monkeypatch.setattr(
        fantasyiq_defense.model, "load_cached", lambda *args: DefenseFromOpponentOffense()
    )
    fantasyiq_defense._cache.clear()

    ranked = fantasyiq.FANTASYIQ.rank(
        db, sport="NFL", season="2026", week=4, day=None, positions=None, defenses=True, config=NFL
    )

    assert [c.entity_id for c in ranked] == [alpha.id, bravo.id]
    assert all(c.kind == "defense" for c in ranked)
