import numpy as np
import pandas as pd
import pytest

from app.ml import evaluate, model
from app.ml.dataset import STATS
from app.ml.features import build_features, usable
from app.services.scoring import default_config


def _nba_history() -> pd.DataFrame:
    rng = np.random.default_rng(1)
    rows = []
    for player_id in range(1, 31):
        skill = rng.uniform(5, 30)
        for game in range(25):
            minutes = float(rng.uniform(15, 38))
            rows.append(
                {
                    "player_id": player_id,
                    "start_time": pd.Timestamp("2025-01-01") + pd.Timedelta(days=2 * game),
                    "position": "G" if player_id % 2 else "F",
                    "is_home": float(game % 2),
                    "minutes": minutes,
                    **{
                        stat: float(rng.poisson(skill * minutes / 36 / 3))
                        for stat in STATS["NBA"]
                        if stat != "minutes"
                    },
                }
            )
    return pd.DataFrame(rows).sort_values(["player_id", "start_time"]).reset_index(drop=True)


def test_train_predict_save_load_round_trip(tmp_path):
    features = build_features(_nba_history(), STATS["NBA"])
    ready = features[usable(features)]
    trained = model.SportModel("NBA", model.train("NBA", ready), "2025-03-01", len(ready))
    predicted = trained.predict(ready)
    assert list(predicted.columns) == list(STATS["NBA"])
    assert len(predicted) == len(ready)
    assert (predicted.drop(columns="minutes") >= 0).all().all()

    model.save(trained, tmp_path)
    reloaded = model.load("NBA", tmp_path)
    assert reloaded is not None
    pd.testing.assert_frame_equal(reloaded.predict(ready), predicted)
    assert model.load("NFL", tmp_path) is None


def test_compare_scores_a_perfect_prediction_with_zero_error():
    config = default_config("NBA")
    test = _nba_history().head(50).assign(start_time=lambda d: d["start_time"].dt.date)
    stats = STATS["NBA"]
    table = evaluate.compare(config, test, {"perfect": test[list(stats)]}, stats, "start_time")
    overall = table[table["position"] == "ALL"].iloc[0]
    assert overall["mae"] == 0
    assert overall["bias"] == 0
    assert overall["rows"] == 50


def test_split_by_time_never_mixes_the_periods():
    frame = _nba_history()
    cutoff = pd.Timestamp("2025-01-25")
    before, after = evaluate.split_by_time(frame, cutoff)
    assert frame[before]["start_time"].max() < cutoff <= frame[after]["start_time"].min()


def _features(ewm, gap):
    return pd.DataFrame({"rushing_attempts__ewm": ewm, "top_gap__rushing_attempts": gap})


def test_a_first_choice_backup_is_raised_towards_the_starters_workload(monkeypatch):
    monkeypatch.setattr(model.get_settings(), "projection_first_choice_share", 0.9)
    nfl = model.SportModel("NFL", {}, "2026-01-01", 0)
    lines = pd.DataFrame(
        {"rushing_attempts": [8.0, 8.0], "rushing_yards": [32.0, 32.0], "receptions": [2.0, 2.0]}
    )

    filled = nfl._fill_the_starters_role(lines, _features([6.0, 6.0], [9.0, 0.0]))

    # 6 + 0.9 * 9 = 14.1 carries; the yards move with the carries, receptions are left alone.
    assert filled.loc[0, "rushing_attempts"] == pytest.approx(14.1)
    assert filled.loc[0, "rushing_yards"] == pytest.approx(32 * 14.1 / 8)
    assert filled.loc[0, "receptions"] == 2.0
    assert filled.loc[1].to_dict() == lines.loc[1].to_dict()  # no gap: unchanged


def test_the_raise_never_lowers_a_projection_and_can_be_turned_off(monkeypatch):
    nfl = model.SportModel("NFL", {}, "2026-01-01", 0)
    lines = pd.DataFrame({"rushing_attempts": [15.0], "rushing_yards": [60.0]})

    monkeypatch.setattr(model.get_settings(), "projection_first_choice_share", 0.9)
    assert nfl._fill_the_starters_role(lines, _features([6.0], [9.0])).equals(lines)  # 14.1 < 15

    monkeypatch.setattr(model.get_settings(), "projection_first_choice_share", 0.0)
    assert nfl._fill_the_starters_role(lines, _features([1.0], [20.0])).equals(lines)


def test_the_nba_is_left_to_the_model(monkeypatch):
    monkeypatch.setattr(model.get_settings(), "projection_first_choice_share", 1.0)
    nba = model.SportModel("NBA", {}, "2026-01-01", 0)
    lines = pd.DataFrame({"rushing_attempts": [8.0]})

    assert nba._fill_the_starters_role(lines, _features([6.0], [9.0])).equals(lines)
