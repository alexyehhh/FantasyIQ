"""GET /api/v1/health/jobs: the worker's jobs, and whether any has stopped succeeding."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.models import JobRun
from app.db.session import SessionLocal, get_db
from app.main import app


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _jobs(client):
    body = client.get("/api/v1/health/jobs").json()
    return body["status"], {job["name"]: job for job in body["jobs"]}


def test_a_worker_that_has_never_run_is_degraded_and_lists_every_job(client):
    status, jobs = _jobs(client)

    assert status == "degraded"
    assert set(jobs) == {"live", "directory", "injuries", "backfill"}
    assert all(job["overdue"] and job["last_success_at"] is None for job in jobs.values())


def test_jobs_that_ran_on_time_are_ok(client, db):
    for name in ("live", "directory", "injuries", "backfill"):
        db.add(JobRun(name=name, last_attempt_at=_now(), last_success_at=_now()))
    db.flush()

    status, jobs = _jobs(client)

    assert status == "ok"
    assert not any(job["overdue"] for job in jobs.values())
    assert jobs["live"]["seconds_since_success"] < 5


def test_a_job_that_has_gone_quiet_is_overdue_and_says_why(client, db):
    interval = get_settings().worker_injuries_interval_seconds
    long_ago = _now() - timedelta(seconds=interval * 4)
    for name in ("live", "directory", "backfill"):
        db.add(JobRun(name=name, last_attempt_at=_now(), last_success_at=_now()))
    db.add(
        JobRun(
            name="injuries",
            last_attempt_at=_now(),
            last_success_at=long_ago,
            consecutive_failures=5,
            last_error="ESPNRateLimited: holding off",
        )
    )
    db.flush()

    status, jobs = _jobs(client)

    assert status == "degraded"
    assert jobs["injuries"]["overdue"] is True
    assert jobs["injuries"]["consecutive_failures"] == 5
    assert jobs["injuries"]["last_error"] == "ESPNRateLimited: holding off"
    assert jobs["live"]["overdue"] is False
