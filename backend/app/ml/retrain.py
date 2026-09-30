"""Retraining the projection models on a schedule (the worker's `retrain` job).

Each model (NBA players, NFL players, NFL team defenses) is refit with the same functions as the
train CLIs: a held-out evaluation (trained on the games before a cutoff, scored on the rest), then
a refit on every finished game. The refit replaces the saved model only if `decide` accepts it.

The rule. The held-out test set grows between runs (new games land after the cutoff), so raw MAE
from one run can't be compared with another's. Each run does score the same simple baseline on its
own test rows, though: `recent_avg`, the decaying average of the player's (or defense's) own games.
A model's *skill* is its fantasy-point MAE divided by that baseline's MAE on the same rows, over
all positions; lower is better, and below 1 beats the baseline. A new model replaces the saved one
when all of these hold:

  1. its skill is at most the saved model's plus `TOLERANCE` (0.02): it may give back up to 2% of
     the baseline's error, about the noise between test sets, but no more;
  2. its skill is below `MAX_SKILL` (1.05): more than 5% worse than the baseline is a broken model,
     whatever the saved one scored;
  3. it was trained on at least `MIN_ROW_SHARE` (98%) as many rows as the saved model: fewer means
     games went missing from the database, not that there is less to learn from.

With no saved model, or one saved without held-out metrics, only rule 2 applies. A rejected model
is logged with the reason and thrown away; the saved one keeps serving. A model is written to a
temporary file and renamed over the old one, so the API (which reloads a model when its file's
mtime changes) never reads half a file.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.ml import defense, model, train, train_defense
from app.ml.model import MODEL_DIR

logger = logging.getLogger(__name__)

TOLERANCE = 0.02
MAX_SKILL = 1.05
MIN_ROW_SHARE = 0.98
BASELINE = "recent_avg"


def skill(held_out: Sequence[dict[str, Any]] | None) -> float | None:
    """The model's MAE over the baseline's, from a held-out table's records (all positions)."""
    mae = {
        row["method"]: row["mae"] for row in held_out or [] if row.get("position", "ALL") == "ALL"
    }
    if not mae.get("model") or not mae.get(BASELINE):
        return None
    return float(mae["model"]) / float(mae[BASELINE])


@dataclass(frozen=True)
class Decision:
    replace: bool
    reason: str
    new_skill: float | None
    old_skill: float | None


def decide(new_metrics: dict[str, Any], new_rows: int, current: Any | None) -> Decision:
    """Whether a newly trained model (its metrics and training rows) should replace `current`."""
    new = skill(new_metrics.get("held_out"))
    old = skill(current.metrics.get("held_out")) if current is not None else None
    if new is None:
        return Decision(False, "no held-out score for the new model", new, old)
    if new >= MAX_SKILL:
        return Decision(False, f"skill {new:.3f} is not below {MAX_SKILL}", new, old)
    if current is None:
        return Decision(True, "no saved model", new, old)
    if new_rows < MIN_ROW_SHARE * current.n_rows:
        return Decision(
            False, f"trained on {new_rows} rows, the saved model on {current.n_rows}", new, old
        )
    if old is None:
        return Decision(True, "the saved model has no held-out score", new, old)
    if new > old + TOLERANCE:
        return Decision(False, f"skill {new:.3f} is worse than the saved {old:.3f}", new, old)
    return Decision(True, f"skill {new:.3f} vs the saved {old:.3f}", new, old)


@dataclass(frozen=True)
class Target:
    """One saved model: how to train it (returning the held-out table and the refit model), read
    the saved one, and save a new one."""

    name: str
    fit: Callable[[Callable[[str], None]], Any]
    load: Callable[[Path], Any | None]
    save: Callable[[Any, Path], Path]


TARGETS = (
    Target(
        "NBA", lambda log: train.fit("NBA", log=log), lambda d: model.load("NBA", d), model.save
    ),
    Target(
        "NFL", lambda log: train.fit("NFL", log=log), lambda d: model.load("NFL", d), model.save
    ),
    Target("NFL defense", lambda log: train_defense.fit(log=log), defense.load, defense.save),
)


@dataclass(frozen=True)
class Outcome:
    name: str
    decision: Decision | None
    path: Path | None = None
    error: str | None = None

    def summary(self) -> str:
        if self.error is not None:
            return f"{self.name}: failed ({self.error})"
        assert self.decision is not None
        verb = "replaced" if self.decision.replace else "kept the saved model"
        return f"{self.name}: {verb}, {self.decision.reason}"


def retrain_all(targets: Sequence[Target] = TARGETS, directory: Path = MODEL_DIR) -> list[Outcome]:
    """Retrain every model, replacing each saved one the rule accepts. One failing doesn't stop
    the others; its error is in its outcome."""
    outcomes = []
    for target in targets:
        try:
            trained = target.fit(lambda line, name=target.name: logger.info("%s: %s", name, line))
            candidate = trained.final
            decision = decide(candidate.metrics, candidate.n_rows, target.load(directory))
            path = target.save(candidate, directory) if decision.replace else None
            outcome = Outcome(target.name, decision, path)
        except Exception as exc:  # noqa: BLE001 - the other models should still be retrained
            logger.exception("Retraining %s failed", target.name)
            outcome = Outcome(target.name, None, error=f"{type(exc).__name__}: {exc}")
        logger.info("Retrain %s", outcome.summary())
        outcomes.append(outcome)
    return outcomes
