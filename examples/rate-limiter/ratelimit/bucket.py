import time
from typing import Callable


class TokenBucket:
    """Classic token bucket: `capacity` tokens max, refilled at `rate` tokens per second."""

    def __init__(self, capacity: int, rate: float, clock: Callable[[], float] = time.monotonic):
        if capacity <= 0 or rate <= 0:
            raise ValueError("capacity and rate must be positive")
        self.capacity = capacity
        self.rate = rate
        self._clock = clock
        self._tokens = float(capacity)
        self._last = clock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = now - self._last
        self._tokens += int(elapsed * self.rate)
        self._last = now

    @property
    def tokens(self) -> float:
        self._refill()
        return self._tokens

    def allow(self, cost: int = 1) -> bool:
        self._refill()
        if self._tokens >= cost:
            self._tokens -= cost
            return True
        return False

    def retry_after(self, cost: int = 1) -> float:
        """Seconds until `cost` tokens will be available."""
        self._refill()
        missing = max(0.0, cost - self._tokens)
        return missing / self.rate
