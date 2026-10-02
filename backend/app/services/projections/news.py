"""Player news for the projection model: depth charts and injury reports from Sleeper's player file.

Two things in that file move a projection and aren't in a player's box scores. The depth chart says
who is next in line when a starter is hurt (Braelon Allen is listed RB1 once Breece Hall is
doubtful), and Sleeper's injury status, which comes from Rotowire's reporting, can be ahead of the
ESPN status we sync. `Feed.for_teams` hands both to the model.

A third source is the news Gemini has read (app/services/news/): an article that says a player is
out for the team's coming game adds him to the players expected out, which frees up his
teammates' workload. What it says about a player's role is saved with the projection and shown in
its notes but doesn't move the number, because there is no history to say by how much.

Nothing is stored here: the file is fetched on demand and kept in memory for hours (Sleeper asks
for it to be fetched sparingly). News is an extra, so failing to reach Sleeper gives an empty
feed, never an error: the model then projects from box scores and ESPN's injury list alone.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Game, NewsItem, Player, Team
from app.services.projections.sleeper import _name, _team

log = logging.getLogger(__name__)

# Sleeper's injury_status values that mean the player isn't expected to play.
EXPECTED_OUT = {"out", "doubtful", "ir", "pup", "sus"}
# A failed fetch isn't retried for this long, so a Sleeper outage doesn't slow every projection.
_RETRY_AFTER_SECONDS = 120.0


@dataclass(frozen=True)
class Item:
    """What Sleeper says about one player right now."""

    position: str | None
    depth_position: str | None
    depth_order: int | None
    injury_status: str | None
    injury_note: str | None


@dataclass
class TeamNews:
    """News for the players of some teams, keyed by our player ids."""

    depth: dict[int, int] = field(default_factory=dict)
    out_by_team: dict[int, set[int]] = field(default_factory=dict)
    notes: dict[int, str] = field(default_factory=dict)
    # What Gemini read in the news about a player's coming game, by player id (see _read_news).
    read: dict[int, dict[str, object]] = field(default_factory=dict)


class Feed:
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
        self._cache: dict[str, tuple[float, dict[tuple[str, str], list[Item]] | None]] = {}

    def _http(self) -> httpx.Client:
        if self._client is None:
            timeout = max(get_settings().sleeper_timeout_seconds, 60.0)  # the file is large
            self._client = httpx.Client(timeout=timeout, headers={"User-Agent": "fantasyiq"})
        return self._client

    def _fetch(self, sport: str) -> dict[tuple[str, str], list[Item]] | None:
        url = f"{get_settings().sleeper_players_url}/{sport.lower()}"
        try:
            response = self._http().get(url)
            response.raise_for_status()
            rows = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("Sleeper player news unavailable: %s", exc)
            return None
        if not isinstance(rows, dict):
            log.warning("Sleeper player news came back in an unexpected shape")
            return None
        index: dict[tuple[str, str], list[Item]] = {}
        for row in rows.values():
            if not isinstance(row, dict) or not row.get("team") or not row.get("full_name"):
                continue
            order = row.get("depth_chart_order")
            item = Item(
                position=row.get("position"),
                depth_position=row.get("depth_chart_position"),
                depth_order=order if isinstance(order, int) else None,
                injury_status=row.get("injury_status"),
                injury_note=row.get("injury_notes") or row.get("injury_body_part"),
            )
            index.setdefault((_name(row["full_name"]), _team(row["team"])), []).append(item)
        return index

    def _players(self, sport: str) -> dict[tuple[str, str], list[Item]]:
        ttl = self._ttl if self._ttl is not None else get_settings().sleeper_players_ttl_seconds
        now = self._clock()
        with self._lock:
            hit = self._cache.get(sport)
            if hit is not None:
                age = now - hit[0]
                if age < (ttl if hit[1] is not None else _RETRY_AFTER_SECONDS):
                    return hit[1] or {}
        index = self._fetch(sport)
        with self._lock:
            self._cache[sport] = (now, index)
        return index or {}

    def for_teams(self, db: Session, sport: str, team_ids: Iterable[int]) -> TeamNews:
        """Depth chart order, expected-out players and injury notes for the players on the teams.

        Only the NFL has a depth chart here; NBA players get injury news only."""
        news = TeamNews()
        ids = [t for t in team_ids if t is not None]
        if not ids:
            return news
        index = self._players(sport)
        if index:
            self._add_sleeper(db, sport, index, ids, news)
        # Stored news is read whether or not Sleeper answered.
        _read_news(db, sport, ids, news)
        return news

    def _add_sleeper(
        self,
        db: Session,
        sport: str,
        index: dict[tuple[str, str], list[Item]],
        ids: list[int],
        news: TeamNews,
    ) -> None:
        rows = db.execute(
            select(Player, Team.abbreviation)
            .join(Team, Player.team_id == Team.id)
            .where(Player.sport == sport, Player.team_id.in_(ids), Player.active.is_(True))
        )
        for player, abbreviation in rows:
            items = index.get((_name(player.name), _team(abbreviation)), [])
            item = next((i for i in items if i.position == player.position), None) or (
                items[0] if len(items) == 1 else None
            )
            if item is None:
                continue
            if sport == "NFL" and item.depth_order is not None:
                news.depth[player.id] = item.depth_order
            status = (item.injury_status or "").lower()
            if status in EXPECTED_OUT:
                news.out_by_team.setdefault(player.team_id, set()).add(player.id)
                news.notes[player.id] = f"{item.injury_status}" + (
                    f" ({item.injury_note})" if item.injury_note else ""
                )


# What a news item can say about availability that counts as expected out, as for Sleeper's.
_NEWS_OUT = {"out", "doubtful"}


def _read_news(db: Session, sport: str, team_ids: list[int], news: TeamNews) -> None:
    """Add what Gemini read in recent news about each team's coming game: an out or doubtful
    player joins `out_by_team`, and every such fact is kept in `read`. Only news published after
    the team's last kickoff counts, so "out for Week 3" isn't still applied in Week 4, and the
    latest article about a player wins."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    since = now - timedelta(days=get_settings().news_max_age_days)
    last_kickoff = dict(
        db.execute(
            select(Team.id, func.max(Game.start_time))
            .join(Game, or_(Game.home_team_id == Team.id, Game.away_team_id == Team.id))
            .where(Team.id.in_(team_ids), Game.sport == sport, Game.start_time <= now)
            .group_by(Team.id)
        ).all()
    )
    team_of = dict(
        db.execute(select(Player.id, Player.team_id).where(Player.team_id.in_(team_ids))).all()
    )
    items = db.scalars(
        select(NewsItem)
        .where(
            NewsItem.sport == sport,
            NewsItem.status == "done",
            NewsItem.published_at >= since,
            NewsItem.facts.is_not(None),
        )
        .order_by(NewsItem.published_at)  # oldest first, so a later article overwrites an earlier
    )
    for item in items:
        for fact in item.facts or []:
            pid = fact.get("player_id")
            tid = team_of.get(pid)
            if tid is None or not fact.get("about_next_game"):
                continue
            if item.published_at < last_kickoff.get(tid, since):
                continue
            news.read[pid] = {
                "availability": fact.get("availability"),
                "role": fact.get("role"),
                "note": fact.get("note"),
                "published": item.published_at.isoformat(timespec="minutes"),
            }
    for pid, fact in news.read.items():
        if fact["availability"] in _NEWS_OUT:
            news.out_by_team.setdefault(team_of[pid], set()).add(pid)
            news.notes.setdefault(pid, f"{fact['availability']} per news")


FEED = Feed()


def team_news(db: Session, sport: str, team_ids: Iterable[int | None]) -> TeamNews:
    return FEED.for_teams(db, sport, [t for t in team_ids if t is not None])
