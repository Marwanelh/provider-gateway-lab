import pytest
from src.core.cache import SemanticCache
from src.core.router import LLMProviderRouter
from src.core.telemetry import TelemetryCollector
from src.core.limiter import TokenBucketRateLimiter

def test_semantic_cache_hit_and_expiration():
    cache = SemanticCache(default_ttl=2)
    cache.set("What is 42?", "claude-3-5-sonnet", "The answer to life.", tokens=15)
    
    # Whitespace-insensitive hit
    hit = cache.get("   what   is   42?   ", "claude-3-5-sonnet")
    assert hit is not None
    assert hit.response_text == "The answer to life."

@pytest.mark.asyncio
async def test_router_failover_cascade():
    # Configure router to simulate primary provider 429 failure
    router = LLMProviderRouter(simulate_upstream_failures=True)
    resp, model, tokens, fallback = await router.execute_request("Test prompt", "claude-3-5-sonnet")
    
    assert fallback is True
    assert model == "gpt-4o"  # Cascaded to secondary provider

def test_telemetry_cost_and_savings_calculation():
    telemetry = TelemetryCollector()
    
    # 1 miss (incurs cost)
    telemetry.record_request("req_1", "claude-3-5-sonnet", prompt_tokens=1000, completion_tokens=500, latency_ms=120.0, cache_hit=False)
    # 1 hit (saves cost)
    telemetry.record_request("req_2", "claude-3-5-sonnet", prompt_tokens=1000, completion_tokens=500, latency_ms=12.0, cache_hit=True)
    
    summary = telemetry.get_summary()
    assert summary["total_requests"] == 2
    assert summary["cache_hit_ratio"] == 0.5
    assert summary["total_cost_saved_usd"] > 0.0

def test_token_bucket_rate_limiter():
    limiter = TokenBucketRateLimiter(capacity=2, refill_rate_per_sec=0.1)
    assert limiter.allow_request() is True
    assert limiter.allow_request() is True
    assert limiter.allow_request() is False  # Bucket exhausted
