import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class CacheEntry:
    value: dict[str, Any]
    expires_at: float


class ExactResponseCache:
    """TTL cache keyed by every request field that can affect a response."""

    def __init__(
        self, default_ttl: int = 300, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if default_ttl <= 0:
            raise ValueError("default_ttl must be positive")
        self.default_ttl = default_ttl
        self.clock = clock
        self._store: dict[str, CacheEntry] = {}

    @staticmethod
    def key(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        entry = self._store.get(key)
        if not entry:
            return None
        if self.clock() >= entry.expires_at:
            del self._store[key]
            return None
        return entry.value.copy()

    def set(self, key: str, value: dict[str, Any], ttl: int | None = None) -> None:
        lifetime = ttl if ttl is not None else self.default_ttl
        if lifetime <= 0:
            raise ValueError("ttl must be positive")
        self._store[key] = CacheEntry(value.copy(), self.clock() + lifetime)

    def clear(self) -> None:
        self._store.clear()
