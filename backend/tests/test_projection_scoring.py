"""Scoring an expected stat line (no database)."""

import pytest

from app.services.projections.base import KickBucket
from app.services.projections.expected_scoring import (
    expected_bracket_points,
    expected_kick_points,
    score_expected_defense,
    score_expected_player,
)
from app.services.scoring import Bracket, ScoringConfig, default_config

NFL = default_config("NFL")


def test_a_bracket_covering_everything_is_worth_its_points_whatever_the_average():
    everything = [Bracket(min=0, points=2)]
    assert expected_bracket_points(everything, 3) == pytest.approx(2)
    assert expected_bracket_points(everything, 40) == pytest.approx(2)


def test_points_allowed_spreads_over_brackets_instead_of_using_the_average():
    brackets = NFL.points_allowed
    # 17.5 sits inside the 14-20 bracket (1 point) but that is not what the defense is expected to
    # score: shutouts and low games are worth much more, big games cost points.
    expected = expected_bracket_points(brackets, 17.5)
    assert expected != pytest.approx(1, abs=0.1)
    # and a better defense is expected to score more, monotonically
    assert (
        expected_bracket_points(brackets, 10)
        > expected
        > expected_bracket_points(brackets, 24)
        > expected_bracket_points(brackets, 32)
    )


def test_a_kick_bucket_inside_one_bracket_scores_exactly():
    # Default brackets: 0-39 = 3, 40-49 = 4, 50+ = 5; misses -3 / -2 / -1.
    scored = expected_kick_points(NFL, [KickBucket(40, 49, made=1.5, missed=0.5)])
    assert scored.points == pytest.approx(1.5 * 4 + 0.5 * -2)
    assert not scored.approximate


def test_a_kick_bucket_straddling_a_bracket_boundary_is_flagged_as_approximate():
    scored = expected_kick_points(NFL, [KickBucket(30, 49, made=1, missed=0)])
    # half its distances are worth 3 and half 4
    assert scored.points == pytest.approx(3.5)
    assert scored.approximate


def test_a_league_with_no_kicker_brackets_gets_nothing_from_kicks():
    config = ScoringConfig(name="No distance", sport="NFL", player_weights={"field_goals_made": 3})
    scored = score_expected_player(
        config, {"field_goals_made": 2}, [KickBucket(40, 49, made=2, missed=0)]
    )
    assert scored.points == 6
    assert not scored.approximate


def test_a_player_stat_line_is_scored_under_the_leagues_weights_including_derived_misses():
    config = ScoringConfig(
        name="Custom",
        sport="NFL",
        player_weights={"passing_yards": 0.05, "passing_incompletions": -0.5, "receptions": 0.5},
    )
    stats = {"passing_yards": 300, "passing_attempts": 40, "passing_completions": 28}
    assert score_expected_player(config, stats).points == 15 - 6


def test_a_defense_line_is_scored_with_its_weights_and_expected_points_allowed_brackets():
    stats = {"sacks": 3, "interceptions": 1, "points_allowed": 17.5}
    scored = score_expected_defense(NFL, stats)
    bracket_part = expected_bracket_points(NFL.points_allowed, 17.5)
    assert scored.points == pytest.approx(3 * 1 + 1 * 2 + bracket_part, abs=0.05)
