"""A minimal in-memory rate limiter.

Split out of main.py for two reasons: it has no FastAPI dependency, so it
can be unit-tested directly (see tests/test_rate_limiter.py) without
booting an ASGI app, and it's a distinct responsibility from request
routing - single-purpose modules are easier to review and reuse.
"""

from __future__ import annotations

import time
from collections import defaultdict

_WINDOW_SECONDS = 60.0
#: Sweep for idle clients every N calls rather than every call, so cleanup
#: cost is amortized instead of paid (as an O(clients) scan) on every
#: single request.
_SWEEP_INTERVAL = 200


class FixedWindowRateLimiter:
    """Per-client request cap over a rolling window.

    Deliberately simple (in-memory, single-process) for a hackathon demo.
    A multi-instance deployment would swap this for a shared store (e.g.
    Redis) without touching any calling code - `allow` is the only method
    callers depend on.

    Every `_SWEEP_INTERVAL` calls, `allow` also evicts client keys with no
    hits left in the current window, so memory tracks currently-active
    clients rather than every client the process has seen since it
    started - relevant for a service meant to run for the length of a
    tournament, not a quick demo restart.
    """

    def __init__(self, limit_per_minute: int) -> None:
        """Initializes the limiter.

        Args:
            limit_per_minute: Maximum requests allowed per client per
                rolling 60-second window.
        """
        self._limit = limit_per_minute
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._calls_since_sweep = 0

    def allow(self, client_key: str, now: float | None = None) -> bool:
        """Records one request attempt and reports whether it's allowed.

        Args:
            client_key: Identifier for the caller, e.g. an IP address.
            now: Injectable clock for tests; defaults to `time.monotonic()`.

        Returns:
            True if the client is under its limit for the current window,
            False if this request should be rejected (e.g. with HTTP 429).
        """
        now = time.monotonic() if now is None else now

        hits = [t for t in self._hits[client_key] if t > now - _WINDOW_SECONDS]
        hits.append(now)
        self._hits[client_key] = hits

        self._calls_since_sweep += 1
        if self._calls_since_sweep >= _SWEEP_INTERVAL:
            self._evict_idle(now)
            self._calls_since_sweep = 0

        return len(hits) <= self._limit

    def active_client_count(self) -> int:
        """Returns the number of client keys currently tracked.

        Exists mainly so tests can assert that idle clients actually get
        evicted, not just that `allow` still returns the right bool.
        """
        return len(self._hits)

    def _evict_idle(self, now: float) -> None:
        """Drops client keys with no hits inside the current window.

        Args:
            now: Reference time to measure the window against.
        """
        window_start = now - _WINDOW_SECONDS
        stale_keys = [key for key, hits in self._hits.items() if not any(t > window_start for t in hits)]
        for key in stale_keys:
            del self._hits[key]
