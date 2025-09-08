from __future__ import annotations
import os, requests
from typing import Optional, Tuple, Dict, Any, List
from utils.rcache import cached_fetch

ODDS_BASE     = os.getenv("ODDS_BASE", "https://api.the-odds-api.com/v4/sports")
ODDS_KEY      = os.getenv("ODDS_API_KEY")
ODDS_MAX_ABS  = float(os.getenv("ODDS_MAX_ABS", "250"))  # inclusive

def _price_ok(american) -> bool:
    try:
        return abs(float(american)) <= ODDS_MAX_ABS
    except Exception:
        return False

# ---------- Provider calls ----------
def _request_mlb_props() -> List[Dict[str, Any]]:
    # GET /baseball_mlb/odds?markets=player_hits,player_total_bases&bookmakers=fanduel...
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
    # GET /americanfootball_nfl/odds?markets=<csv>&bookmakers=fanduel...
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

# ---------- Normalize / extract ----------
def _iter_fd_markets(rows: List[Dict[str, Any]]):
    """Yield (market_key, market_dict) for FanDuel only across all events."""
    for ev in rows or []:
        for bm in ev.get("bookmakers", []):
            if str(bm.get("title","")).lower() != "fanduel":
                continue
            for m in bm.get("markets", []):
                yield m.get("key"), m

def _extract_fd_outcome(market_key: str, market: Dict[str, Any],
                        player_name: str, want_over: bool, target_line: float | None) -> Optional[Tuple[float,float]]:
    """
    Returns (line, american) for the requested player + Over/Under if:
      - player matches, correct direction, and
      - (if target_line provided) outcome point equals it, and
      - |american| <= ODDS_MAX_ABS
    """
    pneedle = player_name.lower()
    for o in market.get("outcomes", []):
        name = str(o.get("name",""))
        desc = str(o.get("description") or o.get("participant") or o.get("player") or "")
        point = o.get("point", o.get("line"))
        price = o.get("price", o.get("odds_american", o.get("american")))

        is_over  = ("over"  in name.lower()) or (o.get("side","").lower() == "over")
        is_under = ("under" in name.lower()) or (o.get("side","").lower() == "under")
        if want_over and not is_over: continue
        if not want_over and not is_under: continue

        player_ok = (pneedle in desc.lower()) or (pneedle in name.lower())
        if not player_ok: continue

        # Enforce line if given (MLB fixed); NFL: target_line is None so we accept market point.
        if target_line is not None and point is not None:
            try:
                if abs(float(point) - float(target_line)) > 1e-6:
                    continue
            except Exception:
                pass

        # price -> american
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
        if american is None or not _price_ok(american):
            continue

        # determine line
        try:
            line = float(point) if point is not None else (float(target_line) if target_line is not None else 0.0)
        except Exception:
            line = float(target_line) if target_line is not None else 0.0

        return line, float(american)
    return None

# ---------- Public API ----------
def get_fd_mlb_price(player_name: str, prop: str) -> Optional[Tuple[float,float]]:
    """
    MLB fixed props:
      HITS_0_5 -> player_hits @ 0.5 (Over)
      TB_1_5   -> player_total_bases @ 1.5 (Over)
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

def get_fd_nfl_quote(player_name: str, prop: str) -> Optional[Tuple[float,float]]:
    """
    NFL broader props (use market's current point):
      REC      -> player_receptions
      RUSH_YDS -> player_rushing_yards
      REC_YDS  -> player_receiving_yards
      PASS_YDS -> player_passing_yards
    """
    mapping = {
        "REC":      "player_receptions",
        "RUSH_YDS": "player_rushing_yards",
        "REC_YDS":  "player_receiving_yards",
        "PASS_YDS": "player_passing_yards",
    }
    market_key = mapping.get(prop)
    if not market_key:
        return None

    rows = _request_nfl_props(market_key)
    for key, m in _iter_fd_markets(rows):
        if key != market_key: 
            continue
        # target_line=None -> accept the market's own point
        got = _extract_fd_outcome(key, m, player_name=player_name, want_over=True, target_line=None)
        if got:
            return got
    return None
# ---------- Public: candidate list for "Top Picks" (MLB) ----------
def list_fd_mlb_candidates() -> List[Dict[str, Any]]:
    """
    Return all FanDuel MLB Over outcomes for hits(0.5)/total bases(1.5)
    within the |american| <= ODDS_MAX_ABS filter:
      [{player_name, prop, line, american}]
    Notes:
      - Accept outcomes even if outcome['point'] is missing; fall back to the target.
      - Still require "Over".
    """
    rows = _request_mlb_props()
    out: List[Dict[str, Any]] = []
    for key, m in _iter_fd_markets(rows):
        if key not in ("player_hits", "player_total_bases"):
            continue
        target = 0.5 if key == "player_hits" else 1.5
        prop   = "HITS_0_5" if key == "player_hits" else "TB_1_5"

        for o in m.get("outcomes", []):
            name = str(o.get("name", ""))  # often "Over" / "Under"
            desc = str(o.get("description") or o.get("participant") or o.get("player") or "")
            point = o.get("point", o.get("line"))
            price = o.get("price", o.get("odds_american", o.get("american")))

            # Over only
            is_over = ("over" in name.lower()) or (o.get("side", "").lower() == "over")
            if not is_over:
                continue

            # Price (american) with ±ODDS_MAX_ABS filter
            american = None
            try:
                american = float(price)
            except Exception:
                if isinstance(price, dict):
                    for k in ("american", "price", "odds_american"):
                        if k in price:
                            try:
                                american = float(price[k]); break
                            except: pass
            if american is None or not _price_ok(american):
                continue

            # Line: accept missing 'point' (many payloads omit it) and fall back to target
            try:
                if point is None:
                    line = float(target)
                else:
                    line = float(point)
                    # If a point exists but differs wildly from target, skip
                    if abs(line - float(target)) > 1.0:  # allow tiny drift; TB can sometimes show 1.5/2.5
                        continue
            except Exception:
                line = float(target)

            # Player display name
            player_name = (desc or name).replace("Over", "").strip()
            if not player_name:
                continue

            out.append({
                "player_name": player_name,
                "prop": prop,
                "line": float(line),
                "american": float(american),
            })
    return out

