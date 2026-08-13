"""Token-bucket rate limiter.

Enforces a maximum number of provider calls per period. ``acquire`` raises
:class:`ProviderRateLimitError` when the limit is exceeded (rather than
blocking), so callers can apply their own backoff policy.
"""

from __future__ import annotations

import time
from threading import Lock

from market_core.providers.errors import ProviderRateLimitError


class RateLimiter:
    """Token-bucket limiter with a fixed refill rate."""

    def __init__(self, max_requests: int, period_seconds: float = 1.0) -> None:
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if period_seconds <= 0:
            raise ValueError("period_seconds must be positive")
        self._max = float(max_requests)
        self._period = period_seconds
        self._tokens = self._max
        self._last_refill = time.monotonic()
        self._lock = Lock()

    def acquire(self) -> None:
        """Consume one token, or raise :class:`ProviderRateLimitError`."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._max, self._tokens + elapsed * (self._max / self._period))
            self._last_refill = now
            if self._tokens < 1.0:
                raise ProviderRateLimitError("rate limit exceeded")
            self._tokens -= 1.0
