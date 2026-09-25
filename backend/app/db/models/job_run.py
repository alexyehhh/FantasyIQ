"""
JobRun model.

One row per background job (see data_pipeline/worker.py) recording when it last ran and whether it
worked. The worker reads it to know what is due, so a restart doesn't rerun everything (and hit
ESPN again), and the API reports it so stale data is visible rather than silent.
"""

from datetime import datetime

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class JobRun(Base):
    __tablename__ = "job_runs"

    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    # Naive UTC, like every timestamp we store.
    last_attempt_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
