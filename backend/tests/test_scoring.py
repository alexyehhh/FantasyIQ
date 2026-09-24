"""Fantasy scoring: the config, the Python scorer, and the SQL scorer that ranks seasons.

The first group is pinned to the same worked examples as the frontend's lib/scoring.test.ts
(which still carries its own copy of the default weights).
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.db.models import (
    FieldGoalKick,
    Game,
    Player,
    PlayerGameStatsNFL,
    Team,
)
from app.db.session import SessionLocal
from app.services import players as players_service
from app.services.scoring import (
    Bracket,
    ScoringConfig,
    bracket_points,
    default_config,
    kick_points,
    score_defense_game,
    score_player_game,
)

NBA = default_config("NBA")
NFL = default_config("NFL")


def test_scores_an_nba_stat_line_with_the_default_weights():
    stats = {"points": 30, "rebounds": 10, "assists": 5, "steals": 2, "blocks": 1, "turnovers": 3}

    # 30 + 12 + 7.5 + 6 + 3 - 3
    assert score_player_game(NBA, stats) == 55.5


def test_scores_an_nfl_stat_line_with_ppr_weights():
    stats = {
        "passing_yards": 300,
        "passing_touchdowns": 2,
        "interceptions": 1,
        "rushing_yards": 20,
        "receptions": 1,
        "receiving_yards": 10,
    }

    # 12 + 8 - 2 + 2 + 1 + 1
    assert score_player_game(NFL, stats) == 22


def test_missing_and_unweighted_stats_count_for_nothing():
    assert score_player_game(NBA, {"points": 10, "minutes": 40}) == 10


def test_rounds_to_a_tenth():
    assert score_player_game(NFL, {"rushing_yards": 17}) == 1.7
    assert score_player_game(NFL, {"passing_yards": 251}) == 10


def test_return_touchdowns_score_for_the_returner():
    assert score_player_game(NFL, {"kick_return_touchdowns": 1, "punt_return_touchdowns": 1}) == 12


# --- Kickers: distance brackets, misses, extra points ---------------------------------------


def test_field_goals_are_scored_by_the_bracket_their_distance_falls_in():
    made = lambda distance: kick_points(NFL, [(distance, "made")])  # noqa: E731

    assert [made(d) for d in (19, 20, 39, 40, 49, 50, 63)] == [3, 3, 3, 4, 4, 5, 5]


def test_missed_and_blocked_field_goals_cost_points_by_distance():
    missed = lambda distance: kick_points(NFL, [(distance, "missed")])  # noqa: E731

    assert [missed(d) for d in (19, 39, 40, 49, 50, 60)] == [-3, -3, -2, -2, -1, -1]
    assert kick_points(NFL, [(45, "blocked")]) == -2


def test_a_kickers_game_combines_kicks_and_extra_points():
    kicks = [(24, "made"), (52, "made"), (43, "missed")]
    stats = {"extra_points_made": 3, "extra_point_attempts": 3}

    # 3 + 5 - 2 from the kicks, +3 for the extra points
    assert score_player_game(NFL, stats, kicks) == 9


def test_a_missed_extra_point_is_attempts_minus_makes():
    stats = {"extra_points_made": 2, "extra_point_attempts": 3}

    assert score_player_game(NFL, stats) == 1  # +2 for the makes, -1 for the miss


def test_a_league_without_distance_brackets_scores_the_same_kicks_flat():
    flat = ScoringConfig(
        name="Flat kicker",
        sport="NFL",
        player_weights={"field_goals_made": 3, "field_goals_missed": -1, "extra_points_made": 1},
    )
    stats = {
        "field_goals_made": 2,
        "field_goal_attempts": 3,
        "extra_points_made": 3,
        "extra_point_attempts": 3,
    }
    kicks = [(24, "made"), (52, "made"), (43, "missed")]

    assert score_player_game(flat, stats, kicks) == 8  # 6 - 1 + 3; distance doesn't matter
    assert score_player_game(NFL, {"extra_points_made": 3, "extra_point_attempts": 3}, kicks) == 9


# --- Team defense: weights and points-allowed brackets --------------------------------------


def test_points_allowed_brackets_score_every_boundary():
    points = lambda allowed: bracket_points(NFL.points_allowed, allowed)  # noqa: E731

    assert [points(p) for p in (0, 1, 6, 7, 13, 14, 20, 21, 27, 28, 34, 35, 70)] == [
        10, 7, 7, 4, 4, 1, 1, 0, 0, -1, -1, -4, -4,
    ]


def test_scores_a_team_defense_game():
    line = {
        "sacks": 3,
        "interceptions": 1,
        "fumble_recoveries": 1,
        "defensive_touchdowns": 1,
        "blocked_kicks": 1,
        "fourth_down_stops": 1,
        "points_allowed": 7,
    }

    # 3 sacks + 2 + 2 + 6 + 2 + 1 = 16, plus 4 for 7 points allowed
    assert score_defense_game(NFL, line) == 20


def test_a_shutout_with_a_safety_and_a_return_touchdown():
    line = {"safeties": 1, "return_touchdowns": 1, "points_allowed": 0}

    assert score_defense_game(NFL, line) == 2 + 6 + 10


def test_a_defense_stat_and_a_player_stat_of_the_same_name_are_scored_separately():
    # A quarterback's interceptions cost him 2; a defense's interceptions earn it 2.
    assert score_player_game(NFL, {"interceptions": 1}) == -2
    assert score_defense_game(NFL, {"interceptions": 1, "points_allowed": 21}) == 2


# --- Config validation -----------------------------------------------------------------------


def test_the_default_configs_are_valid_and_named():
    assert NBA.name == "FantasyIQ standard"
    assert NFL.field_goal_made and NFL.points_allowed


def test_an_unknown_stat_name_is_rejected():
    with pytest.raises(ValidationError, match="unknown NBA player stats"):
        ScoringConfig(name="Typo", sport="NBA", player_weights={"pointz": 1})
    with pytest.raises(ValidationError, match="unknown defense stats"):
        ScoringConfig(name="Typo", sport="NFL", defense_weights={"sacksz": 1})


def test_a_stat_from_the_other_sport_is_rejected():
    with pytest.raises(ValidationError, match="unknown NFL player stats"):
        ScoringConfig(name="Wrong", sport="NFL", player_weights={"rebounds": 1})


def test_kicker_and_defense_scoring_is_nfl_only():
    with pytest.raises(ValidationError, match="NFL only"):
        ScoringConfig(name="Wrong", sport="NBA", points_allowed=(Bracket(min=0, points=1),))


def test_overlapping_brackets_are_rejected():
    with pytest.raises(ValidationError, match="overlap"):
        ScoringConfig(
            name="Overlap",
            sport="NFL",
            points_allowed=(Bracket(min=0, max=10, points=5), Bracket(min=10, max=20, points=1)),
        )
    with pytest.raises(ValidationError, match="overlap"):
        ScoringConfig(
            name="Open ended twice",
            sport="NFL",
            points_allowed=(Bracket(min=0, points=5), Bracket(min=20, points=1)),
        )


def test_a_backwards_bracket_is_rejected():
    with pytest.raises(ValidationError, match="above its maximum"):
        Bracket(min=20, max=10, points=1)


def test_brackets_with_gaps_score_nothing_in_the_gap():
    config = ScoringConfig(
        name="Gappy",
        sport="NFL",
        points_allowed=(Bracket(min=0, max=6, points=7), Bracket(min=14, points=1)),
    )

    assert [score_defense_game(config, {"points_allowed": p}) for p in (3, 10, 20)] == [7, 0, 1]


def test_an_unexpected_field_is_rejected():
    with pytest.raises(ValidationError):
        ScoringConfig(name="Extra", sport="NBA", bonus=1)


# --- SQL ranking agrees with the Python scorer -----------------------------------------------


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _season(db):
    team = Team(name="Team", abbreviation="TST", sport="NFL")
    db.add(team)
    db.flush()
    games = []
    for week in (1, 2):
        game = Game(
            sport="NFL",
            season="2026",
            home_team_id=team.id,
            away_team_id=team.id,
            start_time=datetime(2026, 9, 10 + 7 * week, tzinfo=timezone.utc),
            status="final",
            week=week,
        )
        db.add(game)
        games.append(game)
    db.flush()
    return team, games


def _kicker(db, team, games, name, kicks_by_game, made, attempts):
    player = Player(name=name, sport="NFL", position="PK", team_id=team.id)
    db.add(player)
    db.flush()
    for game, kicks in zip(games, kicks_by_game, strict=True):
        db.add(
            PlayerGameStatsNFL(
                player_id=player.id,
                game_id=game.id,
                field_goals_made=sum(result == "made" for _, result in kicks),
                field_goal_attempts=len(kicks),
                extra_points_made=made,
                extra_point_attempts=attempts,
            )
        )
        for index, (distance, result) in enumerate(kicks):
            db.add(
                FieldGoalKick(
                    player_id=player.id,
                    game_id=game.id,
                    external_play_id=f"{name}-{game.week}-{index}",
                    distance=distance,
                    result=result,
                )
            )
    db.flush()
    return player


_LONG_RANGE = [[(55, "made"), (48, "made")], [(52, "made"), (33, "missed")]]
_SHORT_RANGE = [[(22, "made"), (28, "made"), (31, "made")], [(20, "made")]]


def _python_season_points(config, kicks_by_game, made, attempts):
    return round(
        sum(
            score_player_game(
                config, {"extra_points_made": made, "extra_point_attempts": attempts}, kicks
            )
            for kicks in kicks_by_game
        ),
        1,
    )


def test_ranking_scores_kickers_by_distance_exactly_like_the_python_scorer(db):
    team, games = _season(db)
    long_kicker = _kicker(db, team, games, "Long", _LONG_RANGE, made=3, attempts=4)
    short_kicker = _kicker(db, team, games, "Short", _SHORT_RANGE, made=2, attempts=2)

    points = players_service.get_season_fantasy_points(db, [long_kicker, short_kicker])

    # Long: (5 + 4 + 2 for extra points) + (5 - 3 + 2) = 15. Short: (9 + 2) + (3 + 2) = 16.
    assert points[long_kicker.id] == _python_season_points(NFL, _LONG_RANGE, 3, 4) == 15
    assert points[short_kicker.id] == _python_season_points(NFL, _SHORT_RANGE, 2, 2) == 16
    ranked, _ = players_service.list_players(
        db, sport="NFL", positions=["PK"], sort="fantasy_points"
    )
    assert [p.name for p in ranked] == ["Short", "Long"]


def test_ranking_under_a_custom_config_changes_the_points_and_the_order(db):
    team, games = _season(db)
    long_kicker = _kicker(db, team, games, "Long", _LONG_RANGE, made=3, attempts=4)
    short_kicker = _kicker(db, team, games, "Short", _SHORT_RANGE, made=2, attempts=2)
    only_long_ones = ScoringConfig(
        name="Only 50+ yard field goals count",
        sport="NFL",
        field_goal_made=(Bracket(min=50, points=10),),
    )

    points = players_service.get_season_fantasy_points(
        db, [long_kicker, short_kicker], scoring=only_long_ones
    )
    ranked, _ = players_service.list_players(
        db, sport="NFL", positions=["PK"], sort="fantasy_points", scoring=only_long_ones
    )

    assert (points[long_kicker.id], points[short_kicker.id]) == (20, 0)  # the 55 and 52
    assert [p.name for p in ranked] == ["Long", "Short"]  # the default order, reversed


def test_a_config_for_the_wrong_sport_cannot_rank_players(db):
    with pytest.raises(ValueError, match="can't rank"):
        players_service.list_players(db, sport="NFL", sort="fantasy_points", scoring=NBA)
