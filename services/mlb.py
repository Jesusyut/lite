# services/mlb.py  — Free MLB Stats API only (no API-Sports)

from __future__ import annotations
import os, time, datetime as dt, requests
from typing import Dict, Any, List, Optional

# ---- cache (uses your cache_ttl if present; falls back to in-proc) ----
try:
    from cache_ttl import cache_get as _cache_get, cache_set as _cache_set
except Exception:
    _MEM: Dict[str, Any] = {}
    def _cache_get(k: str): return _MEM.get(k)
    def _cache_set(k: str, v: Any, ttl_s: int = 86400): _MEM[k] = v  # naive fallback

BASE = "https://statsapi.mlb.com/api/v1"
TTL_DAY   = int(os.getenv("MLB_CACHE_TTL_S", "86400"))   # 24h
TTL_HR    = 3600
MIN_IVL_S = float(os.getenv("MLB_MIN_INTERVAL_S", "0.20"))  # polite throttle (~5 qps)
_LAST_AT  = 0.0

def _throttled_get(path: str, params: Dict[str, Any] | None = None, tries: int = 4):
    """Polite throttling + simple backoff to avoid 429."""
    global _LAST_AT
    dtv = time.monotonic() - _LAST_AT
    if dtv < MIN_IVL_S:
        time.sleep(MIN_IVL_S - dtv)
    url = f"{BASE}{path}"
    for i in range(tries):
        r = requests.get(url, params=params or {}, timeout=12)
        if r.status_code == 429:
            time.sleep(1.0 + i)  # linear backoff
            continue
        r.raise_for_status()
        _LAST_AT = time.monotonic()
        return r.json()
    r.raise_for_status()

def _season_today() -> int:
    return dt.date.today().year

# ---------------- Public API ----------------

def todays_matchups(date_iso: Optional[str] = None) -> List[Dict[str, Any]]:
    """[{gamePk, away, home, start}] — used by /api/mlb/today"""
    d = date_iso or dt.date.today().isoformat()
    ck = f"mlb:sched:{d}"
    hit = _cache_get(ck)
    if hit is not None: return hit
    js = _throttled_get("/schedule", {"sportId": 1, "date": d})
    dates = (js or {}).get("dates") or []
    games = (dates[0] or {}).get("games") if dates else []
    out: List[Dict[str, Any]] = []
    for g in games or []:
        out.append({
            "gamePk": g.get("gamePk"),
            "away": ((g.get("teams") or {}).get("away") or {}).get("team", {}).get("name"),
            "home": ((g.get("teams") or {}).get("home") or {}).get("team", {}).get("name"),
            "start": g.get("gameDate"),
        })
    _cache_set(ck, out, ttl_s=TTL_DAY)
    return out

def search_player(q: str) -> List[Dict[str, Any]]:
    """Return [{id, name}] via /people/search — used by /api/mlb/search"""
    q = (q or "").strip()
    if not q: return []
    ck = f"mlb:search:{q.lower()}"
    hit = _cache_get(ck)
    if hit is not None: return hit
    js = _throttled_get("/people/search", {"name": q})
    people = (js or {}).get("people") or []
    out = [{"id": p.get("id"), "name": p.get("fullName")} for p in people if p.get("id")]
    _cache_set(ck, out, ttl_s=TTL_HR)
    return out[:20]

def resolve_player_id(name: str) -> Optional[int]:
    rows = search_player(name)
    return int(rows[0]["id"]) if rows else None

def _game_log(pid: int, season: int):
    """Cache a player's game log for the season."""
    ck = f"mlb:gamelog:{season}:{pid}"
    hit = _cache_get(ck)
    if hit is not None: return hit
    js = _throttled_get(f"/people/{pid}/stats", {"stats": "gameLog", "season": season})
    splits = (((js or {}).get("stats") or [{}])[0].get("splits")) or []
    _cache_set(ck, splits, ttl_s=TTL_DAY)
    return splits

def batter_trends_last10_cached(pid: int):
    """Cache-only read for fast first paint. Returns dict or None."""
    season = _season_today()
    ck = f"mlb:last10:{season}:{pid}"
    return _cache_get(ck)

def batter_trends_last10(player_id: int, player_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Returns:
      {
        n,                         # games counted (<=10)
        hits_rate, tb2_rate,       # 0–100 ints
        hits_series, tb2_series    # arrays of 0/1 (length n)
      }
    Matches your previous shape used by evaluate() and /api/top/mlb.
    """
    pid = int(player_id) if player_id else None
    if not pid and player_name:
        pid = resolve_player_id(player_name)
    if not pid:
        return {"n": 0, "hits_rate": 0, "tb2_rate": 0, "hits_series": [], "tb2_series": []}

    season = _season_today()
    ck = f"mlb:last10:{season}:{pid}"
    hit = _cache_get(ck)
    if hit is not None: return hit

    splits = _game_log(pid, season)
    rows: List[Dict[str, int]] = []
    # The API usually returns most recent first; scan a little, collect first 10 with stats
    for s in splits[:30]:
        st = (s.get("stat") or {})
        # only count games with PA (or AB)
        if "atBats" not in st and "plateAppearances" not in st:
            continue
        rows.append({
            "hits": int(st.get("hits") or 0),
            "tb":   int(st.get("totalBases") or 0),
        })
        if len(rows) >= 10:
            break

    n = len(rows)
    if n == 0:
        out = {"n": 0, "hits_rate": 0, "tb2_rate": 0, "hits_series": [], "tb2_series": []}
        _cache_set(ck, out, ttl_s=TTL_DAY)
        return out

    hits_series = [1 if r["hits"] >= 1 else 0 for r in rows]
    tb2_series  = [1 if r["tb"]   >= 2 else 0 for r in rows]
    out = {
        "n": n,
        "hits_rate": round(100 * sum(hits_series) / n),
        "tb2_rate":  round(100 * sum(tb2_series)  / n),
        "hits_series": hits_series,
        "tb2_series":  tb2_series,
    }
    _cache_set(ck, out, ttl_s=TTL_DAY)
    return out



