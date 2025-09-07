# Redis (or in-memory) caching with stale-while-revalidate + daily call budget

import os, json, time, hashlib

try:
    import redis
    _REDIS_URL = os.environ.get("REDIS_URL")
    r = redis.from_url(_REDIS_URL, decode_responses=True) if _REDIS_URL else None
except Exception:
    r = None

# In-memory fallback (local dev)
_mem = {}

def _k(prefix, path, params=None):
    h = hashlib.md5((path + "|" + json.dumps(params or {}, sort_keys=True)).encode()).hexdigest()
    return f"{prefix}:{h}"

def _day(prefix):
    return f"{prefix}:count:{time.strftime('%Y%m%d')}"

def _get(key):
    if r:
        s = r.get(key)
        return json.loads(s) if s else None
    else:
        val = _mem.get(key)
        if not val: return None
        expires, data = val
        if expires and expires < time.time():
            del _mem[key]
            return None
        return data

def _setex(key, ttl, obj):
    if r:
        r.setex(key, ttl, json.dumps(obj))
    else:
        _mem[key] = (time.time() + ttl if ttl else None, obj)

def budget_ok(prefix="apisports", soft_cap=90):
    key = _day(prefix)
    if r:
        c = int(r.get(key) or 0)
    else:
        c = int(_mem.get(key, (None, 0))[1] if _mem.get(key) else 0)
    return c < soft_cap

def count_call(prefix="apisports", n=1):
    key = _day(prefix)
    if r:
        pipe = r.pipeline()
        pipe.incrby(key, n)
        pipe.expire(key, 60*60*26)  # ~26h
        pipe.execute()
    else:
        _, cur = _mem.get(key, (time.time()+60*60*26, 0))
        _mem[key] = (time.time()+60*60*26, cur + n)

def cached_fetch(prefix, path, params, fetch_fn, ttl=3600, stale_ttl=3*86400):
    fresh_key = _k(prefix + ":fresh", path, params)
    stale_key = _k(prefix + ":stale", path, params)

    data = _get(fresh_key)
    if data is not None:
        return data

    if not budget_ok(prefix):
        data = _get(stale_key)
        if data is not None:
            return data
        raise RuntimeError("API budget exhausted and no cached data")

    # Make upstream call
    data = fetch_fn()
    _setex(fresh_key, ttl, data)
    _setex(stale_key, stale_ttl, data)
    count_call(prefix, 1)
    return data
