"""Response schemas for the accuracy API (app/api/v1/accuracy.py)."""

from typing import Literal

from pydantic import BaseModel


class SourceTotals(BaseModel):
    """One source's accuracy over a set of player-games, in fantasy points under the request's
    scoring. `bias` is the mean of projected minus actual (positive: projects too high).
    `rank_corr` is the average per-week (NFL) or per-NBA-week Spearman correlation between the
    projected and actual order of players, null when no week had enough players."""

    n: int
    mae: float
    rmse: float
    bias: float
    mean_projected: float
    mean_actual: float
    rank_corr: float | None


class PeriodPoint(BaseModel):
    key: str
    label: str
    n: int
    mae: dict[str, float]


class PositionTotals(BaseModel):
    position: str
    n: int
    enough_data: bool
    sources: dict[str, SourceTotals]


class Coverage(BaseModel):
    projected: int
    compared: int


class AccuracyResponse(BaseModel):
    """How accurate each source's saved, pre-kickoff projections were against the real results.

    Sources are compared only on player-games every compared source projected (`compared`), so
    none is judged on easier ones. `did_not_play` counts projected players who didn't play (left
    out unless `include_dnp`). `enough_data` is false until there are enough player-games to say
    which source is better; `notes` explains an empty or thin report. `series` is each source's
    mean absolute error per NFL week or NBA week, for charting."""

    sport: str
    scoring: str
    origin: Literal["live", "backtest"]
    sources: list[str]
    compared: int
    did_not_play: int
    enough_data: bool
    overall: dict[str, SourceTotals]
    by_position: list[PositionTotals]
    series: list[PeriodPoint]
    coverage: dict[str, Coverage]
    notes: list[str]
