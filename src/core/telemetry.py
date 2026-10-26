import math

from pydantic import BaseModel, Field


class RequestTelemetry(BaseModel):
    request_id: str
    provider: str
    latency_ms: float = Field(ge=0)
    cache_hit: bool
    retryable_failures: int = Field(ge=0)


class TelemetryCollector:
    def __init__(self) -> None:
        self.history: list[RequestTelemetry] = []

    def record(self, item: RequestTelemetry) -> None:
        self.history.append(item)

    def summary(self) -> dict[str, int | float]:
        if not self.history:
            return {
                "total_requests": 0,
                "cache_hits": 0,
                "cache_hit_ratio": 0.0,
                "requests_with_failover": 0,
            }
        latencies = sorted(item.latency_ms for item in self.history)
        hits = sum(item.cache_hit for item in self.history)
        failovers = sum(item.retryable_failures > 0 for item in self.history)
        p95_index = math.ceil(0.95 * len(latencies)) - 1
        return {
            "total_requests": len(self.history),
            "cache_hits": hits,
            "cache_hit_ratio": round(hits / len(self.history), 4),
            "requests_with_failover": failovers,
            "p50_latency_ms": latencies[(len(latencies) - 1) // 2],
            "p95_latency_ms": latencies[p95_index],
        }
