"""A Gemini request budget kept in the database, so it holds across restarts and processes.

The AI Analyst's limiter (app/ai/rate_limit.py) lives in one process's memory, which is fine for
an endpoint but not for a worker that restarts on every code change and would forget how much of
the day it had used. Here every request is a row in `gemini_calls`, and `reserve` refuses once
the last minute or the last 24 hours already hold as many as the limits allow.

The 24 hours roll, so the count is never lower than what Google counts for the calendar day the
quota resets on; staying under the rolling limit stays under the daily quota. A request is
counted before it is sent and stays counted if it fails, since a failed request can still use
quota.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.rate_limit import RateLimitExceeded
from app.db.models import GeminiCall


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class GeminiBudget:
    def __init__(
        self,
        model: str,
        *,
        per_minute: int,
        per_day: int,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.model = model
        self.per_minute = per_minute
        self.per_day = per_day
        self._clock = clock

    def _called_since(self, db: Session, since: datetime) -> list[datetime]:
        return list(
            db.scalars(
                select(GeminiCall.called_at)
                .where(GeminiCall.model == self.model, GeminiCall.called_at > since)
                .order_by(GeminiCall.called_at)
            )
        )

    def remaining_today(self, db: Session) -> int:
        since = self._clock() - timedelta(days=1)
        used = db.scalar(
            select(func.count())
            .select_from(GeminiCall)
            .where(GeminiCall.model == self.model, GeminiCall.called_at > since)
        )
        return max(0, self.per_day - (used or 0))

    def reserve(self, db: Session, purpose: str) -> None:
        """Counts one request, or raises RateLimitExceeded (with how long to wait) if the minute's
        or the day's limit is already used up. Commits, so the count survives the request."""
        now = self._clock()
        day = self._called_since(db, now - timedelta(days=1))
        if len(day) >= self.per_day:
            raise RateLimitExceeded(
                (day[len(day) - self.per_day] + timedelta(days=1) - now).total_seconds()
            )
        minute = [t for t in day if t > now - timedelta(minutes=1)]
        if len(minute) >= self.per_minute:
            raise RateLimitExceeded(
                (minute[len(minute) - self.per_minute] + timedelta(minutes=1) - now).total_seconds()
            )
        db.add(GeminiCall(model=self.model, purpose=purpose, called_at=now))
        db.commit()
