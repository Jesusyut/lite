# utils/rcache.py
import os, json, time, hashlib
import redis

r = redis.from_url(os.environ["REDIS_URL"], decode_responses=True)

def _k(prefix, path, params=None):
    h = hashlib.md5((path + "|" + json.dumps(params or {}, sort_keys=True)).encode()).hexdigest()
    return f"{prefix}:{h}"

def _day(prefix):
    return f"{prefix}:count:{time.strftime('%Y%m%d')}"

def budget_ok(prefix="apisports", soft_cap=90):
    # Stop making fresh upstream calls once we pass soft_cap
    c = int(r.get(_day(prefix)) or 0)
    return c < soft_cap

def count_call(prefix="apisports", n=1):
    k = _day(prefix)
    pipe = r.pipeline()
    pipe.incrby(k, n)
    pipe.expire(k, 60 * 60 * 26)  # slightly > 24h to survive restarts
    pipe.execute()

def get_json(key):
    s = r.get(key)
    return json.loads(s) if s else None

def set_json(key, obj, ttl):
    r.setex(key, ttl, json.dumps(obj))

def cached_fetch(prefix, path, params, fetch_fn, ttl=3600, stale_ttl=3*86400):
    fresh_key = _k(prefix + ":fresh", path, params)
    stale_key = _k(prefix + ":stale", path, params)

    data = get_json(fresh_key)
    if data is not None:
        return data

    if not budget_ok(prefix):
        # Serve stale if we're at/over budget
        data = get_json(stale_key)
        if data is not None:
            return data
        raise RuntimeError("API budget exhausted and no cached data")

    # Make one upstream call, then save both fresh and stale
    data = fetch_fn()
    set_json(fresh_key, data, ttl)
    set_json(stale_key, data, stale_ttl)
    count_call(prefix, 1)
    return data
