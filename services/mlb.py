import datetime as dt, requests
from utils.rcache import cached_fetch

BASE = "https://statsapi.mlb.com/api/v1"

def _get(path, params=None, ttl=1800):
    url = f"{BASE}{path}"
    def call():
        r = requests.get(url, params=params or {}, timeout=20)
        r.raise_for_status()
        return r.json()
    # Cache under "mlb" namespace (doesn't count toward API-Sports budget)
    return cached_fetch("mlb", path, params, call, ttl=ttl)

def todays_matchups(date_iso=None):
    date_iso = date_iso or dt.date.today().isoformat()
    data = _get("/schedule", {"sportId": 1, "date": date_iso}, ttl=900)
    games = []
    for d in data.get("dates", []):
        for g in d.get("games", []):
            games.append({
                "gamePk": g["gamePk"],
                "away": g["teams"]["away"]["team"]["name"],
                "home": g["teams"]["home"]["team"]["name"],
            })
    return games

def search_player(name: str):
    data = _get("/people/search", {"namePart": name}, ttl=12*3600)
    out = []
    for p in data.get("people", []):
        out.append({"id": p["id"], "name": p["fullName"]})
    return out

def batter_trends_last10(player_id: int, season: str | None = None):
    season = season or str(dt.date.today().year)
    data = _get(f"/people/{player_id}/stats", {"stats": "gameLog", "group": "hitting", "season": season}, ttl=3600)
    logs = (data.get("stats") or [{}])[0].get("splits") or []
    logs = logs[:10]
    if not logs:
        return {"n": 0, "hits_rate": None, "tb2_rate": None}
    hits = sum(1 for s in logs if s["stat"].get("hits", 0) >= 1)
    tb2  = sum(1 for s in logs if s["stat"].get("totalBases", 0) >= 2)
    n = len(logs)
    return {"n": n, "hits_rate": round(100*hits/n, 1), "tb2_rate": round(100*tb2/n, 1)}

