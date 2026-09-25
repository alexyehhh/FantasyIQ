from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import Game, Player, PlayerGameStats, Team, TeamGameStatsNFL
from app.db.session import SessionLocal
from data_pipeline.backfill import backfill, select_games

_START = datetime(2026, 9, 10, 20, 0, tzinfo=timezone.utc)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _teams(db, sport):
    home = Team(name=f"{sport} Home", abbreviation="HOM", sport=sport)
    away = Team(name=f"{sport} Away", abbreviation="AWY", sport=sport)
    db.add_all([home, away])
    db.flush()
    return home, away


def _game(db, sport, external_id, days, status="final"):
    home, away = _teams(db, sport)
    game = Game(
        external_id=external_id,
        sport=sport,
        season="2026",
        home_team_id=home.id,
        away_team_id=away.id,
        start_time=_START + timedelta(days=days),
        status=status,
    )
    db.add(game)
    db.flush()
    return game


def test_only_finished_games_without_a_box_score_are_selected_oldest_first(db):
    _game(db, "NFL", "g-late", days=7)
    _game(db, "NFL", "g-early", days=0)
    _game(db, "NFL", "g-upcoming", days=14, status="scheduled")
    _game(db, "NFL", "g-live", days=8, status="in_progress")
    _game(db, "NBA", "g-other-sport", days=1)

    assert select_games(db, "NFL") == ["g-early", "g-late"]


def test_a_game_that_already_has_its_stats_is_skipped_unless_reingesting(db):
    nfl = _game(db, "NFL", "nfl-loaded", days=0)
    nfl.stats_final = True
    db.add(TeamGameStatsNFL(team_id=nfl.home_team_id, game_id=nfl.id))
    _game(db, "NFL", "nfl-missing", days=1)
    nba = _game(db, "NBA", "nba-loaded", days=0)
    nba.stats_final = True
    player = Player(name="P", sport="NBA", team_id=nba.home_team_id)
    db.add(player)
    db.flush()
    db.add(PlayerGameStats(player_id=player.id, game_id=nba.id))
    db.flush()

    assert select_games(db, "NFL") == ["nfl-missing"]
    assert select_games(db, "NFL", reingest=True) == ["nfl-loaded", "nfl-missing"]
    assert select_games(db, "NBA") == []
    assert select_games(db, "NBA", reingest=True) == ["nba-loaded"]


def test_a_box_score_taken_mid_game_does_not_count_as_loaded(db):
    # The live refresh stored stats while the game was on; the schedule sync then marked it final.
    game = _game(db, "NFL", "nfl-partial", days=0)
    db.add(TeamGameStatsNFL(team_id=game.home_team_id, game_id=game.id))
    db.flush()

    assert game.stats_final is False
    assert select_games(db, "NFL") == ["nfl-partial"]


def test_going_by_stats_final_alone_ignores_the_marker_table(db):
    # An NFL game whose summary never has play data has no defense rows however often it is
    # fetched; by marker it would come up on every run, by stats_final it is done.
    done = _game(db, "NFL", "nfl-no-plays", days=0)
    done.stats_final = True
    _game(db, "NFL", "nfl-unfinished", days=1)
    db.flush()

    assert select_games(db, "NFL") == ["nfl-no-plays", "nfl-unfinished"]
    assert select_games(db, "NFL", by_marker=False) == ["nfl-unfinished"]


def test_limit_caps_the_number_of_games(db):
    for index in range(3):
        _game(db, "NFL", f"g{index}", days=index)

    assert select_games(db, "NFL", limit=2) == ["g0", "g1"]


def test_backfill_ingests_each_game_pausing_between_requests(db):
    _game(db, "NFL", "g0", days=0)
    _game(db, "NFL", "g1", days=1)
    _game(db, "NFL", "g2", days=2)
    ingested: list[str] = []
    pauses: list[float] = []

    report = backfill(
        db, "NFL", delay=0.25, runner=lambda game_id: ingested.append(game_id) or 1,
        sleep=pauses.append,
    )

    assert ingested == report.ingested == ["g0", "g1", "g2"]
    assert pauses == [0.25, 0.25]  # between games, not before the first or after the last
    assert report.failed == {}


def test_one_failing_game_is_reported_and_the_rest_still_run(db):
    _game(db, "NFL", "ok-1", days=0)
    _game(db, "NFL", "bad", days=1)
    _game(db, "NFL", "ok-2", days=2)

    def runner(game_id):
        if game_id == "bad":
            raise RuntimeError("ESPN said no")
        return 1

    report = backfill(db, "NFL", delay=0, runner=runner)

    assert report.ingested == ["ok-1", "ok-2"]
    assert report.failed == {"bad": "RuntimeError: ESPN said no"}
