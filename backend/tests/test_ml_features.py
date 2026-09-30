"""Features must never see the game they describe or anything after it."""

import numpy as np
import pandas as pd

from app.ml.features import MIN_PRIOR_GAMES, build_features, usable

STATS = ("points", "rebounds")


def _history(n: int = 12) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    rows = []
    for player_id in (1, 2):
        for game in range(n):
            rows.append(
                {
                    "player_id": player_id,
                    "start_time": pd.Timestamp("2025-01-01") + pd.Timedelta(days=2 * game),
                    "position": "G",
                    "is_home": float(game % 2),
                    "points": float(rng.integers(0, 40)),
                    "rebounds": float(rng.integers(0, 15)),
                }
            )
    return pd.DataFrame(rows).sort_values(["player_id", "start_time"]).reset_index(drop=True)


def test_features_ignore_the_row_itself_and_everything_after():
    frame = _history()
    base = build_features(frame, STATS)
    changed = frame.copy()
    # Rewrite player 1's game 7 and everything after it: rows up to 7 must not move.
    mask = (changed["player_id"] == 1) & (changed["start_time"] >= frame["start_time"].iloc[7])
    changed.loc[mask, list(STATS)] += 1000
    altered = build_features(changed, STATS)
    cutoff = frame["start_time"].iloc[7]
    through_game_7 = (frame["player_id"] == 1) & (frame["start_time"] <= cutoff)
    feature_columns = [c for c in base.columns if "__" in c]
    pd.testing.assert_frame_equal(
        base.loc[through_game_7, feature_columns], altered.loc[through_game_7, feature_columns]
    )
    # ...and the next game does see it.
    assert not base.loc[8, feature_columns].equals(altered.loc[8, feature_columns])


def test_a_players_features_do_not_depend_on_other_players():
    frame = _history()
    alone = build_features(frame[frame["player_id"] == 1].reset_index(drop=True), STATS)
    together = build_features(frame, STATS)
    columns = [c for c in alone.columns if "__" in c]
    pd.testing.assert_frame_equal(
        alone[columns], together[together["player_id"] == 1].reset_index(drop=True)[columns]
    )


def test_a_target_row_with_no_result_gets_features_from_history_only():
    history = _history()
    target = pd.DataFrame(
        [{"player_id": 1, "start_time": pd.Timestamp("2025-03-01"), "position": "G",
          "is_home": 1.0, "points": np.nan, "rebounds": np.nan}]
    )  # fmt: skip
    stacked = pd.concat([history, target]).sort_values(["player_id", "start_time"])
    features = build_features(stacked.reset_index(drop=True), STATS)
    row = features[features["start_time"] == pd.Timestamp("2025-03-01")].iloc[0]
    last_three = history[history["player_id"] == 1]["points"].tail(3).mean()
    assert row["points__m3"] == last_three
    assert row["n_prior"] == 12


def test_first_games_are_not_usable():
    features = build_features(_history(), STATS)
    first = features.groupby("player_id").cumcount()
    assert not usable(features)[first < MIN_PRIOR_GAMES].any()
    assert usable(features)[first >= MIN_PRIOR_GAMES].all()
