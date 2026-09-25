"""Keep the box scores of live and just-finished games current.

The ingest jobs load one game at a time and the bulk `backfill` job is for old gaps, so on their
own the stats lag a game's end by however long since someone ran them. The background worker
(data_pipeline/worker.py) calls `LiveRefresher.refresh` every few seconds, and it pulls from ESPN
just the games whose stored stats can't be trusted yet:

- in progress (the stats are a running total, refreshed every cooldown while it lasts);
- started according to the schedule but not yet stored as started (the schedule sync runs rarely);
- final, but with no box score taken after the game ended (`Game.stats_final`).

A game is asked about at most once per cooldown, and one that fails is left alone for a few
minutes. When nothing is due a refresh costs one small query. The games that are due are fetched
in parallel (the ESPN client's gate still spaces the requests), then stored one at a time, each in
its own savepoint so one bad game never costs the others. Everything is idempotent: the ingest jobs
upsert.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Game
from data_pipeline import nba_ingest, nfl_ingest
from data_pipeline.espn import ESPNRateLimited

logger = logging.getLogger(__name__)

SPORTS = ("NBA", "NFL")

# The schedule can go on calling a game "scheduled" long after it was played (or if it was
# postponed); only games that started this recently are looked for.
NOT_STARTED_LOOKBACK = timedelta(hours=48)
# A finished game with no final box score is looked for this long. A longer gap is the bulk
# `backfill` job's to fill, not something a page load should take on.
UNLOADED_LOOKBACK = timedelta(days=14)
FAILURE_BACKOFF = timedelta(minutes=5)
# One NFL Sunday is at most 16 games.
MAX_GAMES_PER_PASS = 20
MAX_PARALLEL_FETCHES = 6


@dataclass(frozen=True)
class Pipeline:
    """One sport's ESPN client and ingest function: `ingest(db, *client.get_game(game_id))`."""

    make_client: Callable[[float], Any]  # timeout seconds -> client with get_game() and close()
    ingest: Callable[..., int]


PIPELINES: dict[str, Pipeline] = {
    "NBA": Pipeline(nba_ingest.ESPNNBAClient, nba_ingest.ingest_game),
    "NFL": Pipeline(nfl_ingest.ESPNNFLClient, nfl_ingest.ingest_game),
}


@dataclass
class RefreshReport:
    refreshed: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)


def _utc_now() -> datetime:
    """Naive UTC, the form the database stores."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _caused_by_rate_limit(exc: BaseException | None) -> bool:
    while exc is not None:
        if isinstance(exc, ESPNRateLimited):
            return True
        exc = exc.__cause__
    return False


def select_refreshable(db: Session, sport: str, now: datetime) -> list[str]:
    """ESPN ids of the games whose stored stats may be stale, newest first (see the module doc)."""
    stmt = (
        select(Game.external_id)
        .where(
            Game.sport == sport,
            Game.external_id.is_not(None),
            or_(
                Game.status == "in_progress",
                and_(
                    Game.status == "scheduled",
                    Game.start_time <= now,
                    Game.start_time >= now - NOT_STARTED_LOOKBACK,
                ),
                and_(
                    Game.status == "final",
                    Game.stats_final.is_(False),
                    Game.start_time >= now - UNLOADED_LOOKBACK,
                ),
            ),
        )
        .order_by(Game.start_time.desc(), Game.id)
    )
    return list(db.scalars(stmt))


class LiveRefresher:
    def __init__(
        self,
        pipelines: dict[str, Pipeline] | None = None,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._pipelines = pipelines if pipelines is not None else PIPELINES
        self._clock = clock
        self._next_attempt: dict[str, datetime] = {}
        # One pass at a time, should a second caller ever share the instance.
        self._lock = threading.Lock()

    def refresh(self, db: Session) -> RefreshReport:
        """Bring every due game up to date in the caller's session; the caller commits."""
        report = RefreshReport()
        with self._lock:
            for sport in SPORTS:
                self._refresh_sport(db, sport, report)
        return report

    def _refresh_sport(self, db: Session, sport: str, report: RefreshReport) -> None:
        now = self._clock()
        due = [
            game_id
            for game_id in select_refreshable(db, sport, now)
            if self._next_attempt.get(game_id, now) <= now
        ][:MAX_GAMES_PER_PASS]
        if not due:
            return

        settings = get_settings()
        pipeline = self._pipelines[sport]
        client = pipeline.make_client(settings.live_refresh_timeout_seconds)
        try:
            fetched = self._fetch_all(client, due)
        finally:
            client.close()

        now = self._clock()
        cooldown = timedelta(seconds=settings.live_refresh_cooldown_seconds)
        for game_id in due:
            payload = fetched[game_id]
            try:
                if isinstance(payload, Exception):
                    raise payload
                with db.begin_nested():
                    pipeline.ingest(db, *payload)
            except Exception as exc:  # noqa: BLE001 - one bad game must not stop the rest
                report.failed[game_id] = f"{type(exc).__name__}: {exc}"
                if _caused_by_rate_limit(exc):
                    # ESPN, not this game, is the problem; the gate holds every request off until
                    # it is over, so the game is simply asked again next time.
                    logger.info("Live refresh of %s game %s held off: %s", sport, game_id, exc)
                    continue
                self._next_attempt[game_id] = now + FAILURE_BACKOFF
                logger.warning("Live refresh of %s game %s failed: %s", sport, game_id, exc)
            else:
                self._next_attempt[game_id] = now + cooldown
                report.refreshed.append(game_id)
        if report.refreshed:
            logger.info("Live refresh: %s games %s", sport, ", ".join(report.refreshed))

    @staticmethod
    def _fetch_all(client: Any, game_ids: list[str]) -> dict[str, Any]:
        """Each game's parsed payload, or the exception that fetching it raised."""

        def fetch(game_id: str) -> Any:
            try:
                return client.get_game(game_id)
            except Exception as exc:  # noqa: BLE001 - reported per game by the caller
                return exc

        with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_FETCHES, len(game_ids))) as pool:
            return dict(zip(game_ids, pool.map(fetch, game_ids), strict=True))
