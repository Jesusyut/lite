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
    # Cached with daily call budget in utils/rcache
    return cached_fetch("apisports", path, params, lambda: _request(path, params), ttl=ttl)

def search_player(name: str):
    # Adjust the path/params if your API-Sports plan uses a different route
    return _get("/players", {"search": name}, ttl=12*3600)

def player_last5_trends(player_id: int, season: int):
    js = _get("/players/statistics", {"player": player_id, "season": season}, ttl=6*3600)
    splits = js.get("response") or []
    splits = splits[:5]  # recent 5
    if not splits:
        return {"n": 0}
    def as_int(x):
        try: return int(x)
        except: return 0
    rec_hits  = 0
    rush_hits = 0
    for s in splits:
        # keys may vary by collection; adapt to your payload
        rec = as_int(s.get("receptions", s.get("receiving",{}).get("receptions", 0)))
        ry  = as_int(s.get("rushing",{}).get("yards", s.get("rushYds", 0)))
        rec_hits  += 1 if rec >= 4 else 0
        rush_hits += 1 if ry  >= 50 else 0
    n = len(splits)
    return {
        "n": n,
        "rec_over35_rate": round(100.0 * rec_hits / n, 1),
        "rush_over49_rate": round(100.0 * rush_hits / n, 1),
        "raw": splits,
    }

