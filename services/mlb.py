# services/mlb.py
from __future__ import annotations
import os, datetime as dt
from typing import Dict, Any, List, Optional, Tuple
import requests
from utils.rcache import cached_fetch
# services/mlb.py
import os
USE_FREE = os.getenv("MLB_FREE_ENABLED", "1") == "1"

if USE_FREE:
    # new free provider
    from services.mlb_free import resolve_player_id, batter_trends_last10
else:
    # legacy APISports provider (kept for fallback)
    from services.mlb_apisports import resolve_player_id, batter_trends_last10  # <-- rename your old file if needed

# -------- Config / TTLs --------
MLB_TIMEOUT_S = float(os.getenv("MLB_TIMEOUT_S", "8"))
MLB_RETRIES   = int(os.getenv("MLB_RETRIES", "0"))

TTL_SCHEDULE  = 900          # /games?date=...
TTL_SEARCH    = 4 * 3600     # /players?search=...
TTL_GAMELOG   = 1800         # /games/players per game
CACHE_NS      = "apisports_mlb"

# Optional scoping (helps API-Sports return data)
APISPORTS_MLB_SEASON = os.getenv("APISPORTS_MLB_SEASON", str(dt.date.today().year))
APISPORTS_MLB_LEAGUE_ID = os.getenv("APISPORTS_MLB_LEAGUE_ID")  # e.g. MLB league id if required by your plan/provider

# -------- API-SPORTS base + headers --------
def _apisports_cfg() -> Tuple[str, Dict[str,str]]:
    try:
        from utils.apisports_env import sport_cfg  # optional helper
        base, headers = sport_cfg("MLB")
        return base.rstrip("/"), headers
    except Exception:
        pass

    base = (os.getenv("APISPORTS_MLB_BASE")
            or os.getenv("APISPORTS_BASE")
            or "https://v1.baseball.api-sports.io").rstrip("/")

    rapid_key  = os.getenv("APISPORTS_MLB_RAPIDAPI_KEY") or os.getenv("APISPORTS_RAPIDAPI_KEY")
    rapid_host = os.getenv("APISPORTS_MLB_RAPIDAPI_HOST") or os.getenv("APISPORTS_RAPIDAPI_HOST")
    direct_key = os.getenv("APISPORTS_MLB_KEY") or os.getenv("APISPORTS_KEY")

    if rapid_key:
        if not rapid_host:
            rapid_host = "api-baseball.p.rapidapi.com"
        headers = {"x-rapidapi-key": rapid_key, "x-rapidapi-host": rapid_host}
        if "://" not in base:
            base = f"https://{rapid_host}"
        return base.rstrip("/"), headers

    if not direct_key:
        raise RuntimeError("API-SPORTS MLB: missing key (set APISPORTS_MLB_KEY or APISPORTS_KEY, or RapidAPI vars).")
    return base.rstrip("/"), {"x-apisports-key": direct_key}

BASE, HEADERS = _apisports_cfg()

# -------- HTTP helpers --------
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

# -------- Public API (same signatures) --------
def todays_matchups(date_iso: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    API-SPORTS: /games?date=YYYY-MM-DD (+ optional season/league if needed)
    Returns: [{gamePk, away, home}]
    """
    date_iso = date_iso or dt.date.today().isoformat()
    params = {"date": date_iso}
    if APISPORTS_MLB_SEASON: params["season"] = APISPORTS_MLB_SEASON
    if APISPORTS_MLB_LEAGUE_ID: params["league"] = APISPORTS_MLB_LEAGUE_ID

    js = _get("/games", params, ttl=TTL_SCHEDULE)
    out: List[Dict[str, Any]] = []
    for g in (js.get("response") or []):
        gid  = g.get("id") or (g.get("game") or {}).get("id")
        teams = g.get("teams") or {}
        away = (teams.get("away") or {}).get("name") or (g.get("away") or {}).get("name")
        home = (teams.get("home") or {}).get("name") or (g.get("home") or {}).get("name")
        if gid and (away or home):
            out.append({"gamePk": gid, "away": away, "home": home})
    return out

def search_player(q: str) -> List[Dict[str, Any]]:
    """
    API-SPORTS: /players?search=q (& season, league)
    Returns: [{id, name}]
    """
    q = (q or "").strip()
    if not q:
        return []
    params = {"search": q}
    if APISPORTS_MLB_SEASON: params["season"] = APISPORTS_MLB_SEASON
    if APISPORTS_MLB_LEAGUE_ID: params["league"] = APISPORTS_MLB_LEAGUE_ID

    js = _get("/players", params, ttl=TTL_SEARCH)
    out: List[Dict[str, Any]] = []
    for p in (js.get("response") or []):
        pid = p.get("id") or (p.get("player") or {}).get("id")
        name = (p.get("name")
                or (p.get("player") or {}).get("name")
                or " ".join([str(p.get("firstname") or ""), str(p.get("lastname") or "")]).strip())
        if pid and name:
            out.append({"id": int(pid), "name": str(name)})
    # de-dupe and cap
    seen, uniq = set(), []
    for r in out:
        if r["id"] in seen: continue
        seen.add(r["id"]); uniq.append(r)
    return uniq[:20]

def resolve_player_id(name: str) -> Optional[int]:
    rows = search_player(name or "")
    if rows:
        return int(rows[0]["id"])
    return None

# -------- Trends helpers (API-SPORTS only) --------
def _player_info(pid: int) -> Dict[str, Any]:
    params = {"id": pid}
    if APISPORTS_MLB_SEASON: params["season"] = APISPORTS_MLB_SEASON
    if APISPORTS_MLB_LEAGUE_ID: params["league"] = APISPORTS_MLB_LEAGUE_ID
    return _get("/players", params, ttl=12*3600)

def _player_team_id_by_pid(pid: int) -> Optional[int]:
    js = _player_info(pid)
    resp = js.get("response") or []
    if not resp:
        return None
    rec = resp[0]
    team = rec.get("team")
    if isinstance(team, dict) and team.get("id"):
        return int(team["id"])
    stats = rec.get("statistics")
    if isinstance(stats, list) and stats:
        t = stats[0].get("team")
        if isinstance(t, dict) and t.get("id"):
            return int(t["id"])
    # try common alternates
    for k in ("Team","teams"):
        t = rec.get(k)
        if isinstance(t, dict) and t.get("id"):
            return int(t["id"])
    return None

def _team_recent_game_ids(team_id: int, season: int, cap: int = 24) -> List[int]:
    params = {"team": team_id, "season": season}
    if APISPORTS_MLB_LEAGUE_ID: params["league"] = APISPORTS_MLB_LEAGUE_ID
    js = _get("/games", params, ttl=3600)
    resp = js.get("response") or []
    def _key(g: Dict[str, Any]) -> str:
        return g.get("date") or g.get("time") or g.get("commence_time") or ""
    resp.sort(key=_key, reverse=True)
    out: List[int] = []
    for g in resp:
        gid = g.get("id") or (g.get("game") or {}).get("id")
        if gid:
            out.append(int(gid))
        if len(out) >= cap:
            break
    return out

def _game_players(gid: int) -> Dict[str, Any]:
    params = {"game": gid}
    if APISPORTS_MLB_LEAGUE_ID: params["league"] = APISPORTS_MLB_LEAGUE_ID
    return _get("/games/players", params, ttl=24*3600)

def _extract_batting_line(game_players: Dict[str, Any], pid: int) -> Optional[Dict[str, Any]]:
    resp = game_players.get("response") or []
    if not resp: return None
    node = resp[0]
    players = node.get("players") or {}
    for side in ("home","away"):
        for p in players.get(side) or []:
            pl = p.get("player") or {}
            _pid = pl.get("id") or p.get("id")
            if _pid and int(_pid) == int(pid):
                st  = p.get("statistics") or p.get("stats") or {}
                bat = st.get("batting") or st.get("Batting") or {}
                if bat: return bat
                if isinstance(st, list) and st:
                    bat = st[0].get("batting") or st[0].get("Batting") or {}
                    if bat: return bat
    return None

def _num(d: Dict[str, Any], *keys) -> float:
    for k in keys:
        if k in d and d[k] is not None:
            try: return float(d[k])
            except: pass
    return 0.0

def batter_trends_last10(player_id: int, season: Optional[str] = None, player_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Build last-10 indicators:
      - hits >= 1  (HITS_0_5)
      - total bases >= 2 (TB_1_5)
    Accepts API-SPORTS player id. If that id fails, will try to resolve via player_name.
    """
    # Resolve to API-SPORTS id if this looks like an MLBAM id or is wrong
    api_pid: Optional[int] = None

    # First, assume caller passed API-SPORTS id
    try:
        api_pid = int(player_id)
    except Exception:
        api_pid = None

    # If we have a name and either no id or player lookup fails, resolve by name
    def _ensure_api_pid(pid: Optional[int]) -> Optional[int]:
        if pid:
            # quick probe to see if /players?id=pid returns something
            try:
                js = _player_info(pid)
                if (js.get("response") or []):
                    return pid
            except Exception:
                pass
        # try name resolution
        if player_name:
            rid = resolve_player_id(player_name)
            if rid:
                return rid
        return pid

    api_pid = _ensure_api_pid(api_pid)

    # If still no valid id, we’re done
    if not api_pid:
        return {"n": 0, "hits_rate": 0.0, "tb2_rate": 0.0, "hits_series": [], "tb2_series": []}

    # Season int
    try:
        season_i = int(season) if season not in (None,"") else int(APISPORTS_MLB_SEASON)
    except Exception:
        season_i = int(dt.date.today().year)

    team_id = _player_team_id_by_pid(api_pid)
    if not team_id:
        return {"n": 0, "hits_rate": 0.0, "tb2_rate": 0.0, "hits_series": [], "tb2_series": []}

    gids = _team_recent_game_ids(team_id, season_i, cap=24)

    hits_series: List[int] = []
    tb2_series:  List[int] = []

    for gid in gids:
        if len(hits_series) >= 10:
            break
        try:
            gp = _game_players(gid)
            bat = _extract_batting_line(gp, api_pid)
            if not bat:
                continue
            h  = _num(bat, "hits", "H", "h")
            tb = _num(bat, "totalBases", "total_bases", "TB", "tb", "bases_total", "bases")
            hits_series.append(1 if h >= 1 else 0)
            tb2_series.append(1 if tb >= 2 else 0)
        except Exception:
            continue

    n = len(hits_series)
    if n == 0:
        return {"n": 0, "hits_rate": 0.0, "tb2_rate": 0.0, "hits_series": [], "tb2_series": []}

    return {
        "n": n,
        "hits_rate": round(100.0 * sum(hits_series)/n, 1),
        "tb2_rate":  round(100.0 * sum(tb2_series)/n,  1),
        "hits_series": hits_series,
        "tb2_series":  tb2_series,
    }


