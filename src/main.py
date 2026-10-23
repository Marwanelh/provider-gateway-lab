import time
import uuid
import uvicorn
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

from .core.cache import SemanticCache
from .core.router import LLMProviderRouter
from .core.telemetry import TelemetryCollector, RequestTelemetry
from .core.limiter import TokenBucketRateLimiter

app = FastAPI(
    title="High-Performance LLM Gateway & Caching Proxy",
    description="Asynchronous reverse proxy with semantic caching, multi-provider failover (Claude, GPT-4o, DeepSeek), token-bucket rate limiting, and cost telemetry.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

cache = SemanticCache(default_ttl=3600)
router = LLMProviderRouter()
telemetry = TelemetryCollector()
limiter = TokenBucketRateLimiter(capacity=50, refill_rate_per_sec=10.0)

class Message(BaseModel):
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    model: str = Field(default="claude-3-5-sonnet", description="Requested model")
    messages: List[Message]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 1000

class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[Dict[str, Any]]
    telemetry: RequestTelemetry

@app.get("/health", tags=["Monitoring"])
async def health_check() -> Dict[str, str]:
    return {"status": "healthy", "service": "llm-gateway-proxy"}

@app.get("/metrics", tags=["Observability"])
async def get_metrics() -> Dict[str, Any]:
    return telemetry.get_summary()

@app.post("/v1/chat/completions", response_model=ChatCompletionResponse, tags=["LLM Proxy"])
async def chat_completions(req: ChatCompletionRequest) -> ChatCompletionResponse:
    if not limiter.allow_request():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Token bucket depleted."
        )

    start_time = time.time()
    req_id = f"chatcmpl_{uuid.uuid4().hex[:12]}"
    prompt = " ".join([m.content for m in req.messages])
    
    # Check Semantic Cache
    cached = cache.get(prompt, req.model)
    if cached:
        latency = (time.time() - start_time) * 1000.0
        prompt_tokens = len(prompt.split())
        telemetry_record = telemetry.record_request(
            request_id=req_id,
            model=cached.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=cached.tokens,
            latency_ms=latency,
            cache_hit=True,
            fallback_triggered=False
        )
        return ChatCompletionResponse(
            id=req_id,
            created=int(time.time()),
            model=cached.model,
            choices=[{"index": 0, "message": {"role": "assistant", "content": cached.response_text}, "finish_reason": "stop"}],
            telemetry=telemetry_record
        )

    # Route through provider fallback chain
    resp_text, actual_model, completion_tokens, fallback_triggered = await router.execute_request(prompt, req.model)
    latency = (time.time() - start_time) * 1000.0
    prompt_tokens = len(prompt.split())

    # Write to Cache
    cache.set(prompt, req.model, resp_text, completion_tokens)

    telemetry_record = telemetry.record_request(
        request_id=req_id,
        model=actual_model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency,
        cache_hit=False,
        fallback_triggered=fallback_triggered
    )

    return ChatCompletionResponse(
        id=req_id,
        created=int(time.time()),
        model=actual_model,
        choices=[{"index": 0, "message": {"role": "assistant", "content": resp_text}, "finish_reason": "stop"}],
        telemetry=telemetry_record
    )

if __name__ == "__main__":
    uvicorn.run("src.main:app", host="0.0.0.0", port=8002, reload=True)
