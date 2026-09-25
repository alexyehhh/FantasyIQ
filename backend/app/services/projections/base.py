"""What a projection source is.

A source (Sleeper now, later our own model) answers one question: what stat line do we
expect from this player, or this team defense, in their next game? It answers in *raw stats*,
never in fantasy points. The service then scores those stats with the request's `ScoringConfig`,
so every source is rescored under the league's own settings and no source needs to know about
scoring.

Sources are looked up by name in `PROVIDERS`; adding one means writing a class with `project`
and registering it there.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Protocol

from sqlalchemy.orm import Session

from app.db.models import Game, Player, Team
from app.services.scoring import ScoringConfig

Kind = Literal["player", "defense"]
Key = tuple[Kind, int]  # ("player", players.id) or ("defense", teams.id)


class ProjectionError(RuntimeError):
    """A source could not be reached or answered with something unusable."""


@dataclass(frozen=True)
class Target:
    """One player or team defense to project, with the game to project it for."""

    kind: Kind
    sport: str
    entity_id: int
    name: str
    team: Team | None
    position: str | None
    game: Game
    opponent: Team
    is_home: bool
    player: Player | None = None

    @property
    def key(self) -> Key:
        return (self.kind, self.entity_id)


@dataclass(frozen=True)
class KickBucket:
    """Expected field goal attempts from `low` to `high` yards, made and missed, per game.

    Sleeper projects five ranges (0-19, 20-29, 30-39, 40-49, 50+)."""

    low: int
    high: int
    made: float
    missed: float


@dataclass
class StatProjection:
    """A source's expected stat line for one target, before any scoring.

    `stats` uses our stat names (the columns of the stats tables), so a `ScoringConfig` applies
    to it directly. `kicks` carries a kicker's expected field goals by distance, for leagues that
    score them by distance. `unprojected` names stats the caller's scoring values that this source
    doesn't project at all; they count as zero."""

    stats: dict[str, float]
    kicks: list[KickBucket] = field(default_factory=list)
    unprojected: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Unavailable:
    """The source has nothing for this target, and why."""

    reason: str


@dataclass(frozen=True)
class RankedCandidate:
    """Someone a source projects for a game, with the fantasy points its stat line is worth."""

    kind: Kind
    entity_id: int
    points: float
    injury_status: str | None = None


class ProjectionProvider(Protocol):
    name: str
    label: str
    description: str
    sports: frozenset[str]

    def project(
        self, db: Session, targets: Sequence[Target], config: ScoringConfig
    ) -> dict[Key, StatProjection | Unavailable]:
        """Projections for `targets`, all of one sport. A target left out of the result is
        treated as unavailable. Raises ProjectionError if the source can't be reached."""
        ...

    def rank(
        self,
        db: Session,
        *,
        sport: str,
        season: str,
        week: int | None,
        day: date | None,
        positions: Sequence[str] | None,
        defenses: bool,
        config: ScoringConfig,
    ) -> list[RankedCandidate]:
        """Everyone the source projects for the game(s) in `week` (NFL) or on `day` (NBA), best
        first: our players at `positions` (any position if None), or the team defenses. The
        candidates' games are not checked here; `project` does that for the ones shown."""
        ...


PROVIDERS: dict[str, ProjectionProvider] = {}


class UnknownSource(ValueError):
    pass


def register(provider: ProjectionProvider) -> ProjectionProvider:
    PROVIDERS[provider.name] = provider
    return provider


def get_provider(name: str) -> ProjectionProvider:
    try:
        return PROVIDERS[name]
    except KeyError:
        raise UnknownSource(
            f"Unknown projection source {name!r}; choose one of {sorted(PROVIDERS)}"
        ) from None
