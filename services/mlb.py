import datetime as dt, requests
from utils.rcache import cached_fetch

BASE = "https://statsapi.mlb.com/api/v1"

def _get(url, ttl=3600):
    key = url.replace("https://","")
    x = get_cached(f"mlb/{key.replace('/','_')}.json", ttl)
    if x is not None: return x
    r = requests.get(url, timeout=20); r.raise_for_status()
    return set_cached(f"mlb/{key.replace('/','_')}.json", r.json())

def todays_matchups(date_iso:str|None=None):
    date_iso = date_iso or dt.date.today().isoformat()
    data = _get(f"{BASE}/schedule?sportId=1&date={date_iso}", ttl=900)
    games = []
    for d in data.get("dates", []):
        for g in d.get("games", []):
            games.append({
                "gamePk": g["gamePk"],
                "away": g["teams"]["away"]["team"]["name"],
                "home": g["teams"]["home"]["team"]["name"],
            })
    return games

def search_player(name:str):
    # simple name search
    data = _get(f"{BASE}/people/search?namePart={name}")
    out=[]
    for p in data.get("people",[]):
        if p.get("primaryPosition",{}).get("code") in {"2","3","4","5","6","7","8","9","D","1"}:
            out.append({"id":p["id"], "name":p["fullName"], "position":p["primaryPosition"]["abbreviation"]})
    return out

def batter_trends_last10(player_id:int, season:str|None=None):
    # MLB provides game logs by season; we stitch recent games across seasons by hitting current season
    season = season or str(dt.date.today().year)
    url = f"{BASE}/people/{player_id}/stats?stats=gameLog&group=hitting&season={season}"
    data = _get(url, ttl=3600)
    logs = (data.get("stats") or [{}])[0].get("splits") or []
    # last 10 appearances
    logs = logs[:10]
    if not logs: return {"n":0,"hits_rate":None,"tb2_rate":None}
    hits_succ = sum(1 for s in logs if s["stat"].get("hits",0) >= 1)
    tb2_succ  = sum(1 for s in logs if s["stat"].get("totalBases",0) >= 2)
    n = len(logs)
    return {
        "n": n,
        "hits_rate": round(100.0*hits_succ/n,1),
        "tb2_rate":  round(100.0*tb2_succ/n,1),
    }
