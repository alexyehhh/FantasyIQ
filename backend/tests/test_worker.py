"""The background worker's scheduler and leader election (data_pipeline/worker.py).

The scheduler tests share one connection whose outer transaction is rolled back at the end, so the
rows the scheduler commits to `job_runs` don't outlive the test.
"""

import threading
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.db.models import JobRun
from app.db.session import engine
from data_pipeline import worker
from data_pipeline.worker import Job, LeaderLock, Scheduler, due_at, retry_delay

T0 = datetime(2026, 9, 25, 12, 0)


@pytest.fixture
def session_factory():
    connection = engine.connect()
    outer = connection.begin()

    def make():
        return Session(bind=connection, join_transaction_mode="create_savepoint")

    try:
        yield make
    finally:
        outer.rollback()
        connection.close()


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


def _state(session_factory, name):
    with session_factory() as db:
        row = db.get(JobRun, name)
        return None if row is None else (
            row.last_attempt_at,
            row.last_success_at,
            row.consecutive_failures,
            row.last_error,
        )


def _scheduler(session_factory, jobs, clock):
    return Scheduler(jobs, session_factory=session_factory, clock=clock)


def test_retry_delay_doubles_from_one_minute_to_a_cap():
    assert [retry_delay(n) for n in (1, 2, 3, 4, 5, 6, 9)] == [
        timedelta(minutes=m) for m in (1, 2, 4, 8, 15, 15, 15)
    ]


def test_a_job_that_never_ran_is_due_and_one_that_did_waits_its_interval():
    job = Job("j", timedelta(hours=1), lambda: None)

    assert due_at(job, None) == datetime.min
    ran = JobRun(name="j", last_attempt_at=T0, last_success_at=T0, consecutive_failures=0)
    assert due_at(job, ran) == T0 + timedelta(hours=1)


def test_a_failing_job_retries_on_the_backoff_not_its_interval():
    job = Job("j", timedelta(hours=6), lambda: None)
    failing = JobRun(name="j", last_attempt_at=T0, last_success_at=None, consecutive_failures=3)

    assert due_at(job, failing) == T0 + timedelta(minutes=4)


def test_jobs_run_when_due_and_are_recorded(session_factory):
    runs = []
    clock = Clock()
    job = Job("j-ok", timedelta(minutes=10), lambda: runs.append(1))
    scheduler = _scheduler(session_factory, [job], clock)

    assert scheduler.run_due() == ["j-ok"]
    assert _state(session_factory, "j-ok") == (T0, T0, 0, None)

    clock.now = T0 + timedelta(minutes=9)
    assert scheduler.run_due() == []  # not yet

    clock.now = T0 + timedelta(minutes=10)
    assert scheduler.run_due() == ["j-ok"]
    assert len(runs) == 2


def test_a_restart_does_not_rerun_jobs_that_ran_recently(session_factory):
    runs = []
    clock = Clock()
    job = Job("j-restart", timedelta(hours=6), lambda: runs.append(1))
    _scheduler(session_factory, [job], clock).run_due()

    clock.now = T0 + timedelta(minutes=1)
    second_life = _scheduler(session_factory, [job], clock)  # a fresh process, no memory

    assert second_life.run_due() == []
    assert len(runs) == 1


def test_a_failing_job_is_recorded_retried_with_backoff_and_does_not_stop_the_others(
    session_factory,
):
    clock = Clock()
    attempts = []

    def broken():
        attempts.append(clock.now)
        raise RuntimeError("ESPN exploded")

    other_runs = []
    jobs = [
        Job("j-broken", timedelta(hours=6), broken),
        Job("j-fine", timedelta(hours=6), lambda: other_runs.append(1)),
    ]
    scheduler = _scheduler(session_factory, jobs, clock)

    assert scheduler.run_due() == ["j-broken", "j-fine"]  # the second still ran
    assert other_runs == [1]
    attempt, success, failures, error = _state(session_factory, "j-broken")
    assert (success, failures, error) == (None, 1, "RuntimeError: ESPN exploded")

    clock.now = T0 + timedelta(seconds=59)
    assert scheduler.run_due() == []
    clock.now = T0 + timedelta(seconds=61)
    assert scheduler.run_due() == ["j-broken"]  # after 1 minute, not 6 hours
    assert _state(session_factory, "j-broken")[2] == 2

    clock.now += timedelta(minutes=2, seconds=1)
    assert scheduler.run_due() == ["j-broken"]  # then 2 minutes
    assert len(attempts) == 3


def test_a_job_that_recovers_clears_its_failures(session_factory):
    clock = Clock()
    outcomes = iter([RuntimeError("down"), None])

    def flaky():
        outcome = next(outcomes)
        if outcome:
            raise outcome

    scheduler = _scheduler(session_factory, [Job("j-flaky", timedelta(hours=1), flaky)], clock)
    scheduler.run_due()
    clock.now += timedelta(minutes=2)
    scheduler.run_due()

    _, success, failures, error = _state(session_factory, "j-flaky")
    assert (success, failures, error) == (clock.now, 0, None)


def test_a_job_is_not_rerun_at_once_when_the_database_cannot_record_it(session_factory):
    clock = Clock()
    runs = []

    class DownAfterReading:
        """Reads work, writes (the recording of a run) fail: as if the database went away."""

        def __init__(self):
            self.calls = 0

        def __call__(self):
            self.calls += 1
            if self.calls % 2 == 1:
                return session_factory()
            raise RuntimeError("database down")

    scheduler = Scheduler(
        [Job("j-nodb", timedelta(minutes=5), lambda: runs.append(1))],
        session_factory=DownAfterReading(),
        clock=clock,
    )

    scheduler.run_due()
    clock.now += timedelta(seconds=30)
    scheduler.run_due()

    assert len(runs) == 1  # without the in-memory guard it would run on every pass


def test_run_forever_survives_a_pass_that_blows_up_and_stops_when_asked():
    stop = threading.Event()
    passes = []

    class Exploding(Scheduler):
        def run_due(self, stop=None):
            passes.append(1)
            if len(passes) >= 3:
                stop_event.set()
            raise RuntimeError("database unreachable")

    stop_event = stop
    scheduler = Exploding([], poll_seconds=0.001)

    scheduler.run_forever(stop)  # returns once stopped, rather than raising

    assert len(passes) >= 3


# --- Leader election ---------------------------------------------------------------------------


def test_only_one_worker_can_be_leader_and_another_takes_over_when_it_lets_go():
    first, second = LeaderLock(), LeaderLock()
    try:
        assert first.acquire() is True
        assert second.acquire() is False  # a standby
        assert first.alive() is True
        assert second.alive() is False

        first.release()

        assert second.acquire() is True
    finally:
        first.release()
        second.release()


def test_build_lanes_keeps_live_games_apart_from_the_slow_jobs():
    from app.core.config import Settings

    live, maintenance = worker.build_lanes(Settings())

    assert [job.name for job in live._jobs] == ["live"]
    assert [job.name for job in maintenance._jobs] == ["directory", "injuries", "backfill"]
