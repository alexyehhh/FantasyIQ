"""
Integration tests for app/services/players.py.

Hits a real Postgres database, same pattern as test_models.py: each
test flushes (never commits) inside a session that's rolled back at
teardown, so nothing persists between tests.
"""

from datetime import datetime, timezone

import pytest

from app.db.models import Game, Player, PlayerGameStats, PlayerGameStatsNFL, Team
from app.db.session import SessionLocal
from app.services import players as players_service


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _make_team(db, sport="NBA", name="Test Team", abbreviation="TST"):
    team = Team(name=name, abbreviation=abbreviation, sport=sport)
    db.add(team)
    db.flush()
    return team


def _make_player(db, team, sport="NBA", name="Test Player", **kwargs):
    player = Player(name=name, sport=sport, team_id=team.id, **kwargs)
    db.add(player)
    db.flush()
    return player


def _make_game(db, team, sport="NBA", start_time=None):
    game = Game(
        sport=sport,
        season="2025-26" if sport == "NBA" else "2025",
        home_team_id=team.id,
        away_team_id=team.id,
        start_time=start_time or datetime(2026, 1, 1, tzinfo=timezone.utc),
        status="final",
    )
    db.add(game)
    db.flush()
    return game


def test_list_players_returns_all_by_default(db):
    team = _make_team(db)
    _make_player(db, team, name="Alice")
    _make_player(db, team, name="Bob")

    players, total = players_service.list_players(db)

    assert total >= 2
    assert {p.name for p in players} >= {"Alice", "Bob"}


def test_list_players_filters_by_sport(db):
    nba_team = _make_team(db, sport="NBA", abbreviation="NBA1")
    nfl_team = _make_team(db, sport="NFL", abbreviation="NFL1")
    _make_player(db, nba_team, sport="NBA", name="Hooper")
    _make_player(db, nfl_team, sport="NFL", name="Gridiron")

    players, _total = players_service.list_players(db, sport="NFL")

    assert all(p.sport == "NFL" for p in players)
    assert "Gridiron" in {p.name for p in players}
    assert "Hooper" not in {p.name for p in players}


def test_list_players_search_is_case_insensitive_substring(db):
    team = _make_team(db)
    _make_player(db, team, name="Stephen Curry")

    players, total = players_service.list_players(db, search="curry")

    assert total == 1
    assert players[0].name == "Stephen Curry"


def test_list_players_pagination(db):
    team = _make_team(db)
    for i in range(5):
        _make_player(db, team, name=f"Pager {i}")

    page, total = players_service.list_players(
        db, search="Pager", limit=2, offset=0
    )
    assert total == 5
    assert len(page) == 2


def test_get_player_returns_none_for_missing_id(db):
    assert players_service.get_player(db, 0) is None


def test_get_player_returns_player(db):
    team = _make_team(db)
    player = _make_player(db, team, name="Findable")

    fetched = players_service.get_player(db, player.id)

    assert fetched is not None
    assert fetched.name == "Findable"


def test_get_player_game_log_nba(db):
    team = _make_team(db, sport="NBA")
    player = _make_player(db, team, sport="NBA")
    game = _make_game(db, team, sport="NBA")
    db.add(PlayerGameStats(player_id=player.id, game_id=game.id, points=30))
    db.flush()

    rows = players_service.get_player_game_log(db, player)

    assert len(rows) == 1
    assert rows[0].stats_row.points == 30
    assert rows[0].game.id == game.id


def test_get_player_game_log_nfl(db):
    team = _make_team(db, sport="NFL")
    player = _make_player(db, team, sport="NFL")
    game = _make_game(db, team, sport="NFL")
    db.add(
        PlayerGameStatsNFL(player_id=player.id, game_id=game.id, passing_yards=275)
    )
    db.flush()

    rows = players_service.get_player_game_log(db, player)

    assert len(rows) == 1
    assert rows[0].stats_row.passing_yards == 275


def test_get_player_game_log_orders_most_recent_first(db):
    team = _make_team(db, sport="NBA")
    player = _make_player(db, team, sport="NBA")
    older_game = _make_game(db, team, start_time=datetime(2025, 12, 1, tzinfo=timezone.utc))
    newer_game = _make_game(db, team, start_time=datetime(2026, 1, 1, tzinfo=timezone.utc))
    db.add(PlayerGameStats(player_id=player.id, game_id=older_game.id, points=10))
    db.add(PlayerGameStats(player_id=player.id, game_id=newer_game.id, points=20))
    db.flush()

    rows = players_service.get_player_game_log(db, player)

    assert [row.stats_row.points for row in rows] == [20, 10]


def test_get_player_game_log_respects_limit(db):
    team = _make_team(db, sport="NBA")
    player = _make_player(db, team, sport="NBA")
    for i in range(3):
        game = _make_game(
            db, team, start_time=datetime(2026, 1, i + 1, tzinfo=timezone.utc)
        )
        db.add(PlayerGameStats(player_id=player.id, game_id=game.id, points=i))
    db.flush()

    rows = players_service.get_player_game_log(db, player, limit=2)

    assert len(rows) == 2


def test_serialize_stats_row_excludes_identity_columns(db):
    team = _make_team(db, sport="NBA")
    player = _make_player(db, team, sport="NBA")
    game = _make_game(db, team, sport="NBA")
    stats = PlayerGameStats(player_id=player.id, game_id=game.id, points=15, assists=5)
    db.add(stats)
    db.flush()

    serialized = players_service.serialize_stats_row(stats)

    assert serialized["points"] == 15
    assert serialized["assists"] == 5
    assert "id" not in serialized
    assert "player_id" not in serialized
    assert "game_id" not in serialized
    assert "created_at" not in serialized


def _make_matchup(db, home, away, *, home_score=None, away_score=None, start_time=None):
    game = Game(
        sport=home.sport,
        season="2025-26",
        home_team_id=home.id,
        away_team_id=away.id,
        start_time=start_time or datetime(2026, 1, 1),
        status="final" if home_score is not None else "scheduled",
        home_score=home_score,
        away_score=away_score,
    )
    db.add(game)
    db.flush()
    return game


def test_game_log_resolves_opponent_side_and_result_for_home_player(db):
    home = _make_team(db, name="Home Team", abbreviation="HOM")
    away = _make_team(db, name="Away Team", abbreviation="AWY")
    player = _make_player(db, home)
    game = _make_matchup(db, home, away, home_score=110, away_score=104)
    db.add(PlayerGameStats(player_id=player.id, game_id=game.id, points=20))
    db.flush()

    (row,) = players_service.get_player_game_log(db, player)

    assert row.is_home is True
    assert row.opponent.abbreviation == "AWY"
    assert (row.team_score, row.opponent_score, row.result) == (110, 104, "W")


def test_game_log_flips_scores_for_away_player_and_marks_loss(db):
    home = _make_team(db, name="Home Team", abbreviation="HOM")
    away = _make_team(db, name="Away Team", abbreviation="AWY")
    player = _make_player(db, away)
    game = _make_matchup(db, home, away, home_score=110, away_score=104)
    db.add(PlayerGameStats(player_id=player.id, game_id=game.id, points=20))
    db.flush()

    (row,) = players_service.get_player_game_log(db, player)

    assert row.is_home is False
    assert row.opponent.abbreviation == "HOM"
    assert (row.team_score, row.opponent_score, row.result) == (104, 110, "L")


def test_game_log_result_is_tie_or_unknown_when_appropriate(db):
    home = _make_team(db, name="Home Team", abbreviation="HOM")
    away = _make_team(db, name="Away Team", abbreviation="AWY")
    player = _make_player(db, home, sport="NBA")
    tied = _make_matchup(db, home, away, home_score=20, away_score=20)
    unscored = _make_matchup(
        db, home, away, start_time=datetime(2026, 1, 2)
    )
    db.add(PlayerGameStats(player_id=player.id, game_id=tied.id, points=1))
    db.add(PlayerGameStats(player_id=player.id, game_id=unscored.id, points=2))
    db.flush()

    unscored_row, tied_row = players_service.get_player_game_log(db, player)

    assert tied_row.result == "T"
    assert unscored_row.result is None


def test_game_log_has_no_opponent_for_a_game_the_players_team_did_not_play(db):
    home = _make_team(db, name="Home Team", abbreviation="HOM")
    away = _make_team(db, name="Away Team", abbreviation="AWY")
    other = _make_team(db, name="Other Team", abbreviation="OTH")
    player = _make_player(db, other)
    game = _make_matchup(db, home, away, home_score=100, away_score=90)
    db.add(PlayerGameStats(player_id=player.id, game_id=game.id, points=9))
    db.flush()

    (row,) = players_service.get_player_game_log(db, player)

    assert row.opponent is None
    assert row.is_home is None
    assert row.result is None


def test_get_next_game_returns_earliest_upcoming_game_with_opponent(db):
    team = _make_team(db, name="Mine", abbreviation="MNE")
    rival = _make_team(db, name="Rival", abbreviation="RIV")
    third = _make_team(db, name="Third", abbreviation="THR")
    player = _make_player(db, team)
    now = datetime(2026, 3, 1, 12)
    _make_matchup(db, team, rival, home_score=1, away_score=0, start_time=datetime(2026, 2, 1))
    later = _make_matchup(db, third, team, start_time=datetime(2026, 3, 9))
    sooner = _make_matchup(db, team, rival, start_time=datetime(2026, 3, 5))
    _make_matchup(db, rival, third, start_time=datetime(2026, 3, 2))  # not their team

    result = players_service.get_next_game(db, player, now=now)

    assert result is not None
    game, opponent, is_home = result
    assert game.id == sooner.id != later.id
    assert opponent.abbreviation == "RIV"
    assert is_home is True


def test_get_next_game_reports_away_when_player_team_is_visitor(db):
    team = _make_team(db, name="Mine", abbreviation="MNE")
    rival = _make_team(db, name="Rival", abbreviation="RIV")
    player = _make_player(db, team)
    _make_matchup(db, rival, team, start_time=datetime(2026, 3, 5))

    _, opponent, is_home = players_service.get_next_game(
        db, player, now=datetime(2026, 3, 1)
    )

    assert opponent.abbreviation == "RIV"
    assert is_home is False


def test_get_next_game_counts_an_in_progress_game(db):
    team = _make_team(db, name="Mine", abbreviation="MNE")
    rival = _make_team(db, name="Rival", abbreviation="RIV")
    player = _make_player(db, team)
    live = _make_matchup(db, team, rival, start_time=datetime(2026, 3, 1, 10))
    live.status = "in_progress"
    db.flush()

    result = players_service.get_next_game(db, player, now=datetime(2026, 3, 1, 11))

    assert result is not None and result[0].id == live.id


def test_get_next_game_is_none_without_a_team_or_upcoming_game(db):
    team = _make_team(db, name="Mine", abbreviation="MNE")
    rival = _make_team(db, name="Rival", abbreviation="RIV")
    _make_matchup(db, team, rival, home_score=3, away_score=2)
    with_team = _make_player(db, team)
    no_team = Player(name="Free Agent", sport="NBA")
    db.add(no_team)
    db.flush()

    assert players_service.get_next_game(db, with_team, now=datetime(2026, 3, 1)) is None
    assert players_service.get_next_game(db, no_team) is None


def test_list_players_includes_team(db):
    team = _make_team(db, name="Listed Team", abbreviation="LST")
    _make_player(db, team, name="Has Team")

    players, _ = players_service.list_players(db, search="Has Team")

    assert players[0].team.abbreviation == "LST"


def test_list_players_filters_by_any_of_the_given_positions(db):
    team = _make_team(db, sport="NFL")
    for name, position in [("Quarterback", "QB"), ("Runner", "RB"), ("Receiver", "WR"),
                           ("Tight", "TE"), ("Kicker", "PK")]:
        _make_player(db, team, sport="NFL", name=name, position=position)

    flex, total = players_service.list_players(db, positions=["RB", "WR", "TE"])
    only_qb, _ = players_service.list_players(db, positions=["QB"])
    everyone, _ = players_service.list_players(db)

    assert {p.name for p in flex} == {"Runner", "Receiver", "Tight"}
    assert total == 3
    assert [p.name for p in only_qb] == ["Quarterback"]
    assert len(everyone) == 5


def test_list_players_position_filter_combines_with_search_and_sport(db):
    team = _make_team(db, sport="NFL")
    _make_player(db, team, sport="NFL", name="Sam Runner", position="RB")
    _make_player(db, team, sport="NFL", name="Sam Receiver", position="WR")
    nba_team = _make_team(db, sport="NBA", abbreviation="NBA1")
    _make_player(db, nba_team, sport="NBA", name="Sam Guard", position="RB")

    players, _ = players_service.list_players(
        db, sport="NFL", search="Sam", positions=["RB"]
    )

    assert [p.name for p in players] == ["Sam Runner"]


def _season_game(db, home, away, when, *, season="2026", week=None, home_score=None,
                 away_score=None, status=None):
    game = Game(
        sport=home.sport, season=season, home_team_id=home.id, away_team_id=away.id,
        start_time=when, week=week, home_score=home_score, away_score=away_score,
        status=status or ("final" if home_score is not None else "scheduled"),
    )
    db.add(game)
    db.flush()
    return game


def test_schedule_lists_played_and_upcoming_games_in_date_order_from_the_teams_side(db):
    me = _make_team(db, sport="NFL", name="Mine", abbreviation="MNE")
    rival = _make_team(db, sport="NFL", name="Rival", abbreviation="RIV")
    player = _make_player(db, me, sport="NFL")
    later = _season_game(db, rival, me, datetime(2999, 10, 4), week=4)
    played = _season_game(db, me, rival, datetime(2026, 9, 6), week=1,
                          home_score=24, away_score=17)
    soon = _season_game(db, me, rival, datetime(2999, 9, 27), week=3)

    schedule = players_service.get_player_schedule(db, player)

    assert [m.game.id for m in schedule] == [played.id, soon.id, later.id]
    assert (schedule[0].result, schedule[0].team_score, schedule[0].opponent_score) == ("W", 24, 17)
    assert schedule[0].is_home is True
    assert schedule[1].result is None
    assert schedule[2].is_home is False
    assert schedule[2].opponent.abbreviation == "RIV"


def test_schedule_stops_at_the_last_fantasy_week_for_the_nfl(db):
    me = _make_team(db, sport="NFL", name="Mine", abbreviation="MNE")
    rival = _make_team(db, sport="NFL", name="Rival", abbreviation="RIV")
    player = _make_player(db, me, sport="NFL")
    for week in (16, 17, 18):
        _season_game(db, me, rival, datetime(2999, 12, week), week=week)

    schedule = players_service.get_player_schedule(db, player)

    assert [m.game.week for m in schedule] == [16, 17]


def test_schedule_does_not_cap_nba_games_that_have_no_week(db):
    me = _make_team(db, sport="NBA", name="Mine", abbreviation="MNE")
    rival = _make_team(db, sport="NBA", name="Rival", abbreviation="RIV")
    player = _make_player(db, me, sport="NBA")
    for day in range(1, 26):
        _season_game(db, me, rival, datetime(2999, 1, day), season="2026-27")

    assert len(players_service.get_player_schedule(db, player)) == 25


def test_schedule_only_covers_the_current_season(db):
    me = _make_team(db, sport="NBA", name="Mine", abbreviation="MNE")
    rival = _make_team(db, sport="NBA", name="Rival", abbreviation="RIV")
    player = _make_player(db, me, sport="NBA")
    _season_game(db, me, rival, datetime(2025, 3, 1), season="2024-25",
                 home_score=100, away_score=90)
    current = _season_game(db, me, rival, datetime(2999, 10, 22), season="2026-27")

    schedule = players_service.get_player_schedule(db, player)

    assert [m.game.id for m in schedule] == [current.id]


def test_schedule_falls_back_to_the_latest_season_once_it_has_no_upcoming_games(db):
    me = _make_team(db, sport="NBA", name="Mine", abbreviation="MNE")
    rival = _make_team(db, sport="NBA", name="Rival", abbreviation="RIV")
    player = _make_player(db, me, sport="NBA")
    _season_game(db, me, rival, datetime(2024, 3, 1), season="2023-24",
                 home_score=1, away_score=2)
    latest = _season_game(db, me, rival, datetime(2025, 3, 1), season="2024-25",
                          home_score=3, away_score=2)

    schedule = players_service.get_player_schedule(db, player)

    assert [m.game.id for m in schedule] == [latest.id]


def test_schedule_is_empty_for_a_player_without_a_team_or_games(db):
    me = _make_team(db, sport="NBA", name="Mine", abbreviation="MNE")
    no_team = Player(name="Free Agent", sport="NBA")
    db.add(no_team)
    db.flush()

    assert players_service.get_player_schedule(db, no_team) == []
    assert players_service.get_player_schedule(db, _make_player(db, me)) == []


def _stat_line(db, player, when, *, season="2026", **stats):
    game = Game(
        sport=player.sport, season=season, home_team_id=player.team_id,
        away_team_id=player.team_id, start_time=when, status="final",
    )
    db.add(game)
    db.flush()
    model = PlayerGameStatsNFL if player.sport == "NFL" else PlayerGameStats
    db.add(model(player_id=player.id, game_id=game.id, **stats))
    db.flush()


def test_list_players_sorts_by_season_fantasy_points_most_first(db):
    team = _make_team(db, sport="NFL")
    low = _make_player(db, team, sport="NFL", name="Low Scorer", position="WR")
    high = _make_player(db, team, sport="NFL", name="High Scorer", position="WR")
    mid = _make_player(db, team, sport="NFL", name="Mid Scorer", position="WR")
    _stat_line(db, low, datetime(2026, 9, 6), receptions=1, receiving_yards=10)      # 2
    _stat_line(db, high, datetime(2026, 9, 6), receptions=8, receiving_yards=120)    # 20
    _stat_line(db, mid, datetime(2026, 9, 6), receptions=4, receiving_yards=60)      # 10

    players, _ = players_service.list_players(db, sport="NFL", search="Scorer",
                                              sort="fantasy_points")

    assert [p.name for p in players] == ["High Scorer", "Mid Scorer", "Low Scorer"]


def test_fantasy_points_sum_over_every_game_in_the_season(db):
    team = _make_team(db, sport="NFL")
    steady = _make_player(db, team, sport="NFL", name="Steady", position="RB")
    spike = _make_player(db, team, sport="NFL", name="Spike", position="RB")
    for week in range(3):
        _stat_line(db, steady, datetime(2026, 9, 6 + week), rushing_yards=50)   # 5 each = 15
    _stat_line(db, spike, datetime(2026, 9, 6), rushing_yards=100)              # 10

    players, _ = players_service.list_players(db, sport="NFL", positions=["RB"],
                                              sort="fantasy_points")

    assert [p.name for p in players][:2] == ["Steady", "Spike"]
    points = players_service.get_season_fantasy_points(db, players)
    assert points[steady.id] == 15
    assert points[spike.id] == 10


def test_fantasy_points_only_count_the_latest_season_with_stats(db):
    team = _make_team(db, sport="NBA")
    veteran = _make_player(db, team, name="Last Year's Star")
    newcomer = _make_player(db, team, name="This Year's Hot Hand")
    _stat_line(db, veteran, datetime(2025, 3, 1), season="2024-25", points=50)
    _stat_line(db, newcomer, datetime(2026, 3, 1), season="2025-26", points=20)

    players, _ = players_service.list_players(db, sport="NBA", sort="fantasy_points")

    names = [p.name for p in players]
    assert names.index("This Year's Hot Hand") < names.index("Last Year's Star")
    points = players_service.get_season_fantasy_points(db, players)
    assert newcomer.id in points
    assert veteran.id not in points  # nothing in the latest season


def test_players_without_stats_come_last_in_name_order(db):
    team = _make_team(db, sport="NFL")
    scorer = _make_player(db, team, sport="NFL", name="ZZ Scorer", position="TE")
    _make_player(db, team, sport="NFL", name="ZZ Benchwarmer B", position="TE")
    _make_player(db, team, sport="NFL", name="ZZ Benchwarmer A", position="TE")
    _stat_line(db, scorer, datetime(2026, 9, 6), receptions=2)

    players, _ = players_service.list_players(db, sport="NFL", search="ZZ", sort="fantasy_points")

    assert [p.name for p in players] == ["ZZ Scorer", "ZZ Benchwarmer A", "ZZ Benchwarmer B"]


def test_fantasy_points_sort_composes_with_position_search_and_paging(db):
    team = _make_team(db, sport="NFL")
    receivers = [
        _make_player(db, team, sport="NFL", name=f"Flex {i}", position="WR") for i in range(5)
    ]
    for index, player in enumerate(receivers):
        _stat_line(db, player, datetime(2026, 9, 6), receptions=index + 1)
    qb = _make_player(db, team, sport="NFL", name="Flex QB", position="QB")
    _stat_line(db, qb, datetime(2026, 9, 6), passing_yards=500)

    first, total = players_service.list_players(
        db, sport="NFL", positions=["WR"], search="Flex", sort="fantasy_points", limit=2
    )
    second, _ = players_service.list_players(
        db, sport="NFL", positions=["WR"], search="Flex", sort="fantasy_points", limit=2, offset=2
    )

    assert total == 5  # the quarterback is filtered out
    assert [p.name for p in first] == ["Flex 4", "Flex 3"]
    assert [p.name for p in second] == ["Flex 2", "Flex 1"]


def test_sorting_by_fantasy_points_needs_a_sport(db):
    with pytest.raises(ValueError):
        players_service.list_players(db, sort="fantasy_points")


def test_season_points_are_empty_for_no_players(db):
    assert players_service.get_season_fantasy_points(db, []) == {}
