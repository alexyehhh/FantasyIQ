"""Unit tests for app/ai/rate_limit.py's in-process limiter."""

import pytest

from app.ai.rate_limit import RateLimiter, RateLimitExceeded


def _clock(times):
    """A fake clock that returns each value in `times` in turn."""
    values = iter(times)
    return lambda: next(values)


def test_allows_calls_up_to_the_limit():
    limiter = RateLimiter([(3, 60)], clock=_clock([0, 0, 0]))

    for _ in range(3):
        limiter.check()  # doesn't raise


def test_the_call_over_the_limit_raises():
    limiter = RateLimiter([(2, 60)], clock=_clock([0, 0, 10]))

    limiter.check()
    limiter.check()
    with pytest.raises(RateLimitExceeded) as excinfo:
        limiter.check()
    assert excinfo.value.retry_after == pytest.approx(50.0)


def test_a_window_ages_out_after_enough_time_passes():
    limiter = RateLimiter([(1, 60)], clock=_clock([0, 61]))

    limiter.check()
    limiter.check()  # doesn't raise: the first call is more than 60s in the past


def test_the_smallest_window_governs():
    limiter = RateLimiter([(1, 60), (1000, 86400)], clock=_clock([0, 0]))

    limiter.check()
    with pytest.raises(RateLimitExceeded):
        limiter.check()  # the per-minute window (limit 1) blocks even though the daily one has room


def test_a_rejected_call_is_not_counted():
    # If a rejected call were still recorded, a second try right after would also be rejected
    # even once the first window has room again.
    calls = iter([0, 0, 61])
    limiter = RateLimiter([(1, 60)], clock=lambda: next(calls))

    limiter.check()
    with pytest.raises(RateLimitExceeded):
        limiter.check()
    limiter.check()  # doesn't raise: only one real call was ever recorded
