import asyncio
import time
from typing import Callable


class TokenBucketRateLimiter:
    def __init__(
        self,
        capacity: float,
        refill_rate_per_second: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacity <= 0 or refill_rate_per_second < 0:
            raise ValueError("capacity must be positive and refill rate cannot be negative")
        self.capacity = capacity
        self.refill_rate = refill_rate_per_second
        self.clock = clock
        self.tokens = capacity
        self.last_refill = clock()
        self._lock = asyncio.Lock()

    async def allow(self, cost: float = 1) -> bool:
        if cost <= 0 or cost > self.capacity:
            raise ValueError("cost must be positive and no greater than capacity")
        async with self._lock:
            now = self.clock()
            elapsed = max(0, now - self.last_refill)
            self.tokens = min(
                self.capacity, self.tokens + elapsed * self.refill_rate
            )
            self.last_refill = now
            if self.tokens < cost:
                return False
            self.tokens -= cost
            return True
