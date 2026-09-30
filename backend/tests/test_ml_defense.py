"""The team defense model's features and data loading (real Postgres for the loader)."""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from app.db.models import Game, Team, TeamGameStatsNFL
from app.db.session import SessionLocal
from app.ml import defense


def _history(games: int = 8) -> pd.DataFrame:
    """Teams 1 and 2 play each other every week. Team 1's defense allows 10 and gets 3 sacks;
    team 2's allows 30 and gets 1, so team 1's offense scores 30 and team 2's scores 10."""
    rng = np.random.default_rng(0)
    rows = []
    for week in range(1, games + 1):
        start = pd.Timestamp("2026-09-01") + pd.Timedelta(days=7 * week)
        for team, opponent, home, sacks, allowed, scored in (
            (1, 2, 1, 3, 10, 30),
            (2, 1, 0, 1, 30, 10),
        ):
            rows.append(
                {
                    "team_id": team,
                    "opponent_id": opponent,
                    "game_id": week,
                    "start_time": start,
                    "season": "2026",
                    "week": float(week),
                    "is_home": home,
                    **{s: float(rng.integers(0, 3)) for s in defense.STATS},
                    "sacks": float(sacks),
                    "points_allowed": float(allowed),
                    "points_scored": float(scored),
                    "sacks_taken": float(3 if team == 2 else 1),
                    "giveaways": 1.0,
                }
            )
    return pd.DataFrame(rows).sort_values(["team_id", "start_time"]).reset_index(drop=True)


def test_features_use_only_earlier_games():
    frame = _history()
    base = defense.build_features(frame)
    changed = frame.copy()
    later = (changed["team_id"] == 1) & (changed["game_id"] >= 5)
    changed.loc[later, list(defense.STATS)] += 1000
    altered = defense.build_features(changed)

    columns = [c for c in base.columns if "__" in c]
    early = base["game_id"] <= 5  # game 5's own features see games 1-4 only
    pd.testing.assert_frame_equal(base.loc[early, columns], altered.loc[early, columns])
    assert not base.loc[base["game_id"] == 6, columns].equals(
        altered.loc[altered["game_id"] == 6, columns]
    )


def test_the_opponents_recent_offense_comes_from_their_own_earlier_games():
    features = defense.build_features(_history())

    team_1_game_5 = features[(features["team_id"] == 1) & (features["game_id"] == 5)].iloc[0]
    team_2_game_5 = features[(features["team_id"] == 2) & (features["game_id"] == 5)].iloc[0]

    # Team 2's offense has scored 10 every game, team 1's 30.
    assert team_1_game_5["opp_points_scored__ewm"] == pytest.approx(10)
    assert team_2_game_5["opp_points_scored__ewm"] == pytest.approx(30)
    assert team_1_game_5["opp_sacks_taken__ewm"] == pytest.approx(3)


def test_a_game_still_to_be_played_gets_features_from_history_alone():
    history = _history()
    games = pd.DataFrame(
        [
            {
                "game_id": 99,
                "start_time": pd.Timestamp("2026-12-01"),
                "season": "2026",
                "week": 13,
                "home_id": 1,
                "away_id": 2,
            }
        ]
    )
    stacked = pd.concat([history, defense.upcoming_rows(games)], ignore_index=True)
    stacked = stacked.sort_values(["team_id", "start_time"], kind="stable").reset_index(drop=True)

    features = defense.build_features(stacked)
    row = features[(features["game_id"] == 99) & (features["team_id"] == 1)].iloc[0]

    assert row["n_prior"] == 8 and row["is_home"] == 1
    assert row["sacks__ewm"] == pytest.approx(3)
    assert row["opp_points_scored__ewm"] == pytest.approx(10)


def test_the_model_predicts_non_negative_stat_lines_and_survives_a_save(tmp_path):
    rng = np.random.default_rng(1)
    frame = pd.concat([_history(10).assign(team_id=t, opponent_id=t % 4 + 1) for t in range(1, 5)])
    frame = frame.sort_values(["team_id", "start_time"])
    features = defense.build_features(frame.reset_index(drop=True))
    ready = features[defense.usable(features)].copy()
    for stat in defense.STATS:
        ready[stat] = rng.poisson(2, len(ready)).astype(float)

    model = defense.DefenseModel(defense.train(ready), "2026-10-01", len(ready))
    predicted = model.predict(ready)

    assert list(predicted.columns) == list(defense.STATS)
    assert (predicted >= 0).all().all()
    defense.save(model, tmp_path)
    reloaded = defense.load_cached(tmp_path)
    assert reloaded is not None
    pd.testing.assert_frame_equal(reloaded.predict(ready), predicted)
    assert defense.load_cached(tmp_path / "nowhere") is None


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def test_the_loader_pairs_each_defense_with_what_the_opponents_offense_did(db):
    alpha = Team(name="Alpha Aces", abbreviation="ALP", sport="NFL")
    bravo = Team(name="Bravo Bears", abbreviation="BRV", sport="NFL")
    db.add_all([alpha, bravo])
    db.flush()
    game = Game(
        sport="NFL", season="2026", home_team_id=alpha.id, away_team_id=bravo.id,
        start_time=datetime(2026, 9, 10) + timedelta(days=1), week=1, status="final",
        stats_final=True,
    )  # fmt: skip
    db.add(game)
    db.flush()
    db.add_all(
        [
            TeamGameStatsNFL(team_id=alpha.id, game_id=game.id, sacks=4, points_allowed=17,
                             interceptions=1, fumble_recoveries=2),
            TeamGameStatsNFL(team_id=bravo.id, game_id=game.id, sacks=2, points_allowed=24,
                             interceptions=3, fumble_recoveries=1),
        ]
    )  # fmt: skip
    db.flush()

    frame = defense.load_history(db.connection())
    mine = frame[frame["team_id"] == alpha.id].iloc[0]

    assert mine["opponent_id"] == bravo.id and mine["is_home"] == 1
    assert mine["points_scored"] == 24  # Bravo's points allowed is what Alpha's offense scored
    assert mine["sacks_taken"] == 2
    assert mine["giveaways"] == 4  # Bravo's 3 interceptions and 1 fumble recovery
