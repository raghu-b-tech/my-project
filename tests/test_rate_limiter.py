"""Small tests for app.rate_limiter - pure logic, injectable clock, no I/O."""

from __future__ import annotations

from app.rate_limiter import _SWEEP_INTERVAL, _WINDOW_SECONDS, FixedWindowRateLimiter


def test_allows_up_to_the_limit_then_denies() -> None:
    limiter = FixedWindowRateLimiter(limit_per_minute=2)
    t = 1000.0
    assert limiter.allow("client-a", now=t) is True
    assert limiter.allow("client-a", now=t) is True
    assert limiter.allow("client-a", now=t) is False


def test_window_rolls_forward() -> None:
    limiter = FixedWindowRateLimiter(limit_per_minute=1)
    t = 1000.0
    assert limiter.allow("client-a", now=t) is True
    assert limiter.allow("client-a", now=t) is False

    later = t + _WINDOW_SECONDS + 1
    assert limiter.allow("client-a", now=later) is True, "a fresh window should reset the count"


def test_clients_are_isolated() -> None:
    limiter = FixedWindowRateLimiter(limit_per_minute=1)
    t = 1000.0
    assert limiter.allow("client-a", now=t) is True
    assert limiter.allow("client-b", now=t) is True  # unaffected by client-a's usage


def test_idle_clients_are_evicted_not_retained_forever() -> None:
    """Regression test: the original inline limiter never dropped stale
    client keys, so `_hits` grew for the lifetime of the process. This
    proves the fix - tracked clients should reflect current activity,
    not history since process start.
    """
    limiter = FixedWindowRateLimiter(limit_per_minute=100)
    base = 5000.0

    for i in range(_SWEEP_INTERVAL - 1):
        limiter.allow(f"client-{i}", now=base)
    assert limiter.active_client_count() == _SWEEP_INTERVAL - 1

    far_future = base + _WINDOW_SECONDS * 10
    limiter.allow("client-new", now=far_future)

    assert limiter.active_client_count() == 1, "stale clients should have been swept"


def test_rejected_requests_still_count_as_activity() -> None:
    limiter = FixedWindowRateLimiter(limit_per_minute=1)
    t = 1000.0
    assert limiter.allow("client-a", now=t) is True
    assert limiter.allow("client-a", now=t) is False
    # still denied one second later, well inside the same window
    assert limiter.allow("client-a", now=t + 1) is False
