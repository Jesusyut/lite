# services/mlb_apisports.py
from __future__ import annotations
import os, time, datetime as dt
from typing import Any, Dict, List, Optional, Tuple
import requests

from utils.rcache import cached_fetch  # same helper you already use

# ---------- Config / headers ----------
BASE = (os.getenv("APISPORTS_BASE") or "https://v1.baseball.api-sports.io").rstrip("/")
KEY  = os.getenv("APISPORTS_KEY")
RAPID_KEY  = os.getenv("APISPORTS_RAPIDAPI_KEY")
RAPID_HOST = os.getenv("APISPORTS_RAPIDAPI_HOST")

if not (KEY or RAPID_KEY):
    raise RuntimeError("API-SPORTS baseball: missing APISPORTS_KEY or APISPORTS_RAPIDAPI_KEY")

def _headers() -> Dict[str,str]:
    if RAPID_KEY:
        return {
            "x-rapidapi-key": RAPID_KEY,
            "x-rapidapi-host": RAPID_HOST or "api-baseball.p.rapidapi.com",
        }
    return {"x-apisports-key": KEY}

def _get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{BASE}{path}"
    r = requests.get(url, headers=_headers(), params=params, timeout=15)
    r.raise_for_status()
    return r.json()

# Generic cached fetch wrapper
def _cfetch(cache_ns: str, path: str, params: Dict[str, Any], ttl=3600, stale_ttl=24*3600):
    return cached_fetch(cache_ns, path, params, lambda: _get(path, params), ttl=ttl, stale_ttl=stale_ttl)

# ---------- Public: search / resolve ----------
def search_player(q: str) -> List[Dict[str, Any]]:
    """Return [{id, name}] for search string."""
    if not q: return []
    js = _cfetch("apisports", "/players", {"search": q}, ttl=6*3600)
    resp = js.get("response") or []
    out: List[Dict[str, Any]] = []
    for row in resp:
        pid = row.get("id") or row.get("player", {}).get("id")
        name = row.get("name") or row.get("player", {}).get("name")
        if pid and name:
            out.append({"id": int(pid), "name": str(name)})
    # de-dupe while preserving order
    seen, uniq = set(), []
    for r in out:
        if r["id"] in seen: continue
        seen.add(r["id"]); uniq.append(r)
    return uniq[:20]

def resolve_player_id(name: str) -> Optional[int]:
    """Best-effort resolve by exact (case-insens) else first hit."""
    if not name: return None
    rows = search_player(name)
    if not rows: return None
    lname = name.strip().lower()
    for r in rows:
        if str(r["name"]).lower() == lname:
            return int(r["id"])
    return int(rows[0]["id"])

# ---------- Public: Today’s games (simple) ----------
def todays_matchups() -> List[Dict[str, Any]]:
    today = dt.date.today().isoformat()
    js = _cfetch("apisports", "/games", {"date": today}, ttl=900)
    resp = js.get("response") or []
    out = []
    for g in resp:
        # Schema is stable enough: home/away names, id, start time
        gid = g.get("id") or g.get("game", {}).get("id")
        home = (g.get("teams", {}) or {}).get("home", {}) or {}
        away = (g.get("teams", {}) or {}).get("away", {}) or {}
        out.append({
            "id": gid,
            "home": home.get("name") or home.get("team"),
            "away": away.get("name") or away.get("team"),
            "time": g.get("date") or g.get("time") or g.get("commence_time"),
        })
    return out

# ---------- Helpers for last-10 ----------
def _player_team_id(pid: int) -> Optional[int]:
    js = _cfetch("apisports", "/players", {"id": pid}, ttl=12*3600)
    resp = js.get("response") or []
    # Prefer the first record's team (active season row)
    if not resp: return None
    rec = resp[0]
    team = rec.get("team") or (rec.get("statistics", [{}])[0].get("team") if rec.get("statistics") else None)
    # Different payloads exist; try common shapes:
    if isinstance(team, dict):
        tid = team.get("id") or team.get("team", {}).get("id")
        if tid: return int(tid)
    # Fallback: check nested
    for k in ("team","teams"):
        t = rec.get(k)
        if isinstance(t, dict) and t.get("id"):
            return int(t["id"])
    return None

def _team_recent_games(team_id: int, season: int, limit: int = 20) -> List[int]:
    """Return latest game IDs (descending date)."""
    js   = _cfetch("apisports", "/games", {"team": team_id, "season": season}, ttl=3600)
    resp = js.get("response") or []
    # sort by date desc
    def _date(g) -> str:
        return g.get("date") or g.get("time") or g.get("commence_time") or ""
    resp.sort(key=_date, reverse=True)
    gids = []
    for g in resp:
        gid = g.get("id") or (g.get("game") or {}).get("id")
        if gid: gids.append(int(gid))
        if len(gids) >= limit: break
    return gids

def _fetch_game_players(gid: int) -> Dict[str, Any]:
    return _cfetch("apisports", "/games/players", {"game": gid}, ttl=24*3600)

def _extract_batter_line(game_players: Dict[str, Any], pid: int) -> Optional[Dict[str, Any]]:
    """
    Find this player's batting line. API-SPORTS returns:
      { response: [ { teams: {...}, players: {home:[{player:{id,name}, statistics:{batting:{...}}}], away:[...] } } ] }
    We walk both home/away lists and return batting stats dict.
    """
    resp = game_players.get("response") or []
    if not resp: return None
    node = resp[0]  # first game node
    players = node.get("players") or {}
    for side in ("home", "away"):
        arr = players.get(side) or []
        for p in arr:
            # various shapes
            pl = p.get("player") or {}
            _pid = pl.get("id") or p.get("id")
            if _pid and int(_pid) == int(pid):
                # batting stats might be nested a few ways
                st = p.get("statistics") or p.get("stats") or {}
                bat = st.get("batting") or st.get("Batting") or {}
                if bat: return bat
                # Sometimes statistics is a list
                if isinstance(st, list) and st:
                    bat = (st[0].get("batting") or st[0].get("Batting") or {})
                    if bat: return bat
    return None

# ---------- Public: last-10 trends ----------
def batter_trends_last10(pid: int, season: Optional[int] = None) -> Dict[str, Any]:
    """
    Compute last-10 trends for:
      - Hits >= 1
      - Total Bases >= 2
    Returns:
      {
        hits_series: [0/1]*N, tb2_series: [0/1]*N,
        hits_rate: %, tb2_rate: %
      }
    """
    if not season:
        season = dt.date.today().year

    team_id = _player_team_id(int(pid))
    if not team_id:
        return {"hits_series": [], "tb2_series": [], "hits_rate": 0.0, "tb2_rate": 0.0}

    game_ids = _team_recent_games(team_id, season, limit=24)
    hits_series: List[int] = []
    tb2_series:  List[int] = []

    # Walk recent games newest→oldest until we collect 10 with a batting line
    for gid in game_ids:
        if len(hits_series) >= 10:
            break
        try:
            gp = _fetch_game_players(gid)
            bat = _extract_batter_line(gp, int(pid))
            if not bat:
                continue
            # robust access
            hits = bat.get("hits") or bat.get("H") or bat.get("h") or 0
            tb   = (bat.get("totalBases") or bat.get("TB") or bat.get("total_bases") or 0)
            try:
                hits = int(hits)
            except: hits = int(float(hits) if hits is not None else 0)
            try:
                tb = int(tb)
            except: tb = int(float(tb) if tb is not None else 0)
            hits_series.append(1 if hits >= 1 else 0)
            tb2_series.append(1 if tb   >= 2 else 0)
        except Exception:
            # skip bad/missing games silently
            continue

    n = max(len(hits_series), 1)
    hr = round(100.0 * (sum(hits_series) / n), 1)
    tr = round(100.0 * (sum(tb2_series)  / n), 1)
    return {
        "hits_series": hits_series,
        "tb2_series": tb2_series,
        "hits_rate": hr,
        "tb2_rate": tr,
    }
