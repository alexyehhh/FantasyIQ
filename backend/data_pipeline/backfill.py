"""Bulk-ingest box scores for finished games the schedule sync already knows about.

The directory sync (`espn_directory`) records every scheduled game and marks it final
with its score once it has been played; the per-game ingest jobs load the box score for
one game at a time. This job connects them: for each finished game that has no box score
yet, run that sport's ingest job. Run it after the directory sync, e.g. once a week:

    python -m data_pipeline.backfill --sport NFL
    python -m data_pipeline.backfill --sport all --reingest

`--reingest` also reloads games that already have stats, which is how new stat columns
get filled in for old games. Every ingest upserts, so re-running is always safe. One
game failing (ESPN error, payload that doesn't reconcile) is reported and skipped; it
never stops the rest of the run.

A game counts as already loaded when it has rows in the table the current ingest job
writes last for that sport: player lines for the NBA, team defense lines for the NFL. An
NFL game whose summary has no play data therefore shows up as missing on every run and
is simply fetched again.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.db.models import Game, PlayerGameStats, TeamGameStatsNFL
from data_pipeline import nba_ingest, nfl_ingest

SPORTS = ("NBA", "NFL")
_RUNNERS: dict[str, Callable[[str], int]] = {
    "NBA": nba_ingest.run,
    "NFL": nfl_ingest.run,
}
_LOADED_MARKER = {
    "NBA": PlayerGameStats.game_id,
    "NFL": TeamGameStatsNFL.game_id,
}


@dataclass
class BackfillReport:
    sport: str
    ingested: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)


def select_games(
    db: Session, sport: str, *, reingest: bool = False, limit: int | None = None
) -> list[str]:
    """ESPN ids of finished games to ingest, oldest first."""
    stmt = (
        select(Game.external_id)
        .where(Game.sport == sport, Game.status == "final", Game.external_id.is_not(None))
        .order_by(Game.start_time, Game.id)
    )
    if not reingest:
        marker = _LOADED_MARKER[sport]
        stmt = stmt.where(~exists().where(marker == Game.id))
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(db.scalars(stmt))


def backfill(
    db: Session,
    sport: str,
    *,
    reingest: bool = False,
    limit: int | None = None,
    delay: float = 0.5,
    runner: Callable[[str], int] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> BackfillReport:
    """Ingest each selected game, pausing `delay` seconds between ESPN requests."""
    run_game = runner or _RUNNERS[sport]
    report = BackfillReport(sport)
    game_ids = select_games(db, sport, reingest=reingest, limit=limit)
    for position, game_id in enumerate(game_ids):
        if position and delay:
            sleep(delay)
        try:
            run_game(game_id)
        except Exception as exc:  # noqa: BLE001 - one bad game must not stop the run
            report.failed[game_id] = f"{type(exc).__name__}: {exc}"
        else:
            report.ingested.append(game_id)
    return report


def main() -> None:
    from app.db.session import SessionLocal

    parser = argparse.ArgumentParser(description="Ingest finished games that have no box score")
    parser.add_argument("--sport", choices=[*SPORTS, "all"], default="all")
    parser.add_argument(
        "--reingest", action="store_true", help="also reload games that already have stats"
    )
    parser.add_argument("--limit", type=int, help="ingest at most this many games per sport")
    parser.add_argument(
        "--delay", type=float, default=0.5, help="seconds to wait between ESPN requests"
    )
    args = parser.parse_args()

    failed = 0
    for sport in SPORTS if args.sport == "all" else (args.sport,):
        db = SessionLocal()
        try:
            report = backfill(
                db, sport, reingest=args.reingest, limit=args.limit, delay=args.delay
            )
        finally:
            db.close()
        print(f"{sport}: ingested {len(report.ingested)} games, {len(report.failed)} failed")
        for game_id, message in report.failed.items():
            print(f"  {game_id}: {message}")
        failed += len(report.failed)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
