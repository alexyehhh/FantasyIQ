"""The scheduled retraining (app/ml/retrain.py): when a new model replaces the saved one, and how
it is written. Training itself is faked; the train CLIs' functions are exercised by hand."""

import os
from dataclasses import dataclass, field
from types import SimpleNamespace

import joblib
import pandas as pd
import pytest

from app.ml import model, retrain
from app.ml.retrain import MAX_SKILL, TOLERANCE, Target, decide, retrain_all, skill


def _held_out(model_mae: float, baseline_mae: float = 5.0) -> list[dict]:
    rows = [
        ("ALL", "model", model_mae),
        ("ALL", "recent_avg", baseline_mae),
        ("ALL", "last_3", 9.0),
        # A position's rows must not be mistaken for the overall ones.
        ("QB", "model", 1.0),
        ("QB", "recent_avg", 100.0),
    ]
    return [{"position": p, "method": m, "rows": 100, "mae": mae} for p, m, mae in rows]


@dataclass
class Fake:
    """Stands in for a SportModel or DefenseModel: all `decide` reads."""

    name: str
    n_rows: int = 1000
    metrics: dict = field(default_factory=dict)


def _fake(name: str, model_mae: float, n_rows: int = 1000) -> Fake:
    return Fake(name, n_rows, {"held_out": _held_out(model_mae)})


def test_skill_is_the_models_error_over_the_baselines_on_all_positions():
    assert skill(_held_out(4.5)) == 0.9
    # The defense table has no position column: every row is overall.
    defense_rows = [{"method": "model", "mae": 3.0}, {"method": "recent_avg", "mae": 4.0}]
    assert skill(defense_rows) == 0.75
    assert skill([{"method": "model", "mae": 3.0}]) is None
    assert skill(None) is None


def test_a_model_as_good_or_a_little_worse_than_the_saved_one_replaces_it():
    current = _fake("old", 4.5)  # skill 0.90

    assert decide(_fake("new", 4.4).metrics, 1000, current).replace is True
    within = 5.0 * (0.90 + TOLERANCE) - 0.001
    assert decide(_fake("new", within).metrics, 1000, current).replace is True


def test_a_meaningfully_worse_model_is_rejected():
    current = _fake("old", 4.5)  # skill 0.90

    beyond = 5.0 * (0.90 + TOLERANCE) + 0.001
    decision = decide(_fake("new", beyond).metrics, 1000, current)

    assert decision.replace is False
    assert "worse than the saved 0.900" in decision.reason


def test_a_model_much_worse_than_the_baseline_is_rejected_even_with_nothing_saved():
    broken = _fake("new", 5.0 * MAX_SKILL)

    assert decide(broken.metrics, 1000, None).replace is False
    assert decide(_fake("new", 5.1).metrics, 1000, None).replace is True


def test_a_model_trained_on_fewer_rows_is_rejected_as_missing_data():
    current = _fake("old", 4.5, n_rows=1000)

    decision = decide(_fake("new", 4.0).metrics, 900, current)

    assert decision.replace is False
    assert "900 rows" in decision.reason
    assert decide(_fake("new", 4.0).metrics, 985, current).replace is True


def test_a_saved_model_without_a_score_is_replaced_by_one_with_a_score():
    assert decide(_fake("new", 4.5).metrics, 1000, Fake("old")).replace is True
    assert decide({}, 1000, Fake("old")).replace is False


# --- The job -----------------------------------------------------------------------------------


def _target(name: str, candidate, calls: list | None = None) -> Target:
    def fit(log):
        log("training")
        if isinstance(candidate, Exception):
            raise candidate
        if calls is not None:
            calls.append(name)
        return SimpleNamespace(final=candidate)

    def load(directory):
        path = directory / f"{name}.joblib"
        return joblib.load(path) if path.exists() else None

    def save(obj, directory):
        return model.dump_atomic(obj, directory / f"{name}.joblib")

    return Target(name, fit, load, save)


def test_the_job_replaces_accepted_models_keeps_rejected_ones_and_survives_a_failure(tmp_path):
    joblib.dump(_fake("good", 4.5), tmp_path / "good.joblib")
    joblib.dump(_fake("bad", 4.5), tmp_path / "bad.joblib")
    bad_before = (tmp_path / "bad.joblib").read_bytes()
    calls = []

    outcomes = retrain_all(
        [
            _target("broken", RuntimeError("database gone")),
            _target("good", _fake("good", 4.4), calls),
            _target("bad", _fake("bad", 4.8), calls),
            _target("fresh", _fake("fresh", 4.0), calls),
        ],
        tmp_path,
    )

    by_name = {o.name: o for o in outcomes}
    assert calls == ["good", "bad", "fresh"]  # the failure didn't stop the rest
    assert by_name["broken"].error == "RuntimeError: database gone"
    assert by_name["good"].decision.replace and joblib.load(tmp_path / "good.joblib").metrics == {
        "held_out": _held_out(4.4)
    }
    assert not by_name["bad"].decision.replace
    assert (tmp_path / "bad.joblib").read_bytes() == bad_before
    assert by_name["fresh"].path == tmp_path / "fresh.joblib"
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "bad.joblib",
        "fresh.joblib",
        "good.joblib",
    ]  # no temporary files left behind


def test_an_atomic_save_is_readable_by_everyone_and_reloaded_by_the_api_cache(tmp_path):
    first = model.SportModel("NBA", {}, "2026-04-01", 1)
    path = model.save(first, tmp_path)
    os.utime(path, (0, 0))  # so the rewrite's mtime is sure to differ
    assert model.load_cached("NBA", tmp_path).trained_through == "2026-04-01"

    model.save(model.SportModel("NBA", {}, "2026-10-01", 2), tmp_path)

    assert oct(path.stat().st_mode & 0o777) == "0o644"
    assert model.load_cached("NBA", tmp_path).trained_through == "2026-10-01"


def test_the_nba_cutoff_ignores_a_season_that_has_only_just_started():
    from app.ml.train import default_cutoff

    last_season = pd.date_range("2025-10-21", "2026-04-12", periods=1000)
    new_season = pd.date_range("2026-10-20", "2026-10-25", periods=40)
    frame = pd.DataFrame(
        {
            "season": ["2025-26"] * len(last_season) + ["2026-27"] * len(new_season),
            "start_time": list(last_season) + list(new_season),
        }
    )

    cutoff = default_cutoff("NBA", frame)

    assert cutoff == last_season.to_series().quantile(0.7)


def test_the_worker_job_raises_when_a_model_failed(monkeypatch):
    from data_pipeline import worker

    ok = retrain.Outcome("NBA", retrain.Decision(True, "fine", 0.9, 0.9))
    failed = retrain.Outcome("NFL", None, error="ValueError: no rows")
    monkeypatch.setattr(retrain, "retrain_all", lambda: [ok])
    worker.run_retrain()

    monkeypatch.setattr(retrain, "retrain_all", lambda: [ok, failed])
    with pytest.raises(RuntimeError, match=r"^NFL: failed \(ValueError: no rows\)$"):
        worker.run_retrain()
