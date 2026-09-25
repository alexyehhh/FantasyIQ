"""Projections: pick the game, ask a source for the stat line, score it, flag what needs flagging.

Like the other services this is plain SQLAlchemy with no knowledge of HTTP. Sources
(`app/services/projections/`) return expected raw stats; the scoring under the caller's
`ScoringConfig` happens here, once, so every source is scored the same way.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Literal

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db.models import Game, Player, Team
from app.services import players as players_service
from app.services.projections import history
from app.services.projections.base import (
    KickBucket,
    Kind,
    ProjectionProvider,
    StatProjection,
    Target,
    Unavailable,
    get_provider,
)
from app.services.projections.expected_scoring import (
    score_expected_defense,
    score_expected_player,
)
from app.services.projections.sleeper import et_date
from app.services.projections.spread import chance_best, spread
from app.services.scoring import ScoringConfig

Status = Literal["ok", "out", "no_game", "unavailable"]

# Injury statuses (as ESPN words them) that mean the player won't play.
_OUT_STATUSES = {"out", "injured reserve", "ir", "suspended", "suspension"}
# Left out of the top lists as well: doubtful players almost never play, so ranking them at a
# full-health projection would only mislead. (When compared by name they're projected, flagged.)
_LEFT_OUT_OF_TOP = _OUT_STATUSES | {"doubtful"}
_UNCERTAIN_NOTE = "Listed {status}; the projection assumes they play."


class ProjectionInputError(ValueError):
    """The request asks for something that can't be projected (unknown id, mixed sports, ...)."""


@dataclass
class Projection:
    kind: Kind
    entity_id: int
    name: str
    sport: str
    position: str | None
    team: Team | None
    source: str
    status: Status
    game: Game | None = None
    opponent: Team | None = None
    is_home: bool | None = None
    fantasy_points: float | None = None
    low: float | None = None
    high: float | None = None
    stats: dict[str, float] = field(default_factory=dict)
    # Games of history the range rests on (never the projection itself).
    games_sampled: int | None = None
    injury_status: str | None = None
    headshot_url: str | None = None
    std: float | None = None
    spread_basis: str | None = None
    chance_best: float | None = None
    approximate: bool = False
    unprojected: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _find_game(
    db: Session, team: Team, sport: str, week: int | None, now: datetime
) -> tuple[Game, Team, bool] | None:
    """`team`'s next game, or with `week` (NFL) its game in that week of the current season."""
    if week is None:
        return players_service.get_team_next_game(db, team.id, now=now)
    season = players_service.get_current_season(db, sport, now=now)
    game = db.scalars(
        select(Game).where(
            Game.sport == sport,
            Game.season == season,
            Game.week == week,
            (Game.home_team_id == team.id) | (Game.away_team_id == team.id),
        )
    ).first()
    if game is None:
        return None
    is_home = game.home_team_id == team.id
    opponent = db.get(Team, game.away_team_id if is_home else game.home_team_id)
    return (game, opponent, is_home) if opponent else None


def _players(db: Session, player_ids: Sequence[int]) -> list[Player]:
    found = {p.id: p for p in db.scalars(select(Player).where(Player.id.in_(player_ids)))}
    missing = [pid for pid in player_ids if pid not in found]
    if missing:
        raise ProjectionInputError(f"Unknown player ids: {missing}")
    return [found[pid] for pid in dict.fromkeys(player_ids)]


def _defenses(db: Session, team_ids: Sequence[int]) -> list[Team]:
    found = {
        t.id: t for t in db.scalars(select(Team).where(Team.id.in_(team_ids), Team.sport == "NFL"))
    }
    missing = [tid for tid in team_ids if tid not in found]
    if missing:
        raise ProjectionInputError(f"Unknown defense ids: {missing}")
    return [found[tid] for tid in dict.fromkeys(team_ids)]


def _key(result: Projection) -> tuple[Kind, int]:
    return (result.kind, result.entity_id)


def project(
    db: Session,
    *,
    sport: str,
    source: str,
    config: ScoringConfig,
    player_ids: Sequence[int] = (),
    defense_ids: Sequence[int] = (),
    week: int | None = None,
    now: datetime | None = None,
) -> list[Projection]:
    """Projections for players and/or team defenses of one sport, for each one's next game (or,
    for the NFL, their game in `week`), highest fantasy points first; anyone without a number
    (bye week, no projection) last.

    Raises ProjectionInputError for a request that can't be answered, UnknownSource for an
    unknown `source`, and ProjectionError when the source can't be reached."""
    provider = get_provider(source)
    if config.sport != sport:
        raise ProjectionInputError(f"A {config.sport} scoring config can't score {sport}")
    if sport not in provider.sports:
        raise ProjectionInputError(f"{source} has no {sport} projections")
    if week is not None and sport != "NFL":
        raise ProjectionInputError("week only applies to the NFL")
    if defense_ids and sport != "NFL":
        raise ProjectionInputError("Team defenses are NFL only")
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)

    players = _players(db, player_ids)
    if any(p.sport != sport for p in players):
        raise ProjectionInputError(f"Every player must be a {sport} player")
    teams = _defenses(db, defense_ids)

    subjects: list[tuple[Kind, int, str, str | None, Team | None, Player | None]] = [
        ("player", p.id, p.name, p.position, p.team, p) for p in players
    ] + [("defense", t.id, f"{t.name} D/ST", "DEF", t, None) for t in teams]

    results: list[Projection] = []
    targets: list[Target] = []
    for kind, entity_id, name, position, team, player in subjects:
        result = Projection(
            kind=kind,
            entity_id=entity_id,
            name=name,
            sport=sport,
            position=position,
            team=team,
            source=source,
            status="no_game",
            injury_status=player.injury_status if player else None,
            headshot_url=player.headshot_url if player else None,
        )
        results.append(result)
        if result.injury_status and result.injury_status.lower() in _OUT_STATUSES:
            result.status = "out"
            result.fantasy_points = 0.0
            result.notes.append(f"Listed {result.injury_status}.")
            continue
        found = _find_game(db, team, sport, week, now) if team else None
        if found is None:
            result.notes.append(
                "No game this week (bye week)." if week else "No upcoming game scheduled."
            )
            continue
        result.game, result.opponent, result.is_home = found
        targets.append(Target(kind, sport, entity_id, name, team, position, *found, player=player))

    if targets:
        _apply(db, provider, targets, config, {_key(r): r for r in results})
    _rate_chances(results)
    return sorted(results, key=lambda r: (r.fantasy_points is None, -(r.fantasy_points or 0.0)))


def _rate_chances(results: list[Projection]) -> None:
    """Each scored player's chance of scoring the most among the ones compared. Players whose game
    has started can't be started any more, so they neither get a chance nor share in the others'."""
    scored = [
        r
        for r in results
        if r.fantasy_points is not None and (r.game is None or r.game.status == "scheduled")
    ]
    if len(scored) < 2:
        return
    chances = chance_best([r.fantasy_points or 0.0 for r in scored], [r.std or 0.0 for r in scored])
    for result, chance in zip(scored, chances, strict=True):
        result.chance_best = round(chance, 3)


def _apply(
    db: Session,
    provider: ProjectionProvider,
    targets: list[Target],
    config: ScoringConfig,
    by_key: dict[tuple[Kind, int], Projection],
) -> None:
    answers = provider.project(db, targets, config)
    for target in targets:
        result = by_key[target.key]
        answer = answers.get(target.key, Unavailable("The source has no projection for this"))
        if isinstance(answer, Unavailable):
            result.status = "unavailable"
            result.notes.append(answer.reason)
            continue
        _fill(result, answer, config, history.points_spread(db, target, config))


def _fill(
    result: Projection,
    answer: StatProjection,
    config: ScoringConfig,
    history: tuple[float | None, int],
) -> None:
    kicks: list[KickBucket] = answer.kicks
    scored = (
        score_expected_defense(config, answer.stats)
        if result.kind == "defense"
        else score_expected_player(config, answer.stats, kicks)
    )
    result.status = "ok"
    result.fantasy_points = scored.points
    result.approximate = scored.approximate
    result.std, result.spread_basis = spread(result.sport, result.position, scored.points, *history)
    result.low = round(scored.points - result.std, 1)
    result.high = round(scored.points + result.std, 1)
    if result.game and result.game.status != "scheduled":
        result.notes.append(
            "This game has been played." if result.game.status == "final" else "Game in progress."
        )
    result.stats = {stat: round(value, 2) for stat, value in answer.stats.items()}
    result.games_sampled = history[1]
    result.unprojected = answer.unprojected
    result.notes.extend(answer.notes)
    if result.injury_status:
        result.notes.append(_UNCERTAIN_NOTE.format(status=result.injury_status))


def current_week(db: Session, sport: str, *, now: datetime | None = None) -> int | None:
    """The NFL week being played for fantasy purposes: that of the earliest game that hasn't
    finished (so it rolls over after Monday night), or of the last game once the schedule has run
    out. The NBA has no weeks."""
    if sport != "NFL":
        return None
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    unfinished = or_(
        and_(Game.status == "scheduled", Game.start_time >= now), Game.status == "in_progress"
    )
    query = select(Game.week).where(Game.sport == sport, Game.week.is_not(None))
    week = db.scalar(query.where(unfinished).order_by(Game.start_time).limit(1))
    return week or db.scalar(query.order_by(Game.start_time.desc()).limit(1))


# Lineup slots the top-players list can be asked for, and the positions that fill each (ESPN's
# codes; None is anyone).
NFL_SLOTS: dict[str, list[str] | None] = {
    "QB": ["QB"],
    "RB": ["RB", "FB"],
    "WR": ["WR"],
    "TE": ["TE"],
    "FLEX": ["RB", "FB", "WR", "TE"],
    "SUPERFLEX": ["QB", "RB", "FB", "WR", "TE"],
    "K": ["PK"],
    "DST": None,
}
NBA_SLOTS: dict[str, list[str] | None] = {
    "G": ["G", "PG", "SG"],
    "F": ["F", "SF", "PF"],
    "C": ["C"],
    "UTIL": None,
}


def _next_game_day(db: Session, sport: str, now: datetime) -> date | None:
    """The (US Eastern) date of the sport's next game that hasn't finished."""
    start = db.scalar(
        select(Game.start_time)
        .where(
            Game.sport == sport,
            or_(
                and_(Game.status == "scheduled", Game.start_time >= now),
                Game.status == "in_progress",
            ),
        )
        .order_by(Game.start_time)
        .limit(1)
    )
    return et_date(start) if start else None


def top_players(
    db: Session,
    *,
    sport: str,
    slot: str,
    source: str,
    config: ScoringConfig,
    week: int | None = None,
    limit: int = 30,
    offset: int = 0,
    now: datetime | None = None,
) -> tuple[list[Projection], int]:
    """A page of the best projections for a lineup slot, highest first, and how many there are in
    all. Everyone the source projects for the week (NFL) or the next day of games (NBA) is ranked
    by the points of their projected stat line, leaving out anyone ruled out or doubtful; only the
    page asked for is then projected in full (game, range, flags)."""
    provider = get_provider(source)
    slots = NFL_SLOTS if sport == "NFL" else NBA_SLOTS
    slot = slot.upper()
    if slot not in slots:
        raise ProjectionInputError(f"Unknown {sport} slot {slot!r}; choose one of {sorted(slots)}")
    if config.sport != sport or sport not in provider.sports:
        raise ProjectionInputError(f"{source} can't project {sport} with a {config.sport} scoring")
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    season = players_service.get_current_season(db, sport, now=now)
    if season is None:
        return [], 0
    week = week or current_week(db, sport, now=now)

    ranked = provider.rank(
        db,
        sport=sport,
        season=season,
        week=week,
        day=_next_game_day(db, sport, now) if sport == "NBA" else None,
        positions=slots[slot],
        defenses=slot == "DST",
        config=config,
    )
    ranked = [c for c in ranked if (c.injury_status or "").lower() not in _LEFT_OUT_OF_TOP]
    page = ranked[offset : offset + limit]
    if not page:
        return [], len(ranked)
    results = project(
        db,
        sport=sport,
        source=source,
        config=config,
        player_ids=[c.entity_id for c in page if c.kind == "player"],
        defense_ids=[c.entity_id for c in page if c.kind == "defense"],
        week=week if sport == "NFL" else None,
        now=now,
    )
    return [r for r in results if r.status == "ok"], len(ranked)
