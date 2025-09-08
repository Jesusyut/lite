# services/mlb.py
import os, datetime as dt, requests
from typing import Dict, Any, List, Optional
from utils.rcache import cached_fetch

MLB_BASE        = os.getenv("MLB_BASE", "https://statsapi.mlb.com/api/v1").rstrip("/")
MLB_TIMEOUT_S   = float(os.getenv("MLB_TIMEOUT_S", "8"))
MLB_RETRIES     = int(os.getenv("MLB_RETRIES", "0"))  # search can be flaky; don't stall forever
TTL_SCHEDULE    = 900
TTL_SEARCH      = 4 * 3600
TTL_GAMELOG     = 1800

# Small local cache to dodge search spikes
_NAME_TO_ID: dict[str, int] = {
    "shohei ohtani": 660271,
    "aaron judge": 592450,
    "juan soto": 665742,
    "mookie betts": 605141,
}

def _http_json(url: str, params: Dict[str, Any] | None) -> Any:
    r = requests.get(url, params=params or {}, timeout=MLB_TIMEOUT_S)
    r.raise_for_status()
    return r.json()

def _get(path: str, params: Dict[str, Any] | None, ttl: int):
    url = f"{MLB_BASE}{path}"
    def call():
        last = None
        tries = max(1, MLB_RETRIES + 1)
        for _ in range(tries):
            try:
                return _http_json(url, params)
            except Exception as e:
                last = e
        raise last
    return cached_fetch("mlb", path, params or {}, call, ttl=ttl, stale_ttl=3*86400)

def todays_matchups(date_iso: Optional[str] = None) -> List[Dict[str, Any]]:
    date_iso = date_iso or dt.date.today().isoformat()
    data = _get("/schedule", {"sportId": 1, "date": date_iso}, ttl=TTL_SCHEDULE)
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
    q = (name or "").strip()
    if not q:
        return []
    data = _get("/people/search", {"namePart": q}, ttl=TTL_SEARCH)
    out = []
    for p in data.get("people", []) or []:
        pid = p.get("id"); nm = p.get("fullName")
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
    season = season or str(dt.date.today().year)
    data = _get(f"/people/{player_id}/stats",
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
        "tb2_series": tb2_series,
    }

