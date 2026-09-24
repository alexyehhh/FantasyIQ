"""The default scoring weights, pinned to the same worked examples as the frontend's
lib/scoring.test.ts so the two copies of the weights can't drift apart."""

from app.services.scoring import DEFAULT_SCORING, fantasy_points


def test_scores_an_nba_stat_line_with_the_default_weights():
    stats = {"points": 30, "rebounds": 10, "assists": 5, "steals": 2, "blocks": 1, "turnovers": 3}

    # 30 + 12 + 7.5 + 6 + 3 - 3
    assert fantasy_points("NBA", stats) == 55.5


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
    assert fantasy_points("NFL", stats) == 22


def test_missing_and_unweighted_stats_count_for_nothing():
    assert fantasy_points("NBA", {"points": 10, "minutes": 40}) == 10


def test_rounds_to_a_tenth():
    assert fantasy_points("NFL", {"rushing_yards": 17}) == 1.7
    assert fantasy_points("NFL", {"passing_yards": 251}) == 10


def test_every_weighted_stat_is_a_real_stats_column():
    from app.db.models import PlayerGameStats, PlayerGameStatsNFL

    for sport, model in (("NBA", PlayerGameStats), ("NFL", PlayerGameStatsNFL)):
        assert set(DEFAULT_SCORING[sport]) <= set(model.__table__.columns.keys())
