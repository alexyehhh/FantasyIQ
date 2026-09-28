"""Integration tests for app/ai/tools.py (real Postgres, rolled back after each test)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.ai import tools
from app.db.models import Game, Player, PlayerGameStatsNFL, Team, TeamGameStatsNFL
from app.db.session import SessionLocal
from tests.projection_sources import install

_START = datetime(2026, 9, 10, 20, 0)


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
    """Alpha (with a finished game and defense line) vs. Bravo, plus Alpha's upcoming game."""
    alpha = Team(name="Alpha Aces", abbreviation="ALP", sport="NFL")
    bravo = Team(name="Bravo Bears", abbreviation="BRV", sport="NFL")
    db.add_all([alpha, bravo])
    db.flush()

    def game(week, status, start, home_score=None, away_score=None):
        row = Game(
            sport="NFL", season="2026", home_team_id=alpha.id, away_team_id=bravo.id,
            start_time=start, week=week, status=status,
            home_score=home_score, away_score=away_score,
        )  # fmt: skip
        db.add(row)
        db.flush()
        return row

    played = game(1, "final", _START, home_score=24, away_score=17)
    next_week = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=3)
    upcoming = game(2, "scheduled", next_week)

    receiver = Player(name="Wes Receiver", sport="NFL", team_id=alpha.id, position="WR")
    db.add(receiver)
    db.flush()
    db.add(
        PlayerGameStatsNFL(
            player_id=receiver.id, game_id=played.id, receptions=8, receiving_yards=100
        )
    )
    db.add(TeamGameStatsNFL(team_id=alpha.id, game_id=played.id, sacks=3, interceptions=1))
    db.flush()

    return {
        "alpha": alpha,
        "bravo": bravo,
        "receiver": receiver,
        "played": played,
        "upcoming": upcoming,
    }


def test_get_stats_for_a_player(db, league):
    result = tools.get_stats(db, kind="player", entity_id=league["receiver"].id)

    assert result["name"] == "Wes Receiver"
    assert result["team"] == "ALP"
    assert result["kind"] == "player"
    assert result["season_summary"]["games_played"] == 1
    assert len(result["recent_games"]) == 1
    assert result["recent_games"][0]["opponent"] == "BRV"
    assert result["recent_games"][0]["fantasy_points"] > 0


def test_get_stats_for_a_defense(db, league):
    result = tools.get_stats(db, kind="defense", entity_id=league["alpha"].id)

    assert result["kind"] == "defense"
    assert result["team"] == "ALP"
    assert result["season_summary"]["games_played"] == 1
    assert result["recent_games"][0]["fantasy_points"] > 0


def test_get_stats_unknown_entity_is_an_error_not_an_exception(db, league):
    assert tools.get_stats(db, kind="player", entity_id=999_999) == {
        "error": "No player with id 999999"
    }


def test_get_matchup_defaults_to_the_next_game(db, league):
    result = tools.get_matchup(db, kind="player", entity_id=league["receiver"].id)

    assert result["team"] == "ALP"
    assert len(result["games"]) == 1
    assert result["games"][0]["week"] == 2
    assert result["games"][0]["status"] == "scheduled"
    assert "doesn't rate matchup difficulty" in result["note"]


def test_get_matchup_can_ask_for_a_specific_week(db, league):
    result = tools.get_matchup(db, kind="defense", entity_id=league["alpha"].id, week=1)

    assert len(result["games"]) == 1
    assert result["games"][0]["status"] == "final"
    assert result["games"][0]["result"] is not None


def test_get_matchup_week_only_applies_to_nfl(db):
    team = Team(name="Nova Ninjas", abbreviation="NVA", sport="NBA")
    db.add(team)
    db.flush()
    player = Player(name="Cam Center", sport="NBA", team_id=team.id, position="C")
    db.add(player)
    db.flush()

    result = tools.get_matchup(db, kind="player", entity_id=player.id, week=3)
    assert result == {"error": "week only applies to the NFL"}


def test_get_projection_uses_the_named_source(db, league, monkeypatch):
    install(monkeypatch, {"Wes Receiver": {"receptions": 6, "receiving_yards": 80}})

    result = tools.get_projection(
        db, kind="player", entity_id=league["receiver"].id, source="static"
    )

    assert result["source"] == "static"
    assert result["status"] == "ok"
    assert result["fantasy_points"] > 0
    assert result["opponent"] == "BRV"


def test_get_projection_unknown_source_is_an_error(db, league):
    result = tools.get_projection(
        db, kind="player", entity_id=league["receiver"].id, source="nope"
    )
    assert "error" in result


def test_call_tool_dispatches_by_name(db, league, monkeypatch):
    install(monkeypatch, {"Wes Receiver": {"receptions": 1, "receiving_yards": 10}})

    args = {"kind": "player", "entity_id": league["receiver"].id, "source": "static"}
    result = tools.call_tool(db, "get_projection", args)
    assert result["status"] == "ok"


def test_call_tool_unknown_name(db):
    assert tools.call_tool(db, "not_a_tool", {}) == {"error": "Unknown tool 'not_a_tool'"}


def test_call_tool_bad_arguments(db):
    result = tools.call_tool(db, "get_stats", {"kind": "player"})
    assert "Bad arguments" in result["error"]
