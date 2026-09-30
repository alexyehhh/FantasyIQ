"""How accurate each projection source was: its saved projection against what actually happened.

A source's projection for a game is its last snapshot taken before kickoff
(`ProjectionSnapshot`), so nothing it says here could have seen the result. Both sides are scored
with the same `ScoringConfig`, so the error is in points a league would see, and because the
snapshots hold raw stat lines any league's scoring works.

Fairness rules:
- Sources are compared only on the player-games *every* compared source projected. A source that
  covers more players isn't judged on easier or harder ones than another.
- A player who did not play isn't scored by default (a projection is for a player who plays, and
  a source that knew he was out would otherwise be rewarded for luck); `include_dnp` scores them as
  zero instead. They are counted either way.
- "live" snapshots (taken ahead of the game) and "backtest" ones (replayed afterwards) are never
  mixed; the report says which it is.

Players only for now: team defenses and kickers' distance-bracket edge cases aren't judged
separately. Nothing is stored here; it is computed from the snapshots on request.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from math import sqrt
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    FieldGoalKick,
    Game,
    Player,
    PlayerGameStats,
    PlayerGameStatsNFL,
    ProjectionSnapshot,
)
from app.ml.features import POSITION_GROUPS
from app.services.players import serialize_stats_row
from app.services.projections.base import KickBucket
from app.services.projections.expected_scoring import score_expected_player
from app.services.projections.sleeper import et_date
from app.services.scoring import ScoringConfig, score_player_game

Origin = Literal["live", "backtest"]
# Fewer player-games than this says little about which source is better; the report says so.
MIN_SAMPLE = 50
# A period's rank correlation needs a list of at least this many players to mean anything.
_MIN_FOR_RANK = 10
_STATS_MODEL = {"NFL": PlayerGameStatsNFL, "NBA": PlayerGameStats}


@dataclass
class Totals:
    """One source's accuracy over a set of player-games."""

    n: int
    mae: float
    rmse: float
    bias: float  # mean (projected - actual): positive means it projects too high
    mean_projected: float
    mean_actual: float
    rank_corr: float | None  # average per-period Spearman correlation, None when not computable


@dataclass
class PeriodPoint:
    """The error of each source in one NFL week or one NBA week, on the same player-games."""

    key: str  # sortable: "2026-04" for week 4, the Monday's date for an NBA week
    label: str
    n: int
    mae: dict[str, float]


@dataclass
class PositionTotals:
    position: str
    n: int
    enough_data: bool
    sources: dict[str, Totals]


@dataclass
class Coverage:
    """How much of a source's saved projections made it into the comparison."""

    projected: int  # player-games it projected among the finished games considered
    compared: int  # of those, in the comparison (everyone else projected them too and played)


@dataclass
class AccuracyReport:
    sport: str
    scoring: str
    origin: Origin
    sources: list[str]
    compared: int
    did_not_play: int
    enough_data: bool
    overall: dict[str, Totals] = field(default_factory=dict)
    by_position: list[PositionTotals] = field(default_factory=list)
    series: list[PeriodPoint] = field(default_factory=list)
    coverage: dict[str, Coverage] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class _Row:
    period: tuple[str, str]  # (sortable key, label)
    position: str
    actual: float
    projected: dict[str, float]


def position_group(sport: str, position: str | None) -> str | None:
    """The bucket a position is judged in: QB/RB/WR/TE/K for the NFL, G/F/C for the NBA."""
    if position is None:
        return None
    if sport == "NFL":
        return {"FB": "RB", "PK": "K"}.get(position, position)
    return POSITION_GROUPS.get(position)


def _period(sport: str, game: Game) -> tuple[str, str]:
    if sport == "NFL":
        week = game.week or 0
        return (f"{game.season}-{week:02d}", f"Week {week}")
    day = et_date(game.start_time)
    monday: date = day - timedelta(days=day.weekday())
    return (monday.isoformat(), f"Week of {monday:%b} {monday.day}")


def _ranks(values: list[float]) -> list[float]:
    """Average ranks, ties sharing their mean rank."""
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def _spearman(actual: list[float], projected: list[float]) -> float | None:
    if len(actual) < _MIN_FOR_RANK:
        return None
    a, p = _ranks(actual), _ranks(projected)
    mean_a, mean_p = sum(a) / len(a), sum(p) / len(p)
    cov = sum((x - mean_a) * (y - mean_p) for x, y in zip(a, p, strict=True))
    var_a = sum((x - mean_a) ** 2 for x in a)
    var_p = sum((y - mean_p) ** 2 for y in p)
    if var_a == 0 or var_p == 0:
        return None
    return cov / sqrt(var_a * var_p)


def _totals(rows: list[_Row], source: str) -> Totals:
    errors = [r.projected[source] - r.actual for r in rows]
    by_period: dict[tuple[str, str], list[_Row]] = defaultdict(list)
    for row in rows:
        by_period[row.period].append(row)
    ranks = [
        c
        for group in by_period.values()
        if (c := _spearman([r.actual for r in group], [r.projected[source] for r in group]))
        is not None
    ]
    n = len(rows)
    return Totals(
        n=n,
        mae=sum(abs(e) for e in errors) / n,
        rmse=sqrt(sum(e * e for e in errors) / n),
        bias=sum(errors) / n,
        mean_projected=sum(r.projected[source] for r in rows) / n,
        mean_actual=sum(r.actual for r in rows) / n,
        rank_corr=sum(ranks) / len(ranks) if ranks else None,
    )


def _latest_before_kickoff(
    db: Session, sport: str, origin: Origin, games: dict[int, Game]
) -> dict[tuple[str, int, int], dict[str, ProjectionSnapshot]]:
    """(player, game) -> {source: that source's last snapshot taken before the game started}."""
    rows = db.scalars(
        select(ProjectionSnapshot)
        .where(
            ProjectionSnapshot.sport == sport,
            ProjectionSnapshot.origin == origin,
            ProjectionSnapshot.kind == "player",
            ProjectionSnapshot.game_id.in_(list(games)),
        )
        .order_by(ProjectionSnapshot.captured_at)
    )
    found: dict[tuple[str, int, int], dict[str, ProjectionSnapshot]] = defaultdict(dict)
    for row in rows:
        if row.captured_at < games[row.game_id].start_time:
            found[(row.kind, row.entity_id, row.game_id)][row.source] = row  # later overwrites
    return found


def _projected_points(config: ScoringConfig, snapshot: ProjectionSnapshot) -> float:
    kicks = [KickBucket(**k) for k in snapshot.kicks or []]
    return score_expected_player(config, snapshot.stats, kicks).points


def compute(
    db: Session,
    *,
    sport: str,
    config: ScoringConfig,
    sources: list[str] | None = None,
    position: str | None = None,
    season: str | None = None,
    origin: Origin = "live",
    include_dnp: bool = False,
) -> AccuracyReport:
    """Score the sources' saved projections against the finished games' box scores."""
    query = select(Game).where(
        Game.sport == sport, Game.status == "final", Game.stats_final.is_(True)
    )
    if season:
        query = query.where(Game.season == season)
    games = {g.id: g for g in db.scalars(query)}
    snapshots = _latest_before_kickoff(db, sport, origin, games) if games else {}

    available = sorted({s for by_source in snapshots.values() for s in by_source})
    chosen = sorted(set(sources)) if sources else available
    report = AccuracyReport(
        sport=sport,
        scoring=config.name,
        origin=origin,
        sources=chosen,
        compared=0,
        did_not_play=0,
        enough_data=False,
    )
    if not chosen or not snapshots:
        report.notes.append(
            "No finished games have saved projections yet: they are captured before kickoff, so "
            "this fills in as games are played."
        )
        return report

    projected_by = {s: sum(1 for by in snapshots.values() if s in by) for s in chosen}
    common = {k: by for k, by in snapshots.items() if all(s in by for s in chosen)}

    player_ids = {k[1] for k in common}
    players = {p.id: p for p in db.scalars(select(Player).where(Player.id.in_(player_ids)))}
    model = _STATS_MODEL[sport]
    stats_rows = {
        (r.player_id, r.game_id): r
        for r in db.scalars(
            select(model).where(
                model.player_id.in_(player_ids), model.game_id.in_({k[2] for k in common})
            )
        )
    }
    kicks: dict[tuple[int, int], list[tuple[int, str]]] = defaultdict(list)
    if sport == "NFL":
        for kick in db.scalars(
            select(FieldGoalKick).where(
                FieldGoalKick.player_id.in_(player_ids),
                FieldGoalKick.game_id.in_({k[2] for k in common}),
            )
        ):
            kicks[(kick.player_id, kick.game_id)].append((kick.distance, kick.result))

    rows: list[_Row] = []
    compared_per_source = dict.fromkeys(chosen, 0)
    wanted = position.upper() if position else None
    for (_, player_id, game_id), by_source in common.items():
        player = players.get(player_id)
        bucket = position_group(sport, player.position if player else None)
        if bucket is None or (wanted and bucket != wanted):
            continue
        stats_row = stats_rows.get((player_id, game_id))
        played = stats_row is not None and (sport != "NBA" or (stats_row.minutes or 0) > 0)
        if not played:
            report.did_not_play += 1
            if not include_dnp:
                continue
        actual = (
            score_player_game(
                config, serialize_stats_row(stats_row), kicks.get((player_id, game_id), [])
            )
            if played and stats_row is not None
            else 0.0
        )
        rows.append(
            _Row(
                period=_period(sport, games[game_id]),
                position=bucket,
                actual=actual,
                projected={s: _projected_points(config, by_source[s]) for s in chosen},
            )
        )
        for s in chosen:
            compared_per_source[s] += 1

    report.compared = len(rows)
    report.enough_data = len(rows) >= MIN_SAMPLE
    report.coverage = {
        s: Coverage(projected=projected_by[s], compared=compared_per_source[s]) for s in chosen
    }
    if not rows:
        report.notes.append("No player-games were projected by every source and then played.")
        return report

    report.overall = {s: _totals(rows, s) for s in chosen}
    by_position: dict[str, list[_Row]] = defaultdict(list)
    for row in rows:
        by_position[row.position].append(row)
    report.by_position = [
        PositionTotals(
            position=name,
            n=len(group),
            enough_data=len(group) >= MIN_SAMPLE,
            sources={s: _totals(group, s) for s in chosen},
        )
        for name, group in sorted(by_position.items())
    ]
    by_period: dict[tuple[str, str], list[_Row]] = defaultdict(list)
    for row in rows:
        by_period[row.period].append(row)
    report.series = [
        PeriodPoint(
            key=key,
            label=label,
            n=len(group),
            mae={
                s: sum(abs(r.projected[s] - r.actual) for r in group) / len(group) for s in chosen
            },
        )
        for (key, label), group in sorted(by_period.items())
    ]
    if not report.enough_data:
        report.notes.append(
            f"Only {len(rows)} player-games so far; under {MIN_SAMPLE} is too few to say which "
            "source is better."
        )
    if len(chosen) == 1:
        report.notes.append(
            "Only one source has saved projections, so there is nothing to compare."
        )
    return report
