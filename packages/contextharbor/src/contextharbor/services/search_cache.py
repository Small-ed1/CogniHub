from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Dict, Tuple

class SearchCache:
    """Simple TTL cache for search results."""
    
    def __init__(self, ttl_minutes: int = 30):
        self.ttl = ttl_minutes * 60  # Convert to seconds
        self.cache: Dict[str, Tuple[float, list[str]]] = {}
    
    def _make_key(self, query: str, n: int) -> str:
        """Create cache key from query and limit."""
        content = f"{query}:{n}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def get(self, query: str, n: int) -> list[str] | None:
        """Get cached results if not expired."""
        key = self._make_key(query, n)
        if key not in self.cache:
            return None
        
        timestamp, results = self.cache[key]
        if time.time() - timestamp > self.ttl:
            del self.cache[key]
            return None
        
        return results
    
    def set(self, query: str, n: int, results: list[str]) -> None:
        """Cache search results."""
        key = self._make_key(query, n)
        self.cache[key] = (time.time(), results)
    
    def cleanup(self) -> None:
        """Remove expired entries."""
        now = time.time()
        expired_keys = [
            key for key, (ts, _) in self.cache.items()
            if now - ts > self.ttl
        ]
        for key in expired_keys:
            del self.cache[key]


class RateLimiter:
    """Simple rate limiter per provider with async locking."""
    
    def __init__(self, min_interval_seconds: int = 2):
        self.min_interval = min_interval_seconds
        self.last_request: Dict[str, float] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
    
    async def wait_if_needed(self, provider: str) -> None:
        """Wait if provider was called too recently (thread-safe)."""
        # Create lock for this provider if not exists
        if provider not in self._locks:
            self._locks[provider] = asyncio.Lock()
        
        async with self._locks[provider]:
            now = time.time()
            last_time = self.last_request.get(provider, 0)
            
            elapsed = now - last_time
            if elapsed < self.min_interval:
                wait_time = self.min_interval - elapsed
                await asyncio.sleep(wait_time)
            
            self.last_request[provider] = time.time()


# Global instances
_search_cache = SearchCache(ttl_minutes=30)
_rate_limiter = RateLimiter(min_interval_seconds=2)

def get_search_cache() -> SearchCache:
    """Get the global search cache instance."""
    return _search_cache

def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter instance."""
    try:
        from .. import config as ch_config

        # Keep runtime-configurable without re-instantiating.
        _rate_limiter.min_interval = float(ch_config.config.search_min_interval_seconds)
    except Exception:
        pass
    return _rate_limiter
