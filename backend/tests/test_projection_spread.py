"""The spread of a projection and the chance of scoring the most."""

import pytest

from app.services.projections.spread import chance_best, spread, typical_spread


def test_a_typical_spread_is_a_share_of_the_projection_by_position_with_a_floor():
    assert typical_spread("NFL", "QB", 20) == pytest.approx(7.0)
    assert typical_spread("NFL", "WR", 20) == pytest.approx(11.0)
    assert typical_spread("NFL", "PK", 2) == 2.0  # never below the floor
    assert typical_spread("NBA", "G", 40) == pytest.approx(12.0)
    assert typical_spread("NFL", "LB", 10) == pytest.approx(5.0)  # positions we have no share for


def test_a_spread_uses_the_position_alone_without_history():
    assert spread("NFL", "WR", 20, None, 2) == (11.0, "position")
    assert spread("NFL", "WR", 20, 4.0, 0) == (11.0, "position")


def test_history_takes_over_from_the_position_as_games_accumulate():
    few, _ = spread("NFL", "WR", 20, 4.0, 3)  # 3/7 history, 4/7 typical
    many, basis = spread("NFL", "WR", 20, 4.0, 40)
    assert basis == "blended"
    assert few == pytest.approx(3 / 7 * 4 + 4 / 7 * 11, abs=0.05)
    assert many < few and many == pytest.approx(40 / 44 * 4 + 4 / 44 * 11, abs=0.05)


def test_two_equal_players_have_an_even_chance_of_scoring_the_most():
    a, b = chance_best([15, 15], [6, 6])

    assert a == pytest.approx(0.5, abs=0.03) and a + b == pytest.approx(1)


def test_a_clearly_better_player_is_very_likely_to_score_the_most():
    ahead, behind = chance_best([30, 10], [4, 4])

    assert ahead > 0.99 and behind < 0.01


def test_a_wider_spread_helps_the_player_who_is_behind():
    tight_behind = chance_best([18, 16], [3, 3])[1]
    wide_behind = chance_best([18, 16], [3, 12])[1]

    assert wide_behind > tight_behind


def test_the_chances_are_repeatable():
    assert chance_best([20, 18, 15], [6, 8, 5]) == chance_best([20, 18, 15], [6, 8, 5])
