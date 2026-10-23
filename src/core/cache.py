import hashlib
import time
from typing import Dict, Any, Optional
from pydantic import BaseModel

class CachedEntry(BaseModel):
    response_text: str
    model: str
    tokens: int
    created_at: float
    ttl_seconds: int

class SemanticCache:
    """
    In-memory semantic cache with Redis compatibility.
    Normalizes whitespace and computes SHA256 fingerprints to eliminate redundant LLM calls.
    """
    def __init__(self, default_ttl: int = 3600):
        self._store: Dict[str, CachedEntry] = {}
        self.default_ttl = default_ttl

    def _generate_key(self, prompt: str, model: str) -> str:
        normalized = " ".join(prompt.lower().strip().split())
        payload = f"{model}:{normalized}"
        return hashlib.sha256(payload.encode()).hexdigest()

    def get(self, prompt: str, model: str) -> Optional[CachedEntry]:
        key = self._generate_key(prompt, model)
        entry = self._store.get(key)
        if not entry:
            return None
        
        # Check TTL expiration
        if time.time() - entry.created_at > entry.ttl_seconds:
            del self._store[key]
            return None
            
        return entry

    def set(self, prompt: str, model: str, response_text: str, tokens: int, ttl: int = None) -> None:
        key = self._generate_key(prompt, model)
        self._store[key] = CachedEntry(
            response_text=response_text,
            model=model,
            tokens=tokens,
            created_at=time.time(),
            ttl_seconds=ttl or self.default_ttl
        )

    def clear(self) -> None:
        self._store.clear()
