from __future__ import annotations
import os, requests
from typing import Optional, Tuple, Dict, Any, List
from utils.rcache import cached_fetch

# -------------------- Config --------------------
ODDS_BASE       = os.getenv("ODDS_BASE", "https://api.the-odds-api.com/v4/sports")
ODDS_KEY        = os.getenv("ODDS_API_KEY")
ODDS_REGION     = os.getenv("ODDS_REGION", "us")
ODDS_MAX_ABS    = float(os.getenv("ODDS_MAX_ABS", "250"))          # inclusive
USE_EVENTWISE   = os.getenv("ODDS_EVENTWISE", "0") == "1"          # 1 => /events + /event-odds
EVENTS_MAX      = int(os.getenv("ODDS_EVENTS_MAX", "14"))          # only used in event-wise mode
ODDS_TIMEOUT_S  = float(os.getenv("ODDS_TIMEOUT_S", "20"))

def _price_ok(american: float) -> bool:
    try:
        return abs(float(american)) <= ODDS_MAX_ABS
    except Exception:
        return False

# -------------------- HTTP helpers --------------------
def _req(path: str, params: Dict[str, Any], *, ttl=600):
    if not ODDS_KEY:
        raise RuntimeError("ODDS_API_KEY missing")
    p = dict(params or {})
    p["apiKey"] = ODDS_KEY
    url = f"{ODDS_BASE}{path}"

    def call():
        r = requests.get(url, params=p, timeout=ODDS_TIMEOUT_S)
        r.raise_for_status()
        return r.json()

    # cache fresh + allow stale for resiliency
    return cached_fetch("oddsfd", path, p, call, ttl=ttl, stale_ttl=3 * 86400)

# ---- MLB bulk ----
def _request_mlb_props_bulk() -> List[Dict[str, Any]]:
    return _req(
        "/baseball_mlb/odds",
        {
            "regions": ODDS_REGION,
            "bookmakers": "fanduel",
            "markets": "player_hits,player_total_bases",
            "oddsFormat": "american",
        },
        ttl=600,
    )

# ---- MLB event-wise ----
def _request_events_mlb() -> List[Dict[str, Any]]:
    # events endpoint: lightweight list of events (per docs)
    return _req("/baseball_mlb/events", {}, ttl=300)

def _request_event_odds_mlb(event_id: str, markets_csv: str) -> Dict[str, Any]:
    return _req(
        f"/baseball_mlb/events/{event_id}/odds",
        {
            "regions": ODDS_REGION,
            "bookmakers": "fanduel",
            "markets": markets_csv,  # e.g., "player_hits,player_total_bases"
            "oddsFormat": "american",
        },
        ttl=600,
    )

# ---- NFL bulk (broader props) ----
def _request_nfl_props(markets_csv: str) -> List[Dict[str, Any]]:
    return _req(
        "/americanfootball_nfl/odds",
        {
            "regions": ODDS_REGION,
            "bookmakers": "fanduel",
            "markets": markets_csv,
            "oddsFormat": "american",
        },
        ttl=600,
    )

# -------------------- Schema iterators / parsing --------------------
def _iter_fd_markets(events: List[Dict[str, Any]]):
    """
    Iterate FanDuel markets across a list of event objects.
    Accepts both bulk-odds (list-of-events) and event-odds (single-event) shapes.
    Yields (market_key, market_dict).
    """
    for ev in events or []:
        for bm in ev.get("bookmakers", []) or []:
            # v4 has both key ('fanduel') and title ('FanDuel'); accept either
            bk = (bm.get("key") or bm.get("title") or "").lower()
            if bk != "fanduel":
                continue
            for m in bm.get("markets", []) or []:
                yield m.get("key"), m

def _pull_outcome(o: Dict[str, Any]) -> Optional[Tuple[str, str, Optional[float], float]]:
    """
    Parse a single outcome using the v4 schema fields:
        name         -> 'Over' / 'Under'
        description  -> player name (for player props)
        point        -> line (float or None)
        price        -> american odds when oddsFormat=american
    Returns (side, player_name, line_or_None, american) or None if invalid/out-of-range.
    """
    name = str(o.get("name", "")).strip()
    # player descriptor lives here for player props
    desc = str(o.get("description") or o.get("participant") or o.get("player") or "").strip()
    point = o.get("point", None)
    price = o.get("price", None)

    if not name or not desc or price is None:
        return None

    side = name.lower()
    if "over" not in side and "under" not in side:
        return None

    # odds are already american when oddsFormat=american
    try:
        american = float(price)
    except Exception:
        # some providers nest alt keys
        if isinstance(price, dict):
            for k in ("american", "odds_american", "price"):
                if k in price:
                    try:
                        american = float(price[k]); break
                    except Exception:
                        pass
            else:
                return None
        else:
            return None

    if not _price_ok(american):
        return None

    try:
        ln = float(point) if point is not None else None
    except Exception:
        ln = None

    return ("over" if "over" in side else "under", desc, ln, float(american))

# -------------------- Public: MLB price lookup --------------------
def get_fd_mlb_price(player_name: str, prop: str) -> Optional[Tuple[float, float]]:
    """
    MLB:
      HITS_0_5 -> player_hits @ 0.5 (Over)
      TB_1_5   -> player_total_bases @ 1.5 (Over)
    """
    market_key = {"HITS_0_5": "player_hits", "TB_1_5": "player_total_bases"}.get(prop)
    target = 0.5 if prop == "HITS_0_5" else (1.5 if prop == "TB_1_5" else None)
    if not market_key or target is None:
        return None

    # source rows (bulk or event-wise)
    rows: List[Dict[str, Any]] = []
    if USE_EVENTWISE:
        evs = _request_events_mlb() or []
        for ev in evs[:max(1, EVENTS_MAX)]:
            ev_id = ev.get("id")
            if not ev_id:
                continue
            data = _request_event_odds_mlb(ev_id, market_key)
            if data and isinstance(data, dict):
                rows.append(data)
    else:
        rows = _request_mlb_props_bulk()

    # scan for player outcome
    pneedle = (player_name or "").lower()
    for key, m in _iter_fd_markets(rows):
        if key != market_key:
            continue
        for o in m.get("outcomes", []) or []:
            res = _pull_outcome(o)
            if not res:
                continue
            side, desc, ln, american = res
            if side != "over":
                continue
            if pneedle not in desc.lower():
                continue
            # accept missing point; fall back to target; allow tiny drift (e.g., TB 2.5 alts)
            line = ln if ln is not None else target
            if line is None:
                continue
            if abs(float(line) - float(target)) > 1.0:
                continue
            return float(line), float(american)

    return None

# -------------------- Public: NFL quote (broader props) --------------------
def get_fd_nfl_quote(player_name: str, prop: str) -> Optional[Tuple[float, float]]:
    """
    NFL (uses market's current point):
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
    pneedle = (player_name or "").lower()

    for key, m in _iter_fd_markets(rows):
        if key != market_key:
            continue
        for o in m.get("outcomes", []) or []:
            res = _pull_outcome(o)
            if not res:
                continue
            side, desc, ln, american = res
            if side != "over":
                continue
            if pneedle not in desc.lower():
                continue
            # For NFL we WANT the live market line, so require ln to exist.
            if ln is None:
                continue
            return float(ln), float(american)

    return None

# -------------------- Public: MLB candidates for Top Picks --------------------
def list_fd_mlb_candidates() -> List[Dict[str, Any]]:
    """
    Return FanDuel MLB Over outcomes for hits(0.5) / total bases(1.5) within ±ODDS_MAX_ABS:
      [{player_name, prop, line, american}]
    Honors event-wise mode if enabled.
    """
    out: List[Dict[str, Any]] = []
    target_by_key = {"player_hits": 0.5, "player_total_bases": 1.5}
    prop_by_key   = {"player_hits": "HITS_0_5", "player_total_bases": "TB_1_5"}

    # source rows
    rows: List[Dict[str, Any]] = []
    if USE_EVENTWISE:
        evs = _request_events_mlb() or []
        for ev in evs[:max(1, EVENTS_MAX)]:
            ev_id = ev.get("id")
            if not ev_id:
                continue
            rows.append(_request_event_odds_mlb(ev_id, "player_hits,player_total_bases"))
    else:
        rows = _request_mlb_props_bulk()

    for key, m in _iter_fd_markets(rows):
        if key not in target_by_key:
            continue
        target = target_by_key[key]
        prop   = prop_by_key[key]
        for o in m.get("outcomes", []) or []:
            res = _pull_outcome(o)
            if not res:
                continue
            side, desc, ln, american = res
            if side != "over":
                continue
            line = ln if ln is not None else target
            # skip wild alt lines; allow small drift
            if abs(float(line) - float(target)) > 1.0:
                continue
            out.append({
                "player_name": desc,
                "prop": prop,
                "line": float(line),
                "american": float(american),
            })

    return out


