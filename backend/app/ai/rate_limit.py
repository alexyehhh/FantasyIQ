"""A simple in-process limiter guarding the AI Analyst's Gemini quota.

The free tier is tight and each request costs several Gemini calls (one per tool-call round —
a two-way comparison alone took three in testing), so an unlimited endpoint can burn a whole
day's quota in a handful of requests. This only helps a single backend process; the app runs
one uvicorn worker today, so that's enough. A multi-worker deployment would need a shared store
(Redis, already in this stack) instead of an in-memory one — not built here since nothing runs
more than one worker yet.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable


class RateLimitExceeded(RuntimeError):
    """Too many calls in one of the limiter's windows; try again after `retry_after` seconds."""

    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded; retry after {retry_after:.0f}s")


class _Window:
    """How many calls happened in the last `seconds`, aging the oldest ones out as time passes."""

    def __init__(self, limit: int, seconds: float) -> None:
        self.limit = limit
        self.seconds = seconds
        self._hits: deque[float] = deque()

    def retry_after(self, now: float) -> float | None:
        while self._hits and now - self._hits[0] >= self.seconds:
            self._hits.popleft()
        if len(self._hits) >= self.limit:
            return self.seconds - (now - self._hits[0])
        return None

    def record(self, now: float) -> None:
        self._hits.append(now)


class RateLimiter:
    """Guards calls across one or more windows (e.g. per-minute and per-day at once); the
    caller supplies the clock so tests don't need to sleep."""

    def __init__(
        self, limits: list[tuple[int, float]], *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._windows = [_Window(limit, seconds) for limit, seconds in limits]
        self._clock = clock
        self._lock = threading.Lock()

    def check(self) -> None:
        """Raises RateLimitExceeded if any window is full; otherwise counts this call in all of
        them. Checking every window before recording in any keeps a rejected call from being
        partially counted."""
        with self._lock:
            now = self._clock()
            for window in self._windows:
                retry_after = window.retry_after(now)
                if retry_after is not None:
                    raise RateLimitExceeded(retry_after)
            for window in self._windows:
                window.record(now)
