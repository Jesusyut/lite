from __future__ import annotations
import os, requests
from typing import Optional, Tuple, Dict, Any, List
from utils.rcache import cached_fetch

ODDS_BASE   = os.getenv("ODDS_BASE", "https://api.the-odds-api.com/v4/sports")
ODDS_KEY    = os.getenv("ODDS_API_KEY")
ODDS_MAX_ABS = float(os.getenv("ODDS_MAX_ABS", "250"))  # <= 250 by default

# ---- helpers ----

def _price_ok(american) -> bool:
    try:
        return abs(float(american)) <= ODDS_MAX_ABS
    except Exception:
        return False

# ---- Provider requests (edit here if your provider is different) ----

def _request_mlb_props() -> List[Dict[str, Any]]:
    """
    The Odds API format:
      GET /baseball_mlb/odds?markets=player_hits,player_total_bases&
          bookmakers=fanduel&regions=us&oddsFormat=american&apiKey=...
    """
    if not ODDS_KEY:
        raise RuntimeError("ODDS_API_KEY missing")
    url = f"{ODDS_BASE}/baseball_mlb/odds"
    params = {
        "markets": "player_hits,player_total_bases",
        "bookmakers": "fanduel",
        "regions": "us",
        "oddsFormat": "american",
        "apiKey": ODDS_KEY,
    }
    def call():
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        return r.json()
    return cached_fetch("oddsfd", "/baseball_mlb/odds", params, call, ttl=900, stale_ttl=3*86400)

def _request_nfl_props(markets_csv: str) -> List[Dict[str, Any]]:
    """
    Example for NFL props if you enable them later.
    """
    if not ODDS_KEY:
        raise RuntimeError("ODDS_API_KEY missing")
    url = f"{ODDS_BASE}/americanfootball_nfl/odds"
    params = {
        "markets": markets_csv,
        "bookmakers": "fanduel",
        "regions": "us",
        "oddsFormat": "american",
        "apiKey": ODDS_KEY,
    }
    def call():
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        return r.json()
    return cached_fetch("oddsfd", "/americanfootball_nfl/odds", params, call, ttl=900, stale_ttl=3*86400)

# ---- Normalization / extraction ----

def _iter_fd_markets(rows: List[Dict[str, Any]]):
    """Yield (market_key, market_dict) for FanDuel only."""
    for ev in rows or []:
        for bm in ev.get("bookmakers", []):
            if str(bm.get("title","")).lower() != "fanduel":
                continue
            for m in bm.get("markets", []):
                yield m.get("key"), m

def _extract_fd_outcome(market_key: str, market: Dict[str, Any],
                        player_name: str, want_over: bool, target_line: float) -> Optional[Tuple[float,float]]:
    """
    Returns (line, american) for the requested player+direction if price is within range.
    """
    pneedle = player_name.lower()
    for o in market.get("outcomes", []):
        name = str(o.get("name",""))
        desc = str(o.get("description") or o.get("participant") or o.get("player") or "")
        point = o.get("point", o.get("line"))
        price = o.get("price", o.get("odds_american", o.get("american")))

        is_over  = ("over"  in name.lower()) or (o.get("side","").lower() == "over")
        is_under = ("under" in name.lower()) or (o.get("side","").lower() == "under")
        player_ok = (pneedle in desc.lower()) or (pneedle in name.lower())
        if want_over and not is_over: continue
        if not want_over and not is_under: continue
        if not player_ok: continue

        # match target line if present
        if point is not None:
            try:
                if abs(float(point) - float(target_line)) > 1e-6:
                    continue
            except Exception:
                pass

        # extract american price
        american = None
        try:
            american = float(price)
        except Exception:
            if isinstance(price, dict):
                for k in ("american","price","odds_american"):
                    if k in price:
                        try:
                            american = float(price[k]); break
                        except: pass
        if american is None:
            continue

        # FILTER by |american| <= ODDS_MAX_ABS
        if not _price_ok(american):
            continue

        # final line number
        try:
            line = float(point) if point is not None else float(target_line)
        except Exception:
            line = float(target_line)
        return line, float(american)
    return None

# ---- Public API ----

def get_fd_mlb_price(player_name: str, prop: str) -> Optional[Tuple[float,float]]:
    """
    prop: 'HITS_0_5' or 'TB_1_5'
    Returns: (line, american) for the Over, filtered to |american| <= ODDS_MAX_ABS; else None.
    """
    rows = _request_mlb_props()
    want_over = True
    if prop == "HITS_0_5":
        market_key = "player_hits"; target = 0.5
    elif prop == "TB_1_5":
        market_key = "player_total_bases"; target = 1.5
    else:
        return None

    for key, m in _iter_fd_markets(rows):
        if key != market_key: 
            continue
        got = _extract_fd_outcome(key, m, player_name=player_name, want_over=want_over, target_line=target)
        if got: 
            return got
    return None

# Optional NFL hooks (filtered the same way). Enable when ready.
def get_fd_nfl_price(player_name: str, market_key: str) -> Optional[Tuple[float,float]]:
    rows = _request_nfl_props(market_key)
    for key, m in _iter_fd_markets(rows):
        if key != market_key: 
            continue
        # For NFL we often don't know target_line ahead of time; pass 0 and don't enforce line equality.
        got = _extract_fd_outcome(key, m, player_name=player_name, want_over=True, target_line=0.0)
        if got:
            return got
    return None
