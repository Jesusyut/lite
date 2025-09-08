from __future__ import annotations
import os, requests
from typing import Optional, Tuple, Dict, Any, List
from utils.rcache import cached_fetch

# ---- Robust base; ensure exactly one /sports ----
RAW_BASE = os.getenv("ODDS_BASE", "https://api.the-odds-api.com/v4").rstrip("/")
SPORTS_BASE = RAW_BASE if RAW_BASE.endswith("/sports") else RAW_BASE + "/sports"

ODDS_KEY       = os.getenv("ODDS_API_KEY")
ODDS_REGION    = os.getenv("ODDS_REGION", "us")
ODDS_MAX_ABS   = float(os.getenv("ODDS_MAX_ABS", "250"))  # keep only |american| <= this
EVENTS_MAX     = int(os.getenv("ODDS_EVENTS_MAX", "16"))  # how many events to scan
ODDS_TIMEOUT_S = float(os.getenv("ODDS_TIMEOUT_S", "10"))

def _price_ok(x: float) -> bool:
    try:
        return abs(float(x)) <= ODDS_MAX_ABS
    except Exception:
        return False

def _req(url: str, params: Dict[str, Any], *, ttl=600):
    if not ODDS_KEY:
        raise RuntimeError("ODDS_API_KEY missing")
    p = dict(params or {}); p["apiKey"] = ODDS_KEY
    def call():
        r = requests.get(url, params=p, timeout=ODDS_TIMEOUT_S)
        r.raise_for_status()
        js = r.json()
        if isinstance(js, dict) and js.get("message"):
            # The Odds API returns {"message": "..."} on errors
            raise RuntimeError(js["message"])
        return js
    # cache key includes URL + params
    return cached_fetch("oddsfd", url, p, call, ttl=ttl, stale_ttl=3*86400)

# ---------- Event lists ----------
def _events(sport_path: str) -> List[Dict[str, Any]]:
    url = f"{SPORTS_BASE}/{sport_path}/events"
    js = _req(url, {}, ttl=300)
    return js if isinstance(js, list) else js.get("events", []) if isinstance(js, dict) else []

def _mlb_events() -> List[Dict[str, Any]]:
    return _events("baseball_mlb")

def _nfl_events() -> List[Dict[str, Any]]:
    return _events("americanfootball_nfl")

# ---------- Event odds ----------
def _event_odds(sport_path: str, event_id: str, markets_csv: str) -> Dict[str, Any]:
    # Player markets must come from the /events/{id}/odds endpoint. :contentReference[oaicite:2]{index=2}
    url = f"{SPORTS_BASE}/{sport_path}/events/{event_id}/odds"
    return _req(url, {
        "regions": ODDS_REGION,
        "bookmakers": "fanduel",
        "markets": markets_csv,
        "oddsFormat": "american",
    }, ttl=300)

# ---------- Helpers ----------
def _parse_american(price) -> Optional[float]:
    if isinstance(price, (int, float)):
        return float(price)
    if isinstance(price, str):
        s = price.strip().upper()
        if s in ("EVEN", "EV"):
            return 100.0
        try:
            return float(price)
        except Exception:
            return None
    if isinstance(price, dict):
        for k in ("american", "odds_american", "price"):
            v = price.get(k)
            if isinstance(v, str):
                ss = v.strip().upper()
                if ss in ("EVEN", "EV"):
                    return 100.0
                try:
                    return float(v)
                except Exception:
                    continue
            elif isinstance(v, (int, float)):
                return float(v)
    return None

def _iter_fd_markets(rows: List[Dict[str, Any]]):
    """Yield (market_key, market_dict) for FanDuel only across all event-odds payloads."""
    for ev in rows or []:
        for bm in (ev.get("bookmakers") or []):
            bk = (bm.get("key") or bm.get("title") or "").lower()
            if bk != "fanduel":
                continue
            for m in (bm.get("markets") or []):
                yield m.get("key"), m

def _pull_outcome(o: Dict[str, Any]) -> Optional[Tuple[str, str, Optional[float], float]]:
    """
    Return (side, player_name, line, american) for an outcome.
    side is 'over' or 'under'.
    """
    name = str(o.get("name", "")).strip().lower()  # usually 'over' / 'under'
    desc = str(o.get("description") or o.get("participant") or o.get("player") or "").strip()
    if not name or not desc:
        return None
    if "over" not in name and "under" not in name:
        return None
    american = _parse_american(o.get("price"))
    if american is None or not _price_ok(american):
        return None
    point = o.get("point", o.get("line"))
    try:
        line = float(point) if point is not None else None
    except Exception:
        line = None
    side = "over" if "over" in name else "under"
    return side, desc, line, float(american)

# ---------- Public: MLB ----------
def get_fd_mlb_price(player_name: str, prop: str) -> Optional[Tuple[float, float]]:
    """
    MLB fixed props (market keys per docs):
      HITS_0_5  -> batter_hits @ 0.5 (Over)
      TB_1_5    -> batter_total_bases @ 1.5 (Over)
    Market keys reference: batter_hits, batter_total_bases. :contentReference[oaicite:3]{index=3}
    """
    mk_map = {
        "HITS_0_5": ("batter_hits", 0.5),
        "TB_1_5":   ("batter_total_bases", 1.5),
    }
    mk, target = mk_map.get(prop, (None, None))
    if not mk:
        return None

    evs = _mlb_events()[:max(1, EVENTS_MAX)]
    rows: List[Dict[str, Any]] = []
    for ev in evs:
        ev_id = (ev.get("id") or ev.get("event_id") or ev.get("idEvent"))
        if not ev_id:
            continue
        js = _event_odds("baseball_mlb", str(ev_id), mk)
        if isinstance(js, dict):
            rows.append(js)

    needle = (player_name or "").lower()
    for key, m in _iter_fd_markets(rows):
        if key != mk:
            continue
        for o in (m.get("outcomes") or []):
            got = _pull_outcome(o)
            if not got:
                continue
            side, desc, ln, american = got
            if side != "over":
                continue
            if needle not in desc.lower():
                continue
            line = ln if ln is not None else target
            if line is None:
                continue
            # tolerate tiny drift; skip wild mismatches
            if abs(float(line) - float(target)) > 1.0:
                continue
            return float(line), float(american)
    return None

def list_fd_mlb_candidates() -> List[Dict[str, Any]]:
    """All FD MLB Over outcomes for hits(0.5)/total bases(1.5) within |american| <= ODDS_MAX_ABS."""
    out: List[Dict[str, Any]] = []
    targets = {"batter_hits": 0.5, "batter_total_bases": 1.5}
    prop_by_key = {"batter_hits": "HITS_0_5", "batter_total_bases": "TB_1_5"}

    evs = _mlb_events()[:max(1, EVENTS_MAX)]
    rows: List[Dict[str, Any]] = []
    for ev in evs:
        ev_id = (ev.get("id") or ev.get("event_id") or ev.get("idEvent"))
        if not ev_id:
            continue
        js = _event_odds("baseball_mlb", str(ev_id), "batter_hits,batter_total_bases")
        if isinstance(js, dict):
            rows.append(js)

    for key, m in _iter_fd_markets(rows):
        if key not in targets:
            continue
        target = targets[key]
        prop = prop_by_key[key]
        for o in (m.get("outcomes") or []):
            got = _pull_outcome(o)
            if not got:
                continue
            side, desc, ln, american = got
            if side != "over":
                continue
            line = ln if ln is not None else target
            if abs(float(line) - float(target)) > 1.0:
                continue
            out.append({
                "player_name": desc,
                "prop": prop,
                "line": float(line),
                "american": float(american),
            })
    return out

# ---------- Public: NFL ----------
def get_fd_nfl_quote(player_name: str, prop: str) -> Optional[Tuple[float, float]]:
    """
    NFL broader props (use market's live point). Market keys per docs: :contentReference[oaicite:4]{index=4}
      REC       -> player_receptions
      RUSH_YDS  -> player_rush_yds
      REC_YDS   -> player_reception_yds
      PASS_YDS  -> player_pass_yds
    """
    mk_map = {
        "REC":      "player_receptions",
        "RUSH_YDS": "player_rush_yds",
        "REC_YDS":  "player_reception_yds",
        "PASS_YDS": "player_pass_yds",
    }
    mk = mk_map.get(prop)
    if not mk:
        return None

    evs = _nfl_events()[:max(1, EVENTS_MAX)]
    rows: List[Dict[str, Any]] = []
    for ev in evs:
        ev_id = (ev.get("id") or ev.get("event_id") or ev.get("idEvent"))
        if not ev_id:
            continue
        js = _event_odds("americanfootball_nfl", str(ev_id), mk)
        if isinstance(js, dict):
            rows.append(js)

    needle = (player_name or "").lower()
    for key, m in _iter_fd_markets(rows):
        if key != mk:
            continue
        for o in (m.get("outcomes") or []):
            got = _pull_outcome(o)
            if not got:
                continue
            side, desc, ln, american = got
            if side != "over":
                continue
            if needle not in desc.lower():
                continue
            if ln is None:
                continue
            return float(ln), float(american)
    return None



