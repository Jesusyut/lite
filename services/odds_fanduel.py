from __future__ import annotations
import os, requests
from typing import Any, Dict, List, Optional, Tuple
from utils.rcache import cached_fetch

# ----------------- config -----------------
ODDS_BASE = os.getenv("ODDS_BASE", "https://api.the-odds-api.com/v4/sports").rstrip("/")
ODDS_KEY  = os.getenv("ODDS_API_KEY")
ODDS_MAX_ABS = float(os.getenv("ODDS_MAX_ABS", "250"))  # ± cap for prices

def _price_ok(american: Any) -> bool:
    try:
        return abs(float(american)) <= ODDS_MAX_ABS
    except Exception:
        return False

def _to_float(x, default=None):
    try: return float(x)
    except Exception: return default

# ----------------- low-level fetchers -----------------
def _get_events(sport_key: str, limit: int) -> List[Dict[str, Any]]:
    """GET /{sport}/events"""
    if not ODDS_KEY:
        raise RuntimeError("ODDS_API_KEY missing")
    url = f"{ODDS_BASE}/{sport_key}/events"
    params = {"apiKey": ODDS_KEY}
    def call():
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    evs = cached_fetch("oddsfd", f"/{sport_key}/events", params, call, ttl=120, stale_ttl=600)
    # Sort by commence_time so we scan near-term games first
    try:
        evs = sorted(evs, key=lambda e: e.get("commence_time",""))
    except Exception:
        pass
    return evs[:max(1, int(limit))]

def _get_event_odds(sport_key: str, event_id: str, markets_csv: str) -> Dict[str, Any]:
    """GET /{sport}/events/{id}/odds (FanDuel only)"""
    if not ODDS_KEY:
        raise RuntimeError("ODDS_API_KEY missing")
    url = f"{ODDS_BASE}/{sport_key}/events/{event_id}/odds"
    params = {
        "regions": "us",
        "bookmakers": "fanduel",
        "markets": markets_csv,
        "oddsFormat": "american",
        "apiKey": ODDS_KEY,
    }
    def call():
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    return cached_fetch("oddsfd", f"/{sport_key}/events/{event_id}/odds", params, call, ttl=120, stale_ttl=600)

def _iter_fd_markets(js: Dict[str, Any], allowed: set[str]):
    for bm in js.get("bookmakers", []):
        if str(bm.get("key","")).lower() != "fanduel":
            continue
        for m in bm.get("markets", []):
            k = m.get("key")
            if k in allowed:
                yield k, m

def _american_from_price(price_obj: Any) -> Optional[float]:
    # price could be number or dict
    try:
        return float(price_obj)
    except Exception:
        if isinstance(price_obj, dict):
            for k in ("american", "price", "odds_american"):
                if k in price_obj:
                    v = _to_float(price_obj[k])
                    if v is not None:
                        return v
    return None

# ----------------- MLB helpers -----------------
def _extract_batter_outcomes(market_key: str, market: Dict[str, Any],
                             target_line: float) -> List[Tuple[str, float, float]]:
    """
    From a FanDuel market, pull Over outcomes that match our target line.
    Returns list of tuples: (player_name, line, american)
    """
    out: List[Tuple[str, float, float]] = []
    for o in market.get("outcomes", []):
        name = str(o.get("name","")).lower()
        side = str(o.get("side","")).lower()
        is_over = ("over" in name) or (side == "over")
        if not is_over:
            continue

        point = o.get("point", o.get("line"))
        line = _to_float(point, target_line)
        # Strict to our SKUs only
        if abs(line - float(target_line)) > 1e-6:
            continue

        american = _american_from_price(o.get("price", o.get("odds_american", o.get("american"))))
        if american is None or not _price_ok(american):
            continue

        desc = str(o.get("description") or o.get("participant") or o.get("player") or "").strip()
        if not desc:
            continue

        out.append((desc, float(line), float(american)))
    return out

def list_fd_mlb_candidates(max_events: int = 8, per_event_cap: int = 30) -> List[Dict[str, Any]]:
    """
    Round-robin list of MLB candidates across upcoming events:
      markets: batter_hits (0.5), batter_total_bases (1.5)
      returns [{player_name, prop, line, american}]
    """
    events = _get_events("baseball_mlb", max_events=max_events)
    all_lists: List[List[Dict[str, Any]]] = []

    for ev in events:
        js = _get_event_odds("baseball_mlb", ev["id"], "batter_hits,batter_total_bases")
        per_ev: List[Dict[str, Any]] = []

        for key, m in _iter_fd_markets(js, {"batter_hits", "batter_total_bases"}):
            target = 0.5 if key == "batter_hits" else 1.5
            prop   = "HITS_0_5" if key == "batter_hits" else "TB_1_5"
            for player, line, american in _extract_batter_outcomes(key, m, target):
                per_ev.append({
                    "player_name": player,
                    "prop": prop,
                    "line": float(line),
                    "american": float(american),
                })
                if len(per_ev) >= per_event_cap:
                    break
            if len(per_ev) >= per_event_cap:
                break

        if per_ev:
            all_lists.append(per_ev)

    # round-robin merge to avoid one-game domination
    merged: List[Dict[str, Any]] = []
    i = 0
    while True:
        progressed = False
        for lst in all_lists:
            if i < len(lst):
                merged.append(lst[i])
                progressed = True
        if not progressed:
            break
        i += 1
    return merged

def get_fd_mlb_price(player_name: str, prop: str) -> Optional[Tuple[float, float]]:
    """
    Try to find an FD price for a specific MLB player & prop across near-term events.
    Returns (line, american) or None.
    """
    target = 0.5 if prop == "HITS_0_5" else 1.5 if prop == "TB_1_5" else None
    key    = "batter_hits" if prop == "HITS_0_5" else "batter_total_bases" if prop == "TB_1_5" else None
    if target is None or key is None:
        return None

    needle = player_name.lower()
    for ev in _get_events("baseball_mlb", 10):
        js = _get_event_odds("baseball_mlb", ev["id"], key)
        for _, m in _iter_fd_markets(js, {key}):
            for o in _extract_batter_outcomes(key, m, target):
                player, line, american = o
                if needle in player.lower():
                    return line, american
    return None

# ----------------- NFL quotes -----------------
_NFL_MAP = {
    "REC":      ("americanfootball_nfl", "player_receptions"),
    "RUSH_YDS": ("americanfootball_nfl", "player_rush_yds"),
    "REC_YDS":  ("americanfootball_nfl", "player_reception_yds"),
    "PASS_YDS": ("americanfootball_nfl", "player_pass_yds"),
}

def get_fd_nfl_quote(player_name: str, prop: str) -> Optional[Tuple[float, float]]:
    """
    Return (line, american) for Over on common NFL props.
    """
    tup = _NFL_MAP.get(prop)
    if not tup:
        return None
    sport_key, market_key = tup
    needle = player_name.lower()

    for ev in _get_events(sport_key, 8):
        js = _get_event_odds(sport_key, ev["id"], market_key)
        for _, m in _iter_fd_markets(js, {market_key}):
            for o in m.get("outcomes", []):
                # Over only
                name = str(o.get("name","")).lower()
                side = str(o.get("side","")).lower()
                if "over" not in name and side != "over":
                    continue

                desc = str(o.get("description") or o.get("participant") or o.get("player") or "")
                if needle not in desc.lower():
                    continue

                american = _american_from_price(o.get("price", o.get("odds_american", o.get("american"))))
                if american is None or not _price_ok(american):
                    continue

                line = _to_float(o.get("point", o.get("line")), 0.0)
                return float(line), float(american)
    return None



