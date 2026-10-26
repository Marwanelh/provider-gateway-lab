import asyncio

import pytest
from fastapi.testclient import TestClient

from src.core.cache import ExactResponseCache
from src.core.limiter import TokenBucketRateLimiter
from src.core.router import DemoProvider, ProviderRouter
from src.core.telemetry import RequestTelemetry, TelemetryCollector
from src.main import app, cache, telemetry


def test_cache_key_covers_response_affecting_fields_and_expiration():
    now = [100.0]
    local_cache = ExactResponseCache(default_ttl=10, clock=lambda: now[0])
    first = {"messages": ["hello"], "temperature": 0.2}
    second = {"messages": ["hello"], "temperature": 0.8}
    assert local_cache.key(first) != local_cache.key(second)

    key = local_cache.key(first)
    local_cache.set(key, {"output": "cached"})
    assert local_cache.get(key) == {"output": "cached"}
    now[0] = 110.0
    assert local_cache.get(key) is None


@pytest.mark.asyncio
async def test_router_fails_over_only_after_retryable_provider_error():
    router = ProviderRouter(
        [DemoProvider("unavailable", fail=True), DemoProvider("healthy")]
    )

    result, failures = await router.complete("hello", None, 100)

    assert result.provider == "healthy"
    assert failures == 1


@pytest.mark.asyncio
async def test_rate_limiter_is_safe_under_concurrent_requests():
    limiter = TokenBucketRateLimiter(capacity=2, refill_rate_per_second=0)
    decisions = await asyncio.gather(*(limiter.allow() for _ in range(5)))
    assert decisions.count(True) == 2
    assert decisions.count(False) == 3


def test_telemetry_reports_observed_counts_without_cost_estimates():
    collector = TelemetryCollector()
    collector.record(
        RequestTelemetry(
            request_id="one",
            provider="demo",
            latency_ms=10,
            cache_hit=False,
            retryable_failures=1,
        )
    )
    collector.record(
        RequestTelemetry(
            request_id="two",
            provider="demo",
            latency_ms=2,
            cache_hit=True,
            retryable_failures=0,
        )
    )
    summary = collector.summary()
    assert summary["cache_hit_ratio"] == 0.5
    assert summary["requests_with_failover"] == 1
    assert summary["p95_latency_ms"] == 10
    assert "total_spend_usd" not in summary


def test_api_validates_requests_and_serves_exact_cache_hits():
    cache.clear()
    telemetry.history.clear()
    client = TestClient(app)
    payload = {
        "messages": [{"role": "user", "content": "Explain safe retries"}],
        "temperature": 0.2,
        "max_output_chars": 200,
    }

    first = client.post("/v1/responses", json=payload)
    second = client.post("/v1/responses", json=payload)

    assert first.status_code == 200
    assert first.json()["telemetry"]["cache_hit"] is False
    assert second.json()["telemetry"]["cache_hit"] is True
    assert second.json()["output"] == first.json()["output"]

    invalid = client.post(
        "/v1/responses",
        json={"messages": [{"role": "tool", "content": "invalid"}]},
    )
    assert invalid.status_code == 422
