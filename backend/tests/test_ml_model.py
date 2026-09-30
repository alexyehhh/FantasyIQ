import numpy as np
import pandas as pd

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
