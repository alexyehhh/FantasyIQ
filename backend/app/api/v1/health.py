"""Health check endpoints.

`/health` exists so we have one real, testable endpoint from the very first
milestone: the frontend can call it to confirm the stack is wired up,
and CI can call it to confirm the container actually boots.

`/health/jobs` reports the background worker's jobs (data_pipeline/worker.py): when each last
succeeded and whether any is overdue, so data that has stopped updating is visible.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import JobRun
from app.db.session import get_db
from app.schemas.players import UTCDatetime

router = APIRouter()

# A job is overdue once it has gone this many intervals (plus a minute) without succeeding.
_OVERDUE_AFTER_INTERVALS = 3


@router.get("/health")
def get_health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "environment": settings.environment,
    }


class JobHealth(BaseModel):
    name: str
    interval_seconds: float
    last_success_at: UTCDatetime | None
    seconds_since_success: float | None
    consecutive_failures: int
    last_error: str | None
    overdue: bool


class JobsHealth(BaseModel):
    status: str  # "ok" when every job is on time, else "degraded"
    jobs: list[JobHealth]


@router.get("/health/jobs", response_model=JobsHealth)
def get_jobs_health(
    db: Session = Depends(get_db),  # noqa: B008 — idiomatic FastAPI DI
) -> JobsHealth:
    # Imported here: the worker module pulls in the whole ingestion stack, which the rest of the
    # API has no need to load.
    from data_pipeline.worker import job_intervals

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    runs = {run.name: run for run in db.scalars(select(JobRun))}
    jobs = []
    for name, interval in job_intervals(get_settings()).items():
        run = runs.get(name)
        succeeded = run.last_success_at if run else None
        age = (now - succeeded).total_seconds() if succeeded else None
        jobs.append(
            JobHealth(
                name=name,
                interval_seconds=interval,
                last_success_at=succeeded,
                seconds_since_success=age,
                consecutive_failures=run.consecutive_failures if run else 0,
                last_error=run.last_error if run else None,
                overdue=age is None or age > interval * _OVERDUE_AFTER_INTERVALS + 60,
            )
        )
    return JobsHealth(
        status="degraded" if any(job.overdue for job in jobs) else "ok", jobs=jobs
    )
