import time
from typing import Dict, Any, List
from pydantic import BaseModel, Field

# Pricing per million tokens (standard 2026 production reference)
MODEL_PRICING = {
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "deepseek-chat": {"input": 0.14, "output": 0.28}
}

class RequestTelemetry(BaseModel):
    request_id: str
    model_used: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    latency_ms: float
    cache_hit: bool
    fallback_triggered: bool

class TelemetryCollector:
    def __init__(self):
        self.history: List[RequestTelemetry] = []
        self.total_cost_saved_usd: float = 0.0

    def record_request(
        self,
        request_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        cache_hit: bool,
        fallback_triggered: bool = False
    ) -> RequestTelemetry:
        pricing = MODEL_PRICING.get(model, {"input": 2.0, "output": 8.0})
        
        if cache_hit:
            cost = 0.0
            # Cost that would have been incurred
            saved = (prompt_tokens * pricing["input"] + completion_tokens * pricing["output"]) / 1_000_000.0
            self.total_cost_saved_usd += saved
        else:
            cost = (prompt_tokens * pricing["input"] + completion_tokens * pricing["output"]) / 1_000_000.0

        item = RequestTelemetry(
            request_id=request_id,
            model_used=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            estimated_cost_usd=round(cost, 6),
            latency_ms=round(latency_ms, 2),
            cache_hit=cache_hit,
            fallback_triggered=fallback_triggered
        )
        self.history.append(item)
        return item

    def get_summary(self) -> Dict[str, Any]:
        total_reqs = len(self.history)
        if total_reqs == 0:
            return {"total_requests": 0, "cache_hit_ratio": 0.0}

        cache_hits = sum(1 for r in self.history if r.cache_hit)
        total_spend = sum(r.estimated_cost_usd for r in self.history)
        latencies = [r.latency_ms for r in self.history]
        latencies.sort()
        p95_idx = int(total_reqs * 0.95)

        return {
            "total_requests": total_reqs,
            "cache_hit_count": cache_hits,
            "cache_hit_ratio": round(cache_hits / total_reqs, 4),
            "total_spend_usd": round(total_spend, 6),
            "total_cost_saved_usd": round(self.total_cost_saved_usd, 6),
            "p50_latency_ms": latencies[total_reqs // 2],
            "p95_latency_ms": latencies[min(p95_idx, total_reqs - 1)]
        }
