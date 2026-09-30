"""Saving what each projection source says about upcoming games, so it can be scored later.

`capture` asks every source for its stat line for everyone it projects in the games about to be
played and stores it (`ProjectionSnapshot`). It only looks at games that haven't started, so a
snapshot can't have seen the result. Run often (the worker does, every few hours): a capture whose
stat line is the same as the source's latest for that player and game is skipped, so the table
holds the changes, and the last row before kickoff is what the source said going in.

A source being unreachable doesn't stop the others; its error is reported once the rest are saved.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Game, Player, ProjectionSnapshot, Team
from app.services.projections.base import (
    PROVIDERS,
    Kind,
    ProjectionError,
    ProjectionProvider,
    StatProjection,
    Target,
)
from app.services.projections.sleeper import et_date
from app.services.scoring import ScoringConfig, default_config

# How far ahead games are captured: the NFL plays one week at a time, the NBA every day.
HORIZON = {"NFL": timedelta(days=8), "NBA": timedelta(days=2)}
_PRECISION = 4


@dataclass
class SourceReport:
    captured: int = 0
    unchanged: int = 0
    unavailable: int = 0


@dataclass
class CaptureReport:
    sources: dict[str, SourceReport] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [
            f"{name}: {r.captured} saved, {r.unchanged} unchanged, {r.unavailable} unavailable"
            for name, r in self.sources.items()
        ]
        return "; ".join(parts) or "nothing to capture"


def _upcoming(db: Session, sport: str, now: datetime) -> list[Game]:
    return list(
        db.scalars(
            select(Game)
            .where(
                Game.sport == sport,
                Game.status == "scheduled",
                Game.start_time > now,
                Game.start_time <= now + HORIZON[sport],
            )
            .order_by(Game.start_time)
        )
    )


def _round(stats: dict[str, float]) -> dict[str, float]:
    return {k: round(float(v), _PRECISION) for k, v in stats.items()}


def _kicks(projection: StatProjection) -> list[dict[str, float]] | None:
    if not projection.kicks:
        return None
    return [
        {"low": k.low, "high": k.high, "made": round(k.made, 4), "missed": round(k.missed, 4)}
        for k in projection.kicks
    ]


def _groups(games: list[Game], sport: str) -> dict[tuple[str, int | date], list[Game]]:
    """The games a source is asked about together: an NFL week, or an NBA day (US Eastern)."""
    groups: dict[tuple[str, int | date], list[Game]] = defaultdict(list)
    for game in games:
        key = game.week if sport == "NFL" else et_date(game.start_time)
        if key is not None:
            groups[(game.season, key)].append(game)
    return groups


def capture(
    db: Session, *, now: datetime, sources: list[str] | None = None, sports: list[str] | None = None
) -> CaptureReport:
    """Save every (or the named) source's current projections for upcoming games. The caller
    commits."""
    report = CaptureReport()
    config = {sport: default_config(sport) for sport in ("NFL", "NBA")}
    for sport in sports or ["NFL", "NBA"]:
        games = _upcoming(db, sport, now)
        for (season, key), group in _groups(games, sport).items():
            by_team = {}
            for game in group:
                by_team[game.home_team_id] = (game, True)
                by_team[game.away_team_id] = (game, False)
            for name in sources or list(PROVIDERS):
                provider = PROVIDERS[name]
                if sport not in provider.sports:
                    continue
                result = report.sources.setdefault(name, SourceReport())
                try:
                    _capture_group(
                        db, provider, sport, season, key, by_team, config[sport], now, result
                    )
                except ProjectionError as exc:
                    report.errors.append(f"{name} {sport} {key}: {exc}")
    return report


def _capture_group(
    db: Session,
    provider: ProjectionProvider,
    sport: str,
    season: str,
    key: int | date,
    by_team: dict[int, tuple[Game, bool]],
    config: ScoringConfig,
    now: datetime,
    result: SourceReport,
) -> None:
    week = key if isinstance(key, int) else None
    day = key if isinstance(key, date) else None
    candidates = []
    for defenses in (False, True) if sport == "NFL" else (False,):
        candidates += provider.rank(
            db,
            sport=sport,
            season=season,
            week=week,
            day=day,
            positions=None,
            defenses=defenses,
            config=config,
        )
    if not candidates:
        return
    players = {
        p.id: p
        for p in db.scalars(
            select(Player).where(
                Player.id.in_([c.entity_id for c in candidates if c.kind == "player"])
            )
        )
    }
    teams = {t.id: t for t in db.scalars(select(Team).where(Team.sport == sport))}
    targets: list[Target] = []
    for candidate in candidates:
        kind: Kind = candidate.kind
        if kind == "player":
            player = players.get(candidate.entity_id)
            team = teams.get(player.team_id) if player and player.team_id else None
            name, position = (player.name, player.position) if player else ("", None)
        else:
            player, team = None, teams.get(candidate.entity_id)
            name, position = (f"{team.name} D/ST" if team else ""), "DEF"
        if team is None or team.id not in by_team or (kind == "player" and player is None):
            continue
        game, is_home = by_team[team.id]
        opponent = teams.get(game.away_team_id if is_home else game.home_team_id)
        if opponent is None:
            continue
        targets.append(
            Target(
                kind,
                sport,
                candidate.entity_id,
                name,
                team,
                position,
                game,
                opponent,
                is_home,
                player,
            )
        )

    answers = provider.project(db, targets, config)
    latest = _latest(db, provider.name, [t.game.id for t in targets])
    for target in targets:
        answer = answers.get(target.key)
        if not isinstance(answer, StatProjection):
            result.unavailable += 1
            continue
        stats, kicks = _round(answer.stats), _kicks(answer)
        previous = latest.get((target.kind, target.entity_id, target.game.id))
        if previous is not None and previous.stats == stats and previous.kicks == kicks:
            result.unchanged += 1
            continue
        db.add(
            ProjectionSnapshot(
                source=provider.name,
                sport=sport,
                kind=target.kind,
                entity_id=target.entity_id,
                game_id=target.game.id,
                origin="live",
                captured_at=now,
                stats=stats,
                kicks=kicks,
                meta=answer.meta or None,
            )
        )
        result.captured += 1
    db.flush()


def _latest(
    db: Session, source: str, game_ids: list[int]
) -> dict[tuple[str, int, int], ProjectionSnapshot]:
    """The source's most recent snapshot of each (kind, entity, game) among `game_ids`."""
    latest: dict[tuple[str, int, int], ProjectionSnapshot] = {}
    rows = db.scalars(
        select(ProjectionSnapshot)
        .where(ProjectionSnapshot.source == source, ProjectionSnapshot.game_id.in_(game_ids))
        .order_by(ProjectionSnapshot.captured_at)
    )
    for row in rows:
        latest[(row.kind, row.entity_id, row.game_id)] = row  # later rows overwrite earlier
    return latest
