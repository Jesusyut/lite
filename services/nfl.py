import os, requests
from utils.cache import get_cached, set_cached

BASE_DIRECT = "https://v1.american-football.api-sports.io"
BASE_RAPID  = "https://api-american-football.p.rapidapi.com"

USE_RAPID   = os.getenv("APISPORTS_MODE", "direct").lower() == "rapidapi"
API_KEY     = os.getenv("APISPORTS_KEY")  # required
RAPID_HOST  = os.getenv("APISPORTS_HOST", "api-american-football.p.rapidapi.com")

def _get(path, params=None, ttl=1800):
    if not API_KEY:
        raise RuntimeError("APISPORTS_KEY missing")
    if USE_RAPID:
        url = f"{BASE_RAPID}{path}"
        headers = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": RAPID_HOST}
    else:
        url = f"{BASE_DIRECT}{path}"
        headers = {"x-apisports-key": API_KEY}

    ck = f"nfl{ '_rapid' if USE_RAPID else '_direct' }{path.replace('/','_')}_{str(params)}.json"
    hit = get_cached(ck, ttl)
    if hit is not None: return hit

    r = requests.get(url, params=params or {}, headers=headers, timeout=20)
    r.raise_for_status()
    return set_cached(ck, r.json())

# --- Examples you can use/adjust per their docs ---
def search_player(name: str):
    # Typical API-Sports pattern: /players?search=NAME
    return _get("/players", {"search": name})

def player_last5_trends(player_id: int, season: int):
    # Typical pattern: /players/statistics?player=ID&season=YYYY
    js = _get("/players/statistics", {"player": player_id, "season": season})
    # Convert last 5 games to simple props (customize thresholds you want to sell)
    splits = (js.get("response") or [])[:5]
    if not splits: return {"n": 0}
    def g(v): 
        try: return int(v)
        except: return 0
    rec_hits  = sum(1 for s in splits if g(s.get("receptions", 0)) >= 4)      # Over 3.5 rec
    rush_hits = sum(1 for s in splits if g(s.get("yards", 0)) >= 50 and s.get("type")=="rushing")  # Over 49.5 rush yds (adjust mapping to your payload)
    n = len(splits)
    return {
        "n": n,
        "rec_over35_rate": round(100.0*rec_hits/n, 1),
        "rush_over49_rate": round(100.0*rush_hits/n, 1),
        "raw": splits
    }
