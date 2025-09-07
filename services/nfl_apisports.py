# services/nfl_apisports.py
import os, requests
from utils.rcache import cached_fetch

BASE_DIRECT = "https://v1.american-football.api-sports.io"
BASE_RAPID  = "https://api-american-football.p.rapidapi.com"

USE_RAPID = os.getenv("APISPORTS_MODE", "direct").lower() == "rapidapi"
API_KEY   = os.getenv("APISPORTS_KEY")
RAPID_HOST= os.getenv("APISPORTS_HOST", "api-american-football.p.rapidapi.com")

def _request(path, params=None):
    if not API_KEY:
        raise RuntimeError("APISPORTS_KEY missing")
    if USE_RAPID:
        url = f"{BASE_RAPID}{path}"
        headers = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": RAPID_HOST}
    else:
        url = f"{BASE_DIRECT}{path}"
        headers = {"x-apisports-key": API_KEY}
    resp = requests.get(url, params=params or {}, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.json()

def _get(path, params=None, ttl=3600):
    return cached_fetch("apisports", path, params, lambda: _request(path, params), ttl=ttl)

def search_player(name: str):
    # Adjust path/params to match the exact API-Sports NFL route you’re using
    return _get("/players", {"search": name}, ttl=12*3600)  # 12h cache

def player_last5_trends(player_id: int, season: int):
    js = _get("/players/statistics", {"player": player_id, "season": season}, ttl=6*3600)
    # Normalize your last-5 logic against their payload
    splits = (js.get("response") or [])[:5]
    if not splits:
        return {"n": 0}
    def as_int(x): 
        try: return int(x)
        except: return 0
    # Example thresholds—you can tune:
    rec_hits  = sum(1 for s in splits if as_int(s.get("receptions", 0)) >= 4)
    rush_hits = sum(1 for s in splits if s.get("type") == "rushing" and as_int(s.get("yards", 0)) >= 50)
    n = len(splits)
    return {
        "n": n,
        "rec_over35_rate": round(100.0 * rec_hits / n, 1),
        "rush_over49_rate": round(100.0 * rush_hits / n, 1),
        "raw": splits,
    }
