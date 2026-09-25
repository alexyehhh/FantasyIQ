"""The background worker: the only process that calls ESPN.

Run it as its own service (`python -m data_pipeline.worker`, the `worker` service in
docker-compose.yml). The API never calls ESPN, so how many people use the app has no effect on how
hard ESPN is hit, or on how fast a page loads. Two lanes of jobs run in their own threads, so a
long roster sync can't hold up a live game:

    live        every ~15 s   stats of games in progress or just finished (refresh.py)
    directory   every 6 h     teams, rosters, schedule and injuries (espn_directory.py)
    injuries    every 15 min  just the injury report, two requests
    backfill    every hour    box scores of finished games older than the live refresh looks back

Intervals come from the settings (`WORKER_*_INTERVAL_SECONDS`). Every request to ESPN goes through
one paced gate (data_pipeline/espn.py) that also stops asking for a while when ESPN answers 429/503.

Staying up: a job that raises is logged, recorded in `job_runs` and retried after 1, 2, 4 ... up to
15 minutes; nothing a job does can stop the worker or the other jobs. What ran when lives in the
database, so a restart (or a crash loop) doesn't rerun everything and hit ESPN again, and
`GET /api/v1/health/jobs` shows anything that has gone stale.

Running more than one copy is safe: they elect a leader with a Postgres advisory lock, and only the
leader runs jobs. The others wait, and take over within seconds if the leader dies.
"""

from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import Engine, select, text

from app.core.config import Settings, get_settings
from app.db.models import JobRun
from app.db.session import SessionLocal, engine
from data_pipeline import backfill as backfill_job
from data_pipeline import espn_directory
from data_pipeline.espn import ESPNClient
from data_pipeline.refresh import SPORTS, LiveRefresher

logger = logging.getLogger("worker")

RETRY_BASE = timedelta(seconds=60)
RETRY_MAX = timedelta(minutes=15)
# Any number; it only has to be the same in every worker.
LEADER_LOCK_KEY = 7_046_001


def _utc_now() -> datetime:
    """Naive UTC, the form the database stores."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class Job:
    name: str
    interval: timedelta
    run: Callable[[], None]


def retry_delay(failures: int) -> timedelta:
    """How long to wait after the `failures`-th failure in a row: 1, 2, 4 ... minutes, to 15."""
    return min(RETRY_BASE * 2 ** (failures - 1), RETRY_MAX)


def due_at(job: Job, state: JobRun | None) -> datetime:
    """When a job should next run, given what the database says about its last run."""
    if state is None or state.last_attempt_at is None:
        return datetime.min
    if state.consecutive_failures:
        return state.last_attempt_at + retry_delay(state.consecutive_failures)
    return state.last_attempt_at + job.interval


class Scheduler:
    """Runs a list of jobs, one at a time, each when it is due."""

    def __init__(
        self,
        jobs: Sequence[Job],
        *,
        session_factory: Callable[[], object] = SessionLocal,
        clock: Callable[[], datetime] = _utc_now,
        poll_seconds: float = 5.0,
    ) -> None:
        self._jobs = list(jobs)
        self._session_factory = session_factory
        self._clock = clock
        self._poll_seconds = poll_seconds
        # A second guard beside the database: even if the database can't be written (so a job
        # would look due again at once), a job isn't rerun before this.
        self._not_before: dict[str, datetime] = {}

    def run_due(self, stop: threading.Event | None = None) -> list[str]:
        """Run every job that is due; returns their names."""
        now = self._clock()
        with self._session_factory() as db:  # type: ignore[attr-defined]
            states = {
                row.name: row
                for row in db.scalars(
                    select(JobRun).where(JobRun.name.in_([job.name for job in self._jobs]))
                )
            }
        ran = []
        for job in self._jobs:
            if stop is not None and stop.is_set():
                break
            due = max(due_at(job, states.get(job.name)), self._not_before.get(job.name, now))
            if due <= now:
                self._execute(job)
                ran.append(job.name)
        return ran

    def _execute(self, job: Job) -> None:
        started = self._clock()
        error = None
        try:
            job.run()
        except Exception as exc:  # noqa: BLE001 - nothing a job does may stop the worker
            error = f"{type(exc).__name__}: {exc}"
            logger.exception("Job %s failed", job.name)
        try:
            failures = self._record(job, started, error)
        except Exception:  # noqa: BLE001 - e.g. the database is down; the guard below still holds
            logger.exception("Could not record the run of job %s", job.name)
            failures = 1 if error else 0
        wait = retry_delay(failures) if error else job.interval
        self._not_before[job.name] = started + wait

    def _record(self, job: Job, started: datetime, error: str | None) -> int:
        """Store the outcome; returns the job's failures in a row."""
        with self._session_factory() as db:  # type: ignore[attr-defined]
            state = db.get(JobRun, job.name)
            if state is None:
                state = JobRun(name=job.name, consecutive_failures=0)
                db.add(state)
            state.last_attempt_at = started
            if error is None:
                state.last_success_at = started
                state.consecutive_failures = 0
                state.last_error = None
            else:
                state.consecutive_failures = (state.consecutive_failures or 0) + 1
                state.last_error = error[:2000]
            db.commit()
            return state.consecutive_failures

    def run_forever(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                self.run_due(stop)
            except Exception:  # noqa: BLE001 - e.g. the database is unreachable: wait, then retry
                logger.exception("Scheduler pass failed")
            stop.wait(self._poll_seconds)


# --- The jobs ----------------------------------------------------------------------------------


def run_live(refresher: LiveRefresher) -> None:
    with SessionLocal() as db:
        try:
            refresher.refresh(db)
            db.commit()
        except Exception:
            db.rollback()
            raise


def run_injuries() -> None:
    client = ESPNClient(timeout=get_settings().nfl_api_timeout_seconds)
    errors = []
    try:
        for sport in espn_directory.LEAGUES:
            with SessionLocal() as db:
                try:
                    espn_directory.refresh_injuries(db, client, sport)
                    db.commit()
                except Exception as exc:  # noqa: BLE001 - the other sport should still update
                    db.rollback()
                    errors.append(f"{sport}: {type(exc).__name__}: {exc}")
    finally:
        client.close()
    if errors:
        raise RuntimeError("; ".join(errors))


def run_directory() -> None:
    for report in espn_directory.run(list(espn_directory.LEAGUES)):
        logger.info("Directory sync: %s", report.summary())


def run_backfill(games_per_sport: int) -> None:
    failed = []
    for sport in SPORTS:
        with SessionLocal() as db:
            report = backfill_job.backfill(
                db, sport, limit=games_per_sport, delay=0.0, by_marker=False
            )
        failed += [f"{sport} {game_id}: {message}" for game_id, message in report.failed.items()]
    if failed:
        raise RuntimeError("; ".join(failed))


def _seconds(value: float) -> timedelta:
    return timedelta(seconds=value)


def job_intervals(settings: Settings) -> dict[str, float]:
    """Each job's interval in seconds; the API uses it to tell when one is overdue."""
    return {
        "live": settings.worker_live_interval_seconds,
        "directory": settings.worker_directory_interval_seconds,
        "injuries": settings.worker_injuries_interval_seconds,
        "backfill": settings.worker_backfill_interval_seconds,
    }


def build_lanes(settings: Settings) -> list[Scheduler]:
    intervals = job_intervals(settings)
    refresher = LiveRefresher()
    live = Scheduler(
        [Job("live", _seconds(intervals["live"]), lambda: run_live(refresher))],
        poll_seconds=min(5.0, intervals["live"]),
    )
    maintenance = Scheduler(
        [
            Job("directory", _seconds(intervals["directory"]), run_directory),
            Job("injuries", _seconds(intervals["injuries"]), run_injuries),
            Job(
                "backfill",
                _seconds(intervals["backfill"]),
                lambda: run_backfill(settings.worker_backfill_games_per_run),
            ),
        ],
        poll_seconds=30.0,
    )
    return [live, maintenance]


# --- Leader election ---------------------------------------------------------------------------


class LeaderLock:
    """A Postgres session-level advisory lock on a connection of its own. Held while this worker
    is the leader; released by `release`, or when the process exits or the connection drops, which
    lets another worker take over."""

    def __init__(self, db_engine: Engine = engine) -> None:
        self._engine = db_engine
        self._conn = None

    def acquire(self) -> bool:
        conn = self._engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            got = conn.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": LEADER_LOCK_KEY}
            ).scalar()
        except Exception:
            conn.close()
            raise
        if got:
            self._conn = conn
        else:
            conn.close()
        return bool(got)

    def alive(self) -> bool:
        if self._conn is None:
            return False
        try:
            self._conn.execute(text("SELECT 1"))
            return True
        except Exception:  # noqa: BLE001 - a dead connection means the lock is gone
            return False

    def release(self) -> None:
        """Give up leadership. Closing a pooled connection only returns it to the pool, still
        holding the lock, so unlock explicitly and then throw the connection away."""
        conn, self._conn = self._conn, None
        if conn is None:
            return
        try:
            conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LEADER_LOCK_KEY})
        except Exception:  # noqa: BLE001 - a dead connection has already lost the lock
            logger.debug("Unlocking the leader connection failed", exc_info=True)
        finally:
            conn.invalidate()
            conn.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per ESPN request is noise
    settings = get_settings()
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    logger.info("Worker started; intervals (s): %s", job_intervals(settings))

    while not stop.is_set():
        lock = LeaderLock()
        try:
            leader = lock.acquire()
        except Exception:  # noqa: BLE001 - the database isn't reachable yet or right now
            logger.exception("Could not reach the database to elect a leader")
            stop.wait(15)
            continue
        if not leader:
            logger.info("Another worker is the leader; waiting")
            stop.wait(15)
            continue

        logger.info("This worker is the leader; running jobs")
        lanes_stop = threading.Event()
        threads = [
            threading.Thread(target=lane.run_forever, args=(lanes_stop,), daemon=True)
            for lane in build_lanes(settings)
        ]
        for thread in threads:
            thread.start()
        while not stop.is_set() and lock.alive():
            stop.wait(5)
        lanes_stop.set()
        lock.release()
        for thread in threads:
            thread.join(timeout=5)
        if not stop.is_set():
            logger.warning("Lost the leader connection; electing again")
    logger.info("Worker stopped")


if __name__ == "__main__":
    main()
