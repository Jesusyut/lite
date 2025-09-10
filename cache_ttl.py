import os
import json
import threading
import time
from typing import Any, Callable, Optional

import redis

# REDIS_URL example: redis://default:password@host:port/0
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
_r = redis.from_url(REDIS_URL, decode_responses=True)

# In-process locks to coalesce concurrent fetches for the same key
_locks = {}
def _lock_for(key: str) -> threading.Lock:
    _locks.setdefault(key, threading.Lock())
    return _locks[key]

def cache_get(key: str) -> Optional[Any]:
    """Get JSON value from Redis by key."""
    val = _r.get(key)
    if val is None:
        return None
    try:
        return json.loads(val)
    except Exception:
        return None

def cache_set(key: str, obj: Any, ttl_seconds: int) -> None:
    """Set JSON value with TTL."""
    _r.setex(key, ttl_seconds, json.dumps(obj))

def cached_fetch(key: str, ttl_seconds: int, fetch_fn: Callable[[], Any]) -> Any:
    """
    Write-through cache with request coalescing.
    The first caller fetches & stores; concurrent callers with the same key wait and read.
    """
    lock = _lock_for(key)
    with lock:
        hit = cache_get(key)
        if hit is not None:
            return hit
        data = fetch_fn()
        cache_set(key, data, ttl_seconds)
        return data

def stale_while_revalidate(key: str, soft_ttl: int, hard_ttl: int, fetch_fn: Callable[[], Any]) -> Any:
    """
    Serve cached value instantly if present and not older than hard_ttl.
    If older than soft_ttl, kick off a background refresh (best-effort).
    Expects the cached object to store a 'meta.cached_at' unix timestamp for age computation.
    """
    now = int(time.time())
    cur = cache_get(key)
    if cur is not None:
        cached_at = ((cur or {}).get("meta") or {}).get("cached_at", 0)
        age = now - cached_at
        if age <= hard_ttl:
            # trigger best-effort refresh if soft_ttl exceeded
            if age >= soft_ttl:
                def _bg():
                    try:
                        fresh = fetch_fn()
                        cache_set(key, fresh, hard_ttl)
                    except Exception:
                        pass
                threading.Thread(target=_bg, daemon=True).start()
            return cur

    # No acceptable cache, fetch synchronously
    data = fetch_fn()
    cache_set(key, data, hard_ttl)
    return data
