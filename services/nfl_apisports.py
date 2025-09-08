import os, requests
from typing import Dict, Any
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
    return _get("/players", {"search": name}, ttl=12*3600)

def player_last5_trends(player_id: int, season: int):
    js = _get("/players/statistics", {"player": player_id, "season": season}, ttl=6*3600)
    splits = js.get("response") or []
    splits = splits[:5]
    if not splits: return {"n": 0}
    def as_int(x): 
        try: return int(x)
        except: return 0
    rec_hits = 0; rush_hits = 0
    for s in splits:
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

def player_last5_dynamic(player_id: int, season: int, metric: str, line: float) -> Dict[str, Any]:
    """
    metric: "REC" | "RUSH_YDS" | "REC_YDS" | "PASS_YDS"
    """
    js = _get("/players/statistics", {"player": player_id, "season": season}, ttl=6*3600)
    splits = js.get("response") or []
    splits = splits[:5]
    if not splits: return {"n": 0, "metric": metric, "line": float(line)}

    def as_int(x): 
        try: return int(x)
        except: return 0

    hits = 0
    for s in splits:
        if metric == "REC":
            v = as_int(s.get("receptions", s.get("receiving",{}).get("receptions", 0)))
        elif metric == "RUSH_YDS":
            v = as_int(s.get("rushing",{}).get("yards", s.get("rushYds", 0)))
        elif metric == "REC_YDS":
            v = as_int(s.get("receiving",{}).get("yards", s.get("recYds", 0)))
        elif metric == "PASS_YDS":
            v = as_int(s.get("passing",{}).get("yards", s.get("passYds", 0)))
        else:
            v = 0
        if v >= float(line):
            hits += 1

    n = len(splits)
    return {"n": n, "rate": round(100.0*hits/n, 1), "metric": metric, "line": float(line)}


