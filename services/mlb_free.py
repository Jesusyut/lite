# services/mlb_free.py
import os, time, datetime, requests

# ---- simple cache adapters (uses your cache_ttl if present) ----
try:
    from cache_ttl import cache_get as _cache_get, cache_set as _cache_set
except Exception:
    _MEM = {}
    def _cache_get(k): return _MEM.get(k)
    def _cache_set(k, v, ttl_s=86400): _MEM[k] = v

TTL_DAY = int(os.getenv("MLB_CACHE_TTL_S", "86400"))   # 24h default
BASE = "https://statsapi.mlb.com/api/v1"

# ---- polite throttling & retries (prevents 429s) ----
_MIN_INTERVAL = float(os.getenv("MLB_MIN_INTERVAL_S", "0.25"))  # 4 qps
_LAST_CALL_AT = 0.0

def _throttled_get(path, params=None, tries=4):
    global _LAST_CALL_AT
    now = time.monotonic()
    dt = now - _LAST_CALL_AT
    if dt < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - dt)
    url = f"{BASE}{path}"
    for i in range(tries):
        resp = requests.get(url, params=params or {}, timeout=12)
        if resp.status_code == 429:
            time.sleep(1.0 + i * 1.0)   # backoff
            continue
        resp.raise_for_status()
        _LAST_CALL_AT = time.monotonic()
        return resp.json()
    # last try:
    resp.raise_for_status()

def _this_season():
    # simple: use current year; adjust if needed post-season
    return datetime.date.today().year

# ---------- Public API (mirrors your old services/mlb.py) ---------
def resolve_player_id(name: str) -> int | None:
    """
    Look up a player id by name using MLB's search.
    """
    if not name: return None
    key = f"mlb:lookup:{name.lower()}"
    val = _cache_get(key)
    if val is not None: return val
    js = _throttled_get("/people/search", {"name": name})
    people = (js or {}).get("people") or []
    pid = (people[0] or {}).get("id") if people else None
    _cache_set(key, pid, ttl_s=TTL_DAY)
    return pid

def _game_log(pid: int, season: int):
    key = f"mlb:gamelog:{season}:{pid}"
    val = _cache_get(key)
    if val is not None: return val
    js = _throttled_get(f"/people/{pid}/stats", {"stats": "gameLog", "season": season})
    splits = (((js or {}).get("stats") or [{}])[0].get("splits")) or []
    _cache_set(key, splits, ttl_s=TTL_DAY)
    return splits

def batter_trends_last10(pid: int) -> dict:
    """
    Returns { hits_rate: 0-100, tb2_rate: 0-100, last10: [ {date, hits, totalBases}, ... ] }
    Matches your previous shape (percent integers).
    """
    if not pid:
        raise ValueError("player id required")
    today = datetime.date.today()
    season = _this_season()
    key = f"mlb:last10:{season}:{pid}"
    cached = _cache_get(key)
    if cached is not None: return cached

    splits = _game_log(pid, season)
    if not splits:
        out = {"hits_rate": 0, "tb2_rate": 0, "last10": []}
        _cache_set(key, out, ttl_s=TTL_DAY)
        return out

    # newest first in API; take last 10 appearances with battingStats
    rows = []
    for s in splits[:30]:  # cap scan window
        stat = (s.get("stat") or {})
        # only count games with PA (or AB present)
        if "atBats" not in stat and "plateAppearances" not in stat:
            continue
        rows.append({
            "date": s.get("date"),
            "hits": int(stat.get("hits", 0) or 0),
            "tb": int(stat.get("totalBases", 0) or 0),
        })
        if len(rows) >= 10: break

    n = len(rows) or 0
    if n == 0:
        out = {"hits_rate": 0, "tb2_rate": 0, "last10": []}
        _cache_set(key, out, ttl_s=TTL_DAY)
        return out

    hits_ge1 = sum(1 for r in rows if r["hits"] >= 1)
    tb_ge2   = sum(1 for r in rows if r["tb"]   >= 2)

    out = {
        "hits_rate": round(100 * hits_ge1 / n),
        "tb2_rate":  round(100 * tb_ge2 / n),
        "last10": rows,
    }
    _cache_set(key, out, ttl_s=TTL_DAY)
    return out
