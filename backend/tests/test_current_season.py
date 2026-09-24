"""The season in play: what the player and defense pages show stats for.

The NBA offseason is the case that matters: last season's games are in the database with
stats, the next season's are scheduled, and none of them has been played yet. Last season's
stats are then history, not "this season".
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.db.models import Game, Player, PlayerGameStats, Team, TeamGameStatsNFL
from app.db.session import SessionLocal, get_db
from app.main import app
from app.services import players as players_service
from app.services import season_summary as summaries

NOW = datetime(2026, 9, 24, 12, 0)  # naive UTC, as stored


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _team(db, sport="NBA", abbreviation="TST"):
    team = Team(name=f"{sport} {abbreviation}", abbreviation=abbreviation, sport=sport)
    db.add(team)
    db.flush()
    return team


def _game(db, team, season, start, status="final", sport="NBA"):
    game = Game(
        sport=sport,
        season=season,
        home_team_id=team.id,
        away_team_id=team.id,
        start_time=start,
        status=status,
    )
    db.add(game)
    db.flush()
    return game


def _offseason(db):
    """Two finished games from last season, and the next season scheduled (not started)."""
    team = _team(db)
    old = [_game(db, team, "2025-26", NOW - timedelta(days=170 - n)) for n in range(2)]
    opener = _game(db, team, "2026-27", NOW + timedelta(days=26), status="scheduled")
    return team, old, opener


def test_the_season_in_play_is_the_next_games_even_when_last_season_has_stats(db):
    _offseason(db)

    assert players_service.get_current_season(db, "NBA", now=NOW) == "2026-27"


def test_a_game_in_progress_counts_as_the_season_in_play(db):
    team = _team(db)
    _game(db, team, "2025-26", NOW - timedelta(days=200))
    _game(db, team, "2026-27", NOW - timedelta(hours=1), status="in_progress")

    assert players_service.get_current_season(db, "NBA", now=NOW) == "2026-27"


def test_once_the_schedule_has_run_out_it_is_the_latest_games_season(db):
    team = _team(db)
    _game(db, team, "2025-26", NOW - timedelta(days=300))
    _game(db, team, "2026-27", NOW - timedelta(days=5))

    assert players_service.get_current_season(db, "NBA", now=NOW) == "2026-27"


def test_a_sports_season_ignores_the_other_sports_games_and_is_none_without_games(db):
    _offseason(db)
    football = _team(db, sport="NFL", abbreviation="FTB")
    _game(db, football, "2026", NOW + timedelta(days=3), status="scheduled", sport="NFL")

    assert players_service.get_current_season(db, "NFL", now=NOW) == "2026"
    assert players_service.get_current_season(db, "NBA", now=NOW) == "2026-27"
    db.query(Game).delete()
    assert players_service.get_current_season(db, "NBA", now=NOW) is None


def _guard_with_last_seasons_games(db):
    team, old, _ = _offseason(db)
    player = Player(name="Luke Kennard", sport="NBA", team_id=team.id, position="G")
    db.add(player)
    db.flush()
    for game in old:
        db.add(PlayerGameStats(player_id=player.id, game_id=game.id, minutes=30, points=12))
    db.flush()
    return player


def test_the_game_log_can_be_limited_to_one_season(db):
    player = _guard_with_last_seasons_games(db)

    assert len(players_service.get_player_game_log(db, player)) == 2
    assert len(players_service.get_player_game_log(db, player, season="2025-26")) == 2
    assert players_service.get_player_game_log(db, player, season="2026-27") == []


def test_a_player_with_only_last_seasons_stats_has_no_season_summary_yet(db):
    player = _guard_with_last_seasons_games(db)

    assert summaries.get_player_season_summary(db, player) is None


def test_the_summary_turns_up_once_the_new_season_has_a_played_game(db):
    player = _guard_with_last_seasons_games(db)
    opener = db.query(Game).filter_by(season="2026-27").one()
    opener.start_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    db.add(PlayerGameStats(player_id=player.id, game_id=opener.id, minutes=25, points=20))
    later = _game(db, db.get(Team, player.team_id), "2026-27",
                  datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=2),
                  status="scheduled")
    assert later.season == "2026-27"
    db.flush()

    summary = summaries.get_player_season_summary(db, player)

    assert (summary.season, summary.games, summary.stats["points"].total) == ("2026-27", 1, 20)


def test_the_stats_endpoint_returns_only_the_season_in_play_when_asked(client, db):
    player = _guard_with_last_seasons_games(db)
    opener = db.query(Game).filter_by(season="2026-27").one()
    # The season in play is 2026-27, whose opener is in the future: no games yet.
    opener.start_time = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=26)
    db.flush()

    everything = client.get(f"/api/v1/players/{player.id}/stats")
    current = client.get(f"/api/v1/players/{player.id}/stats", params={"season": "current"})
    named = client.get(f"/api/v1/players/{player.id}/stats", params={"season": "all"})

    assert len(everything.json()) == 2  # the default keeps history, e.g. for models
    assert len(named.json()) == 2
    assert current.status_code == 200 and current.json() == []
    assert client.get(
        f"/api/v1/players/{player.id}/stats", params={"season": "last"}
    ).status_code == 422


def test_the_stats_endpoint_keeps_this_seasons_games_and_drops_last_seasons(client, db):
    player = _guard_with_last_seasons_games(db)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    opener = db.query(Game).filter_by(season="2026-27").one()
    opener.start_time = now - timedelta(days=1)
    opener.status = "final"
    db.add(PlayerGameStats(player_id=player.id, game_id=opener.id, minutes=25, points=20))
    _game(db, db.get(Team, player.team_id), "2026-27", now + timedelta(days=2), status="scheduled")
    db.flush()

    current = client.get(f"/api/v1/players/{player.id}/stats", params={"season": "current"}).json()

    assert [game["stats"]["points"] for game in current] == [20]
    assert len(client.get(f"/api/v1/players/{player.id}/stats").json()) == 3


def test_the_defense_stats_endpoint_takes_the_same_season_parameter(client, db):
    team = _team(db, sport="NFL", abbreviation="DEF")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    last = _game(db, team, "2025", now - timedelta(days=200), sport="NFL")
    _game(db, team, "2026", now + timedelta(days=5), status="scheduled", sport="NFL")
    db.add(TeamGameStatsNFL(team_id=team.id, game_id=last.id, sacks=3))
    db.flush()

    everything = client.get(f"/api/v1/defenses/{team.id}/stats").json()
    current = client.get(f"/api/v1/defenses/{team.id}/stats", params={"season": "current"}).json()

    assert len(everything) == 1
    assert current == []
    assert client.get(f"/api/v1/defenses/{team.id}/season").json() is None
