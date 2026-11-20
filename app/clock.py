"""Time sources used for cache expiry."""

import time
from typing import Protocol


class Clock(Protocol):
    """Anything that reports monotonic time in seconds."""

    def now(self) -> float:
        """Return the current monotonic time in seconds."""
        ...


class SystemClock:
    """Clock backed by :func:`time.monotonic`."""

    def now(self) -> float:
        return time.monotonic()


class FakeClock:
    """Manually advanced clock for deterministic local testing."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds
