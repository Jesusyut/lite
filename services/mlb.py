# services/mlb.py
from __future__ import annotations
import os, datetime as dt
from typing import Dict, Any, List, Optional

import requests
from utils.rcache import cached_fetch

# ---------------- Config / TTLs ----------------
MLB_TIMEOUT_S = float(os.getenv("MLB_TIMEOUT_S", "8"))
MLB_RETRIES   = int(os.getenv("MLB_RETRIES", "0"))

TTL_SCHEDULE  = 900          # 15m   (games for a date)
TTL_SEARCH    = 4 * 3600     # 4h    (player search)
TTL_GAMELOG   = 1800         # 30m   (per-game stats pulled via /games/players)
CACHE_NS      = "apisports_mlb"

# ------------- API-SPORTS base + headers -------------
def _apisports_cfg() -> tuple[str, Dict[str, str]]:
    """
    Resolve API-SPORTS Baseball endpoint + headers.
    Supports either:
      - Direct: APISPORTS_MLB_KEY (or APISPORTS_KEY) with APISPORTS_MLB_BASE/APISPORTS_BASE
      - RapidAPI: APISPORTS_MLB_RAPIDAPI_KEY (or APISPORTS_RAPIDAPI_KEY) with host
    """
    # Prefer central helper if present
    try:
        from utils.apisports_env import sport_cfg
        base, headers = sport_cfg("MLB")
        return base.rstrip("/"), headers
    except Exception:
        pass

    base = (
        os.getenv("APISPORTS_MLB_BASE")
        or os.getenv("APISPORTS_BASE")
        or "https://v1.baseball.api-sports.io"
    ).rstrip("/")

    rapid_key  = os.getenv("APISPORTS_MLB_RAPIDAPI_KEY") or os.getenv("APISPORTS_RAPIDAPI_KEY")
    rapid_host = os.getenv("APISPORTS_MLB_RAPIDAPI_HOST") or os.getenv("APISPORTS_RAPIDAPI_HOST")
    direct_key = os.getenv("APISPORTS_MLB_KEY") or os.getenv("APISPORTS_KEY")

    if rapid_key:
        if not rapid_host:
            rapid_host = "api-baseball.p.rapidapi.com"
        headers = {"x-rapidapi-key": rapid_key, "x-rapidapi-host": rapid_host}
        # Allow using host as base
        if "://" not in base:
            base = f"https://{rapid_host}"
        return base.rstrip("/"), headers

    if not direct_key:
        raise RuntimeError("API-SPORTS (MLB): missing key. Set APISPORTS_MLB_KEY or APISPORTS_KEY (or RapidAPI vars).")

    headers = {"x-apisports-key": direct_key}
    return base.rstrip("/"), headers

BASE, HEADERS = _apisports_cfg()

# ------------- HTTP helpers -------------
def _http_json(url: str, params: Dict[str, Any] | None) -> Any:
    r = requests.get(url, headers=HEADERS, params=params or {}, timeout=MLB_TIMEOUT_S)
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
    raise last

def _get(path: str, params: Dict[str, Any] | None, ttl: int):
    """
    Cached GET with a safety: if the Redis layer throws a "budget exhausted"
    and there's no cache yet, we make one direct call so routes don't 500.
    """
    url = f"{BASE}{path}"
    def call():
        return _retrying_call(lambda: _http_json(url, params), MLB_RETRIES + 1)
    try:
        return cached_fetch(CACHE_NS, path, params or {}, call, ttl=ttl, stale_ttl=3*86400)
    except Exception as e:
        msg = str(e).lower()
        if "budget" in msg and "exhaust" in msg:
            return call()
        raise

# ------------- Small in-proc cache for name→id -------------
_NAME_TO_ID: dict[str, int] = {
    "shohei ohtani": 660271,  # keep a couple of hot names to cut early calls
    "aaron judge":   592450,
    "juan soto":     665742,
    "mookie betts":  605141,
}

# =============================================================================
# Public API (unchanged signatures)
# =============================================================================

def todays_matchups(date_iso: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    API-SPORTS: /games?date=YYYY-MM-DD
    Returns: [{gamePk, away, home}]
    """
    date_iso = date_iso or dt.date.today().isoformat()
    js = _get("/games", {"date": date_iso}, ttl=TTL_SCHEDULE)
    out: List[Dict[str, Any]] = []
    for g in (js.get("response") or []):
        # flexible read
        gid  = g.get("id") or (g.get("game") or {}).get("id")
        teams = g.get("teams") or {}
        away = (teams.get("away") or {}).get("name") or (g.get("away") or {}).get("name")
        home = (teams.get("home") or {}).get("name") or (g.get("home") or {}).get("name")
        if gid and (away or home):
            out.append({"gamePk": gid, "away": away, "home": home})
    return out

def search_player(q: str) -> List[Dict[str, Any]]:
    """
    API-SPORTS: /players?search=q
    Returns: [{id, name}]
    """
    q = (q or "").strip()
    if not q:
        return []
    js = _get("/players", {"search": q}, ttl=TTL_SEARCH)
    out: List[Dict[str, Any]] = []
    for p in (js.get("response") or []):
        pid = p.get("id") or (p.get("player") or {}).get("id")
        name = (
            p.get("name")
            or (p.get("player") or {}).get("name")
            or " ".join([str(p.get("firstname") or ""), str(p.get("lastname") or "")]).strip()
        )
        if pid and name:
            out.append({"id": int(pid), "name": str(name)})
    # de-dupe
    seen, uniq = set(), []
    for r in out:
        if r["id"] in seen: continue
        seen.add(r["id"]); uniq.append(r)
    return uniq[:20]

def resolve_player_id(name: str) -> Optional[int]:
    if not name:
        return None
    key = name.lower().strip()
    if key in _NAME_TO_ID:
        return _NAME_TO_ID[key]
    try:
        rows = search_player(name)
        if rows:
            pid = int(rows[0]["id"])
            _NAME_TO_ID[key] = pid
            return pid
    except Exception:
        pass
    return None

# --------- Helpers for last-10 trends via API-SPORTS ---------
def _player_team_id(pid: int) -> Optional[int]:
    js = _get("/players", {"id": pid}, ttl=12*3600)
    resp = js.get("response") or []
    if not resp:
        return None
    rec = resp[0]
    # common shapes: rec["team"] or rec["statistics"][0]["team"]
    team = rec.get("team")
    if isinstance(team, dict) and team.get("id"):
        return int(team["id"])
    stats = rec.get("statistics")
    if isinstance(stats, list) and stats:
        t = stats[0].get("team")
        if isinstance(t, dict) and t.get("id"):
            return int(t["id"])
    # try fallback keys
    for k in ("Team", "teams"):
        t = rec.get(k)
        if isinstance(t, dict) and t.get("id"):
            return int(t["id"])
    return None

def _team_recent_game_ids(team_id: int, season: int, cap: int = 24) -> List[int]:
    js = _get("/games", {"team": team_id, "season": season}, ttl=3600)
    resp = js.get("response") or []
    # sort newest→oldest by date/commence_time
    def _dt(g: Dict[str, Any]) -> str:
        return g.get("date") or g.get("time") or g.get("commence_time") or ""
    resp.sort(key=_dt, reverse=True)
    gids: List[int] = []
    for g in resp:
        gid = g.get("id") or (g.get("game") or {}).get("id")
        if gid: gids.append(int(gid))
        if len(gids) >= cap: break
    return gids

def _game_players(gid: int) -> Dict[str, Any]:
    return _get("/games/players", {"game": gid}, ttl=24*3600)

def _extract_batting_line(game_players: Dict[str, Any], pid: int) -> Optional[Dict[str, Any]]:
    resp = game_players.get("response") or []
    if not resp: return None
    node = resp[0]  # single game
    players = node.get("players") or {}
    for side in ("home", "away"):
        arr = players.get(side) or []
        for p in arr:
            pl = p.get("player") or {}
            _pid = pl.get("id") or p.get("id")
            if _pid and int(_pid) == int(pid):
                st = p.get("statistics") or p.get("stats") or {}
                bat = st.get("batting") or st.get("Batting") or {}
                if bat: return bat
                if isinstance(st, list) and st:
                    bat = st[0].get("batting") or st[0].get("Batting") or {}
                    if bat: return bat
    return None

def batter_trends_last10(player_id: int, season: Optional[str] = None) -> Dict[str, Any]:
    """
    API-SPORTS ONLY:
      - find player team
      - get recent team games
      - per game: /games/players?game=... → batting line
      - build last-10 series for Hits>=1 and TB>=2
    """
    try:
        season_i = int(season) if season not in (None, "",) else dt.date.today().year
    except Exception:
        season_i = dt.date.today().year

    team_id = _player_team_id(int(player_id))
    if not team_id:
        return {"n": 0, "hits_rate": 0.0, "tb2_rate": 0.0, "hits_series": [], "tb2_series": []}

    game_ids = _team_recent_game_ids(team_id, season_i, cap=24)

    hits_series: List[int] = []
    tb2_series:  List[int] = []

    def _num(d: Dict[str, Any], *keys) -> float:
        for k in keys:
            if k in d and d[k] is not None:
                try:   return float(d[k])
                except: pass
        return 0.0

    for gid in game_ids:
        if len(hits_series) >= 10:
            break
        try:
            gp = _game_players(gid)
            bat = _extract_batting_line(gp, int(player_id))
            if not bat:
                continue
            h  = _num(bat, "hits", "H", "h")
            tb = _num(bat, "totalBases", "total_bases", "TB", "tb", "bases_total", "bases")
            hits_series.append(1 if h  >= 1 else 0)
            tb2_series.append(1 if tb >= 2 else 0)
        except Exception:
            continue

    n = max(len(hits_series), 1)
    hr = round(100.0 * (sum(hits_series) / n), 1)
    tr = round(100.0 * (sum(tb2_series)  / n), 1)
    return {
        "n": len(hits_series),
        "hits_rate": hr,
        "tb2_rate": tr,
        "hits_series": hits_series,
        "tb2_series": tb2_series,
    }

