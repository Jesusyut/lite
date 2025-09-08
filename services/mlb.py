# services/mlb.py
from __future__ import annotations
import os
import datetime as dt
from typing import Dict, Any, List, Optional

import requests
from utils.rcache import cached_fetch

# ---- Tunables / TTLs ---------------------------------------------------------

MLB_TIMEOUT_S   = float(os.getenv("MLB_TIMEOUT_S", "8"))
MLB_RETRIES     = int(os.getenv("MLB_RETRIES", "0"))
TTL_SCHEDULE    = 900          # 15 min
TTL_SEARCH      = 4 * 3600     # 4 h
TTL_GAMELOG     = 1800         # 30 min

# If API-SPORTS is available, we’ll prefer it. Otherwise we’ll use MLB StatsAPI.
PREFER_APISPORTS = os.getenv("APISPORTS_MLB_ON", "1") == "1"

# ---- Fallback (StatsAPI) base ------------------------------------------------

STATS_BASE = os.getenv("MLB_BASE", "https://statsapi.mlb.com/api/v1").rstrip("/")

# ---- Local small cache for name → id -----------------------------------------

_NAME_TO_ID: dict[str, int] = {
    "shohei ohtani": 660271,
    "aaron judge":   592450,
    "juan soto":     665742,
    "mookie betts":  605141,
}

# ---- HTTP helpers ------------------------------------------------------------

def _http_json(url: str, params: Dict[str, Any] | None, headers: Dict[str, str] | None = None) -> Any:
    r = requests.get(url, params=params or {}, headers=headers or {}, timeout=MLB_TIMEOUT_S)
    r.raise_for_status()
    return r.json()

def _retrying_call(fn, tries: int):
    last = None
    tries = max(1, tries)
    for _ in range(tries):
        try:
            return fn()
        except Exception as e:
            last = e
    if last:
        raise last

# ---- Provider detection for API-SPORTS ---------------------------------------

def _apisports_cfg() -> tuple[str, Dict[str, str]] | None:
    """
    Returns (base, headers) for API-SPORTS Baseball if env is present, else None.
    Uses utils.apisports_env.sport_cfg('MLB') when available; otherwise tries
    direct envs.
    """
    # Preferred way: central helper
    try:
        from utils.apisports_env import sport_cfg  # optional
        base, headers = sport_cfg("MLB")
        return base.rstrip("/"), headers
    except Exception:
        pass

    # Lightweight direct read (keeps this file self-contained if helper is absent)
    base = (
        os.getenv("APISPORTS_MLB_BASE")
        or os.getenv("APISPORTS_BASE")
        or "https://v1.baseball.api-sports.io"
    ).rstrip("/")

    # RapidAPI flavor
    rapid_key  = os.getenv("APISPORTS_MLB_RAPIDAPI_KEY") or os.getenv("APISPORTS_RAPIDAPI_KEY")
    rapid_host = os.getenv("APISPORTS_MLB_RAPIDAPI_HOST") or os.getenv("APISPORTS_RAPIDAPI_HOST")
    direct_key = os.getenv("APISPORTS_MLB_KEY") or os.getenv("APISPORTS_KEY")

    if rapid_key:
        if not rapid_host:
            # best guess host for baseball on RapidAPI
            rapid_host = "api-baseball.p.rapidapi.com"
        headers = {"x-rapidapi-key": rapid_key, "x-rapidapi-host": rapid_host}
        # When using RapidAPI we can hit https://{host} directly
        if "://" not in base:
            base = f"https://{rapid_host}"
        return base.rstrip("/"), headers

    if direct_key:
        headers = {"x-apisports-key": direct_key}
        return base.rstrip("/"), headers

    # No API-SPORTS keys
    return None

# ---- API-SPORTS GET (cached) -------------------------------------------------

def _apisports_get(path: str, params: Dict[str, Any] | None, ttl: int):
    cfg = _apisports_cfg()
    if not cfg:
        raise RuntimeError("API-SPORTS MLB env not configured")
    base, headers = cfg
    url = f"{base}{path}"
    def call():
        return _retrying_call(lambda: _http_json(url, params, headers=headers), MLB_RETRIES + 1)
    # single shared namespace for baseball odds/players/games
    return cached_fetch("apisports_mlb", path, params or {}, call, ttl=ttl, stale_ttl=3*86400)

# ---- StatsAPI GET (cached) ---------------------------------------------------

def _stats_get(path: str, params: Dict[str, Any] | None, ttl: int):
    url = f"{STATS_BASE}{path}"
    def call():
        return _retrying_call(lambda: _http_json(url, params), MLB_RETRIES + 1)
    return cached_fetch("mlb", path, params or {}, call, ttl=ttl, stale_ttl=3*86400)

# =============================================================================
# Public API (unchanged signatures)
# =============================================================================

def todays_matchups(date_iso: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Returns: [{gamePk|id, away, home}]
    Prefers API-SPORTS /games?date=YYYY-MM-DD, falls back to StatsAPI /schedule.
    """
    date_iso = (date_iso or dt.date.today().isoformat())
    if PREFER_APISPORTS:
        try:
            js = _apisports_get("/games", {"date": date_iso}, ttl=TTL_SCHEDULE)
            out: List[Dict[str, Any]] = []
            for g in (js.get("response") or []):
                # flexible extraction
                gid  = g.get("id") or g.get("game", {}).get("id")
                away = (g.get("teams") or {}).get("away", {}).get("name") or (g.get("away") or {}).get("name")
                home = (g.get("teams") or {}).get("home", {}).get("name") or (g.get("home") or {}).get("name")
                if gid and (away or home):
                    out.append({"gamePk": gid, "away": away, "home": home})
            if out:
                return out
        except Exception:
            # silent fallthrough
            pass

    # Fallback: StatsAPI
    data = _stats_get("/schedule", {"sportId": 1, "date": date_iso}, ttl=TTL_SCHEDULE)
    games = []
    for d in data.get("dates", []) or []:
        for g in d.get("games", []) or []:
            games.append({
                "gamePk": g.get("gamePk"),
                "away": g.get("teams", {}).get("away", {}).get("team", {}).get("name"),
                "home": g.get("teams", {}).get("home", {}).get("team", {}).get("name"),
            })
    return games

def search_player(name: str) -> List[Dict[str, Any]]:
    """
    Returns: list of {id, name}. Prefers API-SPORTS /players?search=.
    """
    q = (name or "").strip()
    if not q:
        return []
    if PREFER_APISPORTS:
        try:
            js = _apisports_get("/players", {"search": q}, ttl=TTL_SEARCH)
            out: List[Dict[str, Any]] = []
            for p in (js.get("response") or []):
                pid = p.get("id") or (p.get("player") or {}).get("id")
                nm  = (p.get("name") or (p.get("player") or {}).get("name")
                       or " ".join([str(p.get("firstname") or ""), str(p.get("lastname") or "")]).strip())
                if pid and nm:
                    out.append({"id": int(pid), "name": nm})
            if out:
                return out
        except Exception:
            pass

    # Fallback: StatsAPI
    data = _stats_get("/people/search", {"namePart": q}, ttl=TTL_SEARCH)
    out = []
    for p in data.get("people", []) or []:
        pid = p.get("id")
        nm  = p.get("fullName")
        if pid and nm:
            out.append({"id": pid, "name": nm})
    return out

def resolve_player_id(name: str) -> Optional[int]:
    if not name:
        return None
    key = name.lower().strip()
    if key in _NAME_TO_ID:
        return _NAME_TO_ID[key]
    try:
        res = search_player(name)
        if res:
            pid = int(res[0]["id"])
            _NAME_TO_ID[key] = pid
            return pid
    except Exception:
        pass
    return None

def batter_trends_last10(player_id: int, season: Optional[str] = None) -> Dict[str, Any]:
    """
    Compute last-10 game indicators for:
      - hits >= 1     (HITS_0_5)
      - total bases >= 2  (TB_1_5)

    Prefers API-SPORTS if it can provide per-game stats; falls back to StatsAPI
    gameLog if not available.

    Returns:
      {
        "n": int,
        "hits_rate": float|None,   # percent (0-100)
        "tb2_rate":  float|None,   # percent (0-100)
        "hits_series": [0|1]*n,
        "tb2_series":  [0|1]*n
      }
    """
    season = season or str(dt.date.today().year)

    # --- Try API-SPORTS first ---
    if PREFER_APISPORTS:
        try:
            # First attempt: a per-game list endpoint
            # Common shapes seen: /players/games or /players/statistics with per-game splits
            games = None
            try:
                js = _apisports_get("/players/games", {"id": player_id, "season": season}, ttl=TTL_GAMELOG)
                games = js.get("response") or (js.get("response", {}) or {}).get("games")
            except Exception:
                pass

            if not games:
                # Second attempt: statistics endpoint that sometimes returns per-game items
                js = _apisports_get("/players/statistics", {"id": player_id, "season": season}, ttl=TTL_GAMELOG)
                # try a few plausible paths
                games = (js.get("response") or [])
                # If it’s a wrapper with one player entry that contains "games"/"splits"
                if len(games) == 1 and isinstance(games[0], dict):
                    g0 = games[0]
                    games = g0.get("games") or g0.get("splits") or g0.get("fixtures") or g0.get("matches") or []

            hits_series: List[int] = []
            tb2_series:  List[int] = []

            def _num(d: Dict[str, Any], *keys) -> float:
                for k in keys:
                    if k in d and d[k] is not None:
                        try:
                            return float(d[k])
                        except Exception:
                            pass
                return 0.0

            # Normalize last 10 (most recent first if possible)
            if isinstance(games, list) and games:
                # take last 10 safely
                last10 = games[-10:] if len(games) > 10 else games
                for g in last10:
                    st = (g.get("statistics") or g.get("stats") or g.get("totals") or g) or {}
                    # Try common aliases
                    h  = _num(st, "hits", "H")
                    tb = _num(st, "totalBases", "TB", "tb", "bases_total", "bases")

                    hits_series.append(1 if h >= 1 else 0)
                    tb2_series.append(1 if tb >= 2 else 0)

                if hits_series:
                    n = len(hits_series)
                    return {
                        "n": n,
                        "hits_rate": round(100.0 * sum(hits_series) / n, 1),
                        "tb2_rate":  round(100.0 * sum(tb2_series)  / n, 1),
                        "hits_series": hits_series,
                        "tb2_series":  tb2_series,
                    }
        except Exception:
            # fall through to StatsAPI
            pass

    # --- Fallback: StatsAPI gameLog (stable) ---
    data = _stats_get(f"/people/{player_id}/stats",
                      {"stats": "gameLog", "group": "hitting", "season": season},
                      ttl=TTL_GAMELOG)
    splits = ((data.get("stats") or [{}])[0].get("splits") or [])[:10]
    if not splits:
        return {"n": 0, "hits_rate": None, "tb2_rate": None, "hits_series": [], "tb2_series": []}
    hits_series = []
    tb2_series  = []
    for s in splits:
        st = s.get("stat", {}) or {}
        hits_series.append(1 if (st.get("hits") or 0) >= 1 else 0)
        tb2_series.append(1 if (st.get("totalBases") or 0) >= 2 else 0)
    n = len(splits)
    return {
        "n": n,
        "hits_rate": round(100.0 * sum(hits_series) / n, 1),
        "tb2_rate":  round(100.0 * sum(tb2_series)  / n, 1),
        "hits_series": hits_series,
        "tb2_series":  tb2_series,
    }

