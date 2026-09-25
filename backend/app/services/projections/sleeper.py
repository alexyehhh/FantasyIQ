"""The `sleeper` source: Sleeper's public projections (produced by Rotowire).

Sleeper projects a *stat line* per player per game, including the opponent, so this is the
matchup-aware source. Because the stat line is raw stats (yards, receptions, field goals by
distance, sacks, points allowed), it is rescored with the caller's `ScoringConfig` instead of using
Sleeper's own PPR/standard points, which is what lets it follow a league's settings. Stats the
league scores that Sleeper doesn't project (4th-down stops, ...) are reported as `unprojected` and
count as zero, except ones that almost never happen (kick return touchdowns).

Nothing from Sleeper is stored: each week's file is fetched on demand and kept in memory for a
few minutes. The endpoint isn't officially documented, so a change on their side surfaces as a
`ProjectionError`, never as wrong numbers: rows are matched to our players by name and team, and
must agree with our schedule on the opponent.
"""

from __future__ import annotations

import re
import threading
import time
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Player, Team
from app.services.projections.base import (
    Key,
    KickBucket,
    ProjectionError,
    RankedCandidate,
    StatProjection,
    Target,
    Unavailable,
    register,
)
from app.services.projections.expected_scoring import (
    score_expected_defense,
    score_expected_player,
)
from app.services.scoring import ScoringConfig, player_stat_values

# Sleeper's team abbreviations that differ from ESPN's (ours), both sports; compared after this.
_TEAM_ALIASES = {
    "WAS": "WSH",
    "GSW": "GS",
    "NOP": "NO",
    "NYK": "NY",
    "SAS": "SA",
    "UTA": "UTAH",
    "JAC": "JAX",
}

_NFL_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF", "FB")

# our stat name -> the Sleeper stats that are summed to make it. A stat Sleeper leaves out of a
# player's line is zero.
_NFL_PLAYER = {
    "passing_completions": ("pass_cmp",),
    "passing_attempts": ("pass_att",),
    "passing_yards": ("pass_yd",),
    "passing_touchdowns": ("pass_td",),
    "interceptions": ("pass_int",),
    "rushing_attempts": ("rush_att",),
    "rushing_yards": ("rush_yd",),
    "rushing_touchdowns": ("rush_td",),
    "receptions": ("rec",),
    "receiving_targets": ("rec_tgt",),
    "receiving_yards": ("rec_yd",),
    "receiving_touchdowns": ("rec_td",),
    "fumbles_lost": ("fum_lost",),
    "field_goals_made": ("fgm",),
    "field_goal_attempts": ("fga",),
    "extra_points_made": ("xpm",),
    "extra_point_attempts": ("xpa",),
    "punt_return_touchdowns": ("pr_td",),
}
_NFL_DEFENSE = {
    "sacks": ("sack",),
    "interceptions": ("int",),
    "fumble_recoveries": ("fum_rec",),
    "safeties": ("safe",),
    "blocked_kicks": ("blk_kick",),
    "defensive_touchdowns": ("def_td",),
    "return_touchdowns": ("def_kr_td", "def_pr_td"),
    "points_allowed": ("pts_allow",),
    "yards_allowed": ("yds_allow",),
}
_NBA_PLAYER = {
    "points": ("pts",),
    "rebounds": ("reb",),
    "assists": ("ast",),
    "steals": ("stl",),
    "blocks": ("blk",),
    "turnovers": ("to",),
    "field_goals_made": ("fgm",),
    "field_goal_attempts": ("fga",),
    "three_pointers_made": ("tpm",),
    "three_point_attempts": ("tpa",),
    "free_throws_made": ("ftm",),
    "free_throw_attempts": ("fta",),
    "minutes": ("sp",),  # seconds; converted below
}

# Sleeper's field goal distance ranges (inclusive). A bucket's distances are treated as evenly
# spread, so its expected kicks score exactly when it lies inside one of the league's brackets.
_KICK_BUCKETS = {"0_19": (0, 19), "20_29": (20, 29), "30_39": (30, 39), "40_49": (40, 49)}
_KICK_BUCKETS["50p"] = (50, 65)

# ESPN calls kickers "PK"; Sleeper calls them "K".
_KICKER_POSITIONS = {"K", "PK"}
_ROW_HAS_POINTS = {"NFL": "pts_ppr", "NBA": "pts"}
_STATE_TTL_SECONDS = 6 * 3600.0
# Stats a league may score that Sleeper doesn't project but that almost never happen, so a
# projection without them is fine and isn't worth warning about (they count as zero).
_RARE_STATS = {"kick_return_touchdowns"}
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
_WRONG_GAME = "Sleeper's projection is for a different game than the one scheduled"


def et_date(start_time: datetime) -> date:
    """A game's US Eastern date, which is what Sleeper's NBA rows are dated by. Stored times are
    naive UTC; NBA games never start between midnight and 1am Eastern, so a fixed five hours back
    gives the right date in both standard and daylight time."""
    return (start_time - timedelta(hours=5)).date()


def _team(abbreviation: str) -> str:
    upper = abbreviation.upper()
    return _TEAM_ALIASES.get(upper, upper)


def _name(full_name: str) -> str:
    """A name reduced to what ESPN and Sleeper agree on: no accents, punctuation or suffixes."""
    ascii_name = unicodedata.normalize("NFKD", full_name).encode("ascii", "ignore").decode()
    words = re.sub(r"[^a-z ]", "", ascii_name.lower().replace("-", "")).split()
    return " ".join(word for word in words if word not in _SUFFIXES)


@dataclass
class _Week:
    """One week's usable projection rows, indexed for matching."""

    players: dict[tuple[str, str], list[dict[str, Any]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    defenses: dict[str, dict[str, Any]] = field(default_factory=dict)


def _build_week(sport: str, rows: list[Any]) -> _Week:
    week = _Week()
    for row in rows:
        stats, team = row.get("stats"), row.get("team")
        if not team or not isinstance(stats, dict) or stats.get(_ROW_HAS_POINTS[sport]) is None:
            continue  # Sleeper lists many players with only an ADP; those have no projection
        player = row.get("player") or {}
        if player.get("position") == "DEF":
            week.defenses[_team(team)] = row
        else:
            full_name = f"{player.get('first_name', '')} {player.get('last_name', '')}"
            week.players[(_name(full_name), _team(team))].append(row)
    return week


def _same_position(row: dict[str, Any], target: Target) -> bool:
    theirs, ours = row["player"].get("position"), target.position
    return theirs == ours or (theirs == "K" and ours in _KICKER_POSITIONS)


def _mapped(stats: dict[str, float], mapping: Mapping[str, tuple[str, ...]]) -> dict[str, float]:
    return {ours: sum(stats.get(key, 0.0) for key in keys) for ours, keys in mapping.items()}


def _kick_buckets(stats: dict[str, float]) -> list[KickBucket]:
    buckets = [
        KickBucket(low, high, stats.get(f"fgm_{name}", 0.0), stats.get(f"fgmiss_{name}", 0.0))
        for name, (low, high) in _KICK_BUCKETS.items()
    ]
    return [b for b in buckets if b.made or b.missed]


class SleeperProvider:
    name = "sleeper"
    label = "Sleeper"
    description = (
        "Matchup-aware stat projections from Sleeper (produced by Rotowire), rescored with your "
        "scoring settings. Covers fantasy-relevant players only; left out are players Sleeper "
        "doesn't project, such as those ruled out."
    )
    sports = frozenset({"NBA", "NFL"})

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        ttl_seconds: float | None = None,
    ) -> None:
        self._client = client
        self._clock = clock
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._cache: dict[tuple[Any, ...], tuple[float, Any]] = {}

    # -- fetching ------------------------------------------------------------------------------

    def _http(self) -> httpx.Client:
        if self._client is None:
            timeout = get_settings().sleeper_timeout_seconds
            self._client = httpx.Client(timeout=timeout, headers={"User-Agent": "fantasyiq"})
        return self._client

    def _get_json(self, url: str, params: dict[str, str | list[str]] | None = None) -> Any:
        try:
            response = self._http().get(url, params=params)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProjectionError(f"Sleeper could not be reached or answered badly: {exc}") from exc

    def _cached(self, key: tuple[Any, ...], ttl: float, fetch: Callable[[], Any]) -> Any:
        now = self._clock()
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None and now - hit[0] < ttl:
                return hit[1]
        value = fetch()
        with self._lock:
            self._cache[key] = (now, value)
        return value

    def _week(self, sport: str, year: int, week: int) -> _Week:
        settings = get_settings()

        def fetch() -> _Week:
            params: dict[str, str | list[str]] = {"season_type": "regular"}
            if sport == "NFL":
                params["position[]"] = list(_NFL_POSITIONS)
            url = f"{settings.sleeper_projections_url}/{sport.lower()}/{year}/{week}"
            rows = self._get_json(url, params)
            if not isinstance(rows, list):
                raise ProjectionError("Sleeper's projections came back in an unexpected shape")
            return _build_week(sport, rows)

        ttl = self._ttl if self._ttl is not None else settings.sleeper_cache_ttl_seconds
        return self._cached(("week", sport, year, week), ttl, fetch)

    def _nba_week(self, on: date) -> int:
        """Sleeper's NBA week number for a date: weeks run Monday to Sunday and week 1 is the one
        the season starts in. Before the season starts there is no week (0)."""
        settings = get_settings()
        state = self._cached(
            ("state", "NBA"),
            _STATE_TTL_SECONDS,
            lambda: self._get_json(f"{settings.sleeper_state_url}/nba"),
        )
        try:
            start = date.fromisoformat(state["season_start_date"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProjectionError("Sleeper's season state has no start date") from exc
        if on < start:
            return 0

        def monday(day: date) -> date:
            return day - timedelta(days=day.weekday())

        return 1 + (monday(on) - monday(start)).days // 7

    # -- matching ------------------------------------------------------------------------------

    def _find_player_row(self, week: _Week, target: Target) -> dict[str, Any] | Unavailable:
        team = _team(target.team.abbreviation) if target.team else ""
        rows = week.players.get((_name(target.name), team), [])
        if not rows:
            return Unavailable(
                "Sleeper has no projection for this player this week (it leaves out players it "
                "expects not to play, and fringe players)"
            )
        opponent = _team(target.opponent.abbreviation)
        rows = [row for row in rows if _team(row.get("opponent") or "") == opponent]
        if target.sport == "NBA" and rows:
            day = et_date(target.game.start_time)
            rows = [r for r in rows if abs((date.fromisoformat(r["date"]) - day).days) <= 1]
            rows.sort(key=lambda r: abs((date.fromisoformat(r["date"]) - day).days))
            rows = rows[:1]
        if len(rows) > 1:
            rows = [r for r in rows if _same_position(r, target)] or rows
        if len(rows) != 1:
            return Unavailable(_WRONG_GAME)
        return rows[0]

    def _find_defense_row(self, week: _Week, target: Target) -> dict[str, Any] | Unavailable:
        row = week.defenses.get(_team(target.team.abbreviation)) if target.team else None
        if row is None:
            return Unavailable("Sleeper has no projection for this defense this week")
        if _team(row.get("opponent") or "") != _team(target.opponent.abbreviation):
            return Unavailable(_WRONG_GAME)
        return row

    # -- projecting ----------------------------------------------------------------------------

    def _stat_projection(
        self,
        row: dict[str, Any],
        *,
        kind: str,
        sport: str,
        position: str | None,
        config: ScoringConfig,
    ) -> StatProjection:
        sleeper_stats = {k: v for k, v in row["stats"].items() if isinstance(v, int | float)}
        kicks: list[KickBucket] = []
        mapping: Mapping[str, tuple[str, ...]]
        if kind == "defense":
            mapping = _NFL_DEFENSE
            weighted = [s for s, w in config.defense_weights.items() if w]
            supported = set(mapping)
        else:
            mapping = _NFL_PLAYER if sport == "NFL" else _NBA_PLAYER
            weighted = [s for s, w in config.player_weights.items() if w]
            supported = set(mapping) | set(player_stat_values(config.sport, {}))
            if sport == "NFL" and position in _KICKER_POSITIONS:
                kicks = _kick_buckets(sleeper_stats)
        stats = _mapped(sleeper_stats, mapping)
        if "minutes" in stats:
            stats["minutes"] /= 60
        return StatProjection(
            stats=stats,
            kicks=kicks,
            unprojected=sorted(set(weighted) - supported - _RARE_STATS),
            notes=["Projection from Sleeper (Rotowire)."],
        )

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
        sleeper_week = week if sport == "NFL" else (self._nba_week(day) if day else 0)
        if not sleeper_week:
            return []
        projections = self._week(sport, int(season[:4]), sleeper_week)
        ranked: list[RankedCandidate] = []

        if defenses:
            teams = {
                _team(t.abbreviation): t
                for t in db.scalars(select(Team).where(Team.sport == sport))
            }
            for abbreviation, row in projections.defenses.items():
                team = teams.get(abbreviation)
                if team is None:
                    continue
                stats = self._stat_projection(
                    row, kind="defense", sport=sport, position="DEF", config=config
                ).stats
                ranked.append(
                    RankedCandidate(
                        "defense", team.id, score_expected_defense(config, stats).points
                    )
                )
        else:
            ours: dict[tuple[str, str], list[Player]] = defaultdict(list)
            query = (
                select(Player, Team.abbreviation)
                .join(Team, Player.team_id == Team.id)
                .where(Player.sport == sport, Player.active.is_(True))
            )
            for player, abbreviation in db.execute(query):
                ours[(_name(player.name), _team(abbreviation))].append(player)
            for key, rows in projections.players.items():
                for row in rows:
                    if sport == "NBA" and (day is None or row.get("date") != day.isoformat()):
                        continue
                    matches = ours.get(key, [])
                    theirs = row["player"].get("position")
                    match = next((p for p in matches if p.position == theirs), None) or (
                        matches[0] if matches else None
                    )
                    if match is None or (positions and match.position not in positions):
                        continue
                    projection = self._stat_projection(
                        row, kind="player", sport=sport, position=match.position, config=config
                    )
                    points = score_expected_player(
                        config, projection.stats, projection.kicks
                    ).points
                    ranked.append(RankedCandidate("player", match.id, points, match.injury_status))

        return sorted(ranked, key=lambda c: -c.points)

    def project(
        self, db: Session, targets: Sequence[Target], config: ScoringConfig
    ) -> dict[Key, StatProjection | Unavailable]:
        by_week: dict[tuple[str, int, int], list[Target]] = defaultdict(list)
        results: dict[Key, StatProjection | Unavailable] = {}
        for target in targets:
            year = int(target.game.season[:4])
            week = (
                target.game.week
                if target.sport == "NFL"
                else self._nba_week(et_date(target.game.start_time))
            )
            if not week:
                results[target.key] = Unavailable("Sleeper has no projections for this game yet")
                continue
            by_week[(target.sport, year, week)].append(target)

        for (sport, year, week), group in by_week.items():
            projections = self._week(sport, year, week)
            for target in group:
                found = (
                    self._find_defense_row(projections, target)
                    if target.kind == "defense"
                    else self._find_player_row(projections, target)
                )
                results[target.key] = (
                    found
                    if isinstance(found, Unavailable)
                    else self._stat_projection(
                        found,
                        kind=target.kind,
                        sport=target.sport,
                        position=target.position,
                        config=config,
                    )
                )
        return results


SLEEPER = register(SleeperProvider())
