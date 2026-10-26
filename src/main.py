import time
import uuid
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from .core.cache import ExactResponseCache
from .core.limiter import TokenBucketRateLimiter
from .core.router import DemoProvider, ProviderRouter, RetryableProviderError
from .core.telemetry import RequestTelemetry, TelemetryCollector


app = FastAPI(
    title="Provider Gateway Lab",
    description="A local reference implementation for validated requests, exact caching, rate limiting, retryable failover, and telemetry.",
    version="2.0.0",
)
cache = ExactResponseCache(default_ttl=300)
router = ProviderRouter([DemoProvider("demo-primary"), DemoProvider("demo-backup")])
telemetry = TelemetryCollector()
limiter = TokenBucketRateLimiter(capacity=30, refill_rate_per_second=5)


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=10_000)


class GatewayRequest(BaseModel):
    provider: str | None = Field(default=None, max_length=100)
    messages: list[Message] = Field(min_length=1, max_length=100)
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_output_chars: int = Field(default=1_000, ge=1, le=10_000)


class GatewayResponse(BaseModel):
    id: str
    provider: str
    output: str
    telemetry: RequestTelemetry


def request_payload(request: GatewayRequest) -> dict[str, Any]:
    return request.model_dump(mode="json")


@app.get("/health", tags=["monitoring"])
async def health_check() -> dict[str, str]:
    return {"status": "healthy", "service": "provider-gateway-lab"}


@app.get("/metrics", tags=["telemetry"])
async def get_metrics() -> dict[str, int | float]:
    return telemetry.summary()


@app.post("/v1/responses", response_model=GatewayResponse, tags=["gateway"])
async def create_response(request: GatewayRequest) -> GatewayResponse:
    if not await limiter.allow():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limit exceeded",
        )

    started = time.perf_counter()
    request_id = f"response_{uuid.uuid4().hex[:12]}"
    key = ExactResponseCache.key(request_payload(request))
    cached = cache.get(key)
    if cached:
        item = RequestTelemetry(
            request_id=request_id,
            provider=cached["provider"],
            latency_ms=(time.perf_counter() - started) * 1_000,
            cache_hit=True,
            retryable_failures=0,
        )
        telemetry.record(item)
        return GatewayResponse(
            id=request_id,
            provider=cached["provider"],
            output=cached["output"],
            telemetry=item,
        )

    prompt = "\n".join(
        f"{message.role}: {message.content}" for message in request.messages
    )
    try:
        result, failures = await router.complete(
            prompt, request.provider, request.max_output_chars
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RetryableProviderError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    cache.set(key, {"provider": result.provider, "output": result.text})
    item = RequestTelemetry(
        request_id=request_id,
        provider=result.provider,
        latency_ms=(time.perf_counter() - started) * 1_000,
        cache_hit=False,
        retryable_failures=failures,
    )
    telemetry.record(item)
    return GatewayResponse(
        id=request_id,
        provider=result.provider,
        output=result.text,
        telemetry=item,
    )


if __name__ == "__main__":
    uvicorn.run("src.main:app", host="0.0.0.0", port=8002)
