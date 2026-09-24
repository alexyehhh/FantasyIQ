"""Integration tests for the team defense service (real Postgres, rolled back after each test)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import Game, Team, TeamGameStatsNFL
from app.db.session import SessionLocal
from app.services import defenses as defenses_service
from app.services import players as players_service
from app.services.scoring import Bracket, ScoringConfig, default_config

_START = datetime(2026, 9, 10, 20, 0, tzinfo=timezone.utc)
NBA = default_config("NBA")


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


def _game(db, home, away, week, home_score=None, away_score=None, season="2026", status="final"):
    game = Game(
        sport="NFL",
        season=season,
        home_team_id=home.id,
        away_team_id=away.id,
        start_time=_START + timedelta(days=7 * week),
        week=week,
        status=status,
        home_score=home_score,
        away_score=away_score,
    )
    db.add(game)
    db.flush()
    return game


def _line(db, team, game, **stats):
    row = TeamGameStatsNFL(team_id=team.id, game_id=game.id, **stats)
    db.add(row)
    db.flush()
    return row


def _league(db):
    """Three NFL teams, one NBA team, and two games of stats for the first two NFL teams."""
    alpha = _team(db, "Alpha Aces", "ALP")
    bravo = _team(db, "Bravo Bears", "BRV")
    charlie = _team(db, "Charlie Chiefs", "CHA")
    _team(db, "Hoops", "HPS", sport="NBA")
    week1 = _game(db, alpha, bravo, 1, 24, 7)
    week2 = _game(db, charlie, alpha, 2, 10, 0)
    # Alpha: game 1 = 3 sacks + 2 (INT) + 4 (7 allowed) = 9; game 2 = 5 sacks + 10 (shutout) = 15.
    _line(db, alpha, week1, sacks=3, interceptions=1, points_allowed=7)
    _line(db, alpha, week2, sacks=5, points_allowed=0)
    # Bravo: 1 sack, 31 points allowed (-1) -> 0.
    _line(db, bravo, week1, sacks=1, points_allowed=31)
    return alpha, bravo, charlie, week1, week2


def test_only_nfl_teams_are_listed_as_defenses(db):
    _league(db)

    teams, total = defenses_service.list_defenses(db, search="")

    assert [t.abbreviation for t in teams] == ["ALP", "BRV", "CHA"]
    assert total == 3


def test_search_matches_team_name_or_abbreviation_and_paging_keeps_the_total(db):
    _league(db)

    by_name, _ = defenses_service.list_defenses(db, search="bears")
    by_abbreviation, _ = defenses_service.list_defenses(db, search="cha")
    page, total = defenses_service.list_defenses(db, limit=1, offset=1)

    assert [t.abbreviation for t in by_name] == ["BRV"]
    assert [t.abbreviation for t in by_abbreviation] == ["CHA"]
    assert ([t.abbreviation for t in page], total) == (["BRV"], 3)


def test_ranking_sums_the_season_and_puts_teams_without_stats_last(db):
    alpha, bravo, charlie, *_ = _league(db)

    teams, _ = defenses_service.list_defenses(db, sort="fantasy_points")
    points = defenses_service.get_season_fantasy_points(db, teams)

    assert [t.abbreviation for t in teams] == ["ALP", "BRV", "CHA"]
    assert points == {alpha.id: 24, bravo.id: 0}  # Charlie has no stats, so is absent


def test_season_points_match_the_python_scorer_for_the_same_lines(db):
    from app.services.scoring import score_defense_game

    alpha, _, _, week1, week2 = _league(db)
    config = default_config("NFL")
    rows = defenses_service.get_defense_game_log(db, alpha)

    expected = sum(defenses_service.defense_game_fantasy_points(config, row) for row in rows)

    assert expected == 24
    assert defenses_service.get_season_fantasy_points(db, [alpha])[alpha.id] == expected
    assert score_defense_game(config, {"sacks": 5, "points_allowed": 0}) == 15


def test_only_the_latest_season_with_stats_is_ranked(db):
    alpha, bravo, *_ = _league(db)
    old = _game(db, alpha, bravo, 0, 30, 0, season="2025")
    _line(db, bravo, old, sacks=9, points_allowed=30)

    points = defenses_service.get_season_fantasy_points(db, [alpha, bravo])

    assert points[bravo.id] == 0  # last season's nine sacks don't count


def test_a_custom_scoring_config_changes_the_points_and_the_order(db):
    alpha, bravo, *_ = _league(db)
    only_sacks = ScoringConfig(name="Sacks only", sport="NFL", defense_weights={"sacks": 10})
    bracketed = ScoringConfig(
        name="Big scores hurt",
        sport="NFL",
        points_allowed=(Bracket(max=10, points=1), Bracket(min=11, points=-5)),
    )

    by_sacks = defenses_service.get_season_fantasy_points(db, [alpha, bravo], only_sacks)
    by_allowed = defenses_service.get_season_fantasy_points(db, [alpha, bravo], bracketed)
    ranked, _ = defenses_service.list_defenses(db, sort="fantasy_points", scoring=bracketed)

    assert (by_sacks[alpha.id], by_sacks[bravo.id]) == (80, 10)
    assert (by_allowed[alpha.id], by_allowed[bravo.id]) == (2, -5)
    # Bravo's -5 drops it below Charlie, who has no stats and counts as 0.
    assert [t.abbreviation for t in ranked][:2] == ["ALP", "CHA"]


def test_an_nba_scoring_config_cannot_score_defenses(db):
    _league(db)

    with pytest.raises(ValueError, match="can't score team defenses"):
        defenses_service.list_defenses(db, sort="fantasy_points", scoring=NBA)


def test_get_defense_finds_nfl_teams_only(db):
    alpha, *_ = _league(db)
    hoops = db.query(Team).filter_by(abbreviation="HPS").one()

    assert defenses_service.get_defense(db, alpha.id) is alpha
    assert defenses_service.get_defense(db, hoops.id) is None
    assert defenses_service.get_defense(db, 999_999) is None


def test_the_game_log_is_newest_first_with_opponent_result_and_points(db):
    alpha, bravo, charlie, *_ = _league(db)

    log = defenses_service.get_defense_game_log(db, alpha)

    assert [(row.game.week, row.opponent.abbreviation) for row in log] == [(2, "CHA"), (1, "BRV")]
    assert [row.result for row in log] == ["L", "W"]  # 0-10 at Charlie, then 24-7 over Bravo
    assert [(row.team_score, row.opponent_score) for row in log] == [(0, 10), (24, 7)]
    config = default_config("NFL")
    assert [defenses_service.defense_game_fantasy_points(config, r) for r in log] == [15, 9]
    assert defenses_service.serialize_defense_row(log[1].stats_row)["sacks"] == 3
    assert "id" not in defenses_service.serialize_defense_row(log[1].stats_row)
    assert len(defenses_service.get_defense_game_log(db, alpha, limit=1)) == 1


def test_a_team_schedule_and_next_game_work_without_a_player(db):
    alpha, bravo, charlie, week1, week2 = _league(db)
    upcoming = _game(db, alpha, charlie, 3, status="scheduled")
    upcoming.start_time = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=3)
    db.flush()

    schedule = players_service.get_team_schedule(db, alpha.id, "NFL")
    game, opponent, is_home = players_service.get_team_next_game(db, alpha.id)

    assert [m.game.week for m in schedule] == [1, 2, 3]
    assert (game.id, opponent.id, is_home) == (upcoming.id, charlie.id, True)
