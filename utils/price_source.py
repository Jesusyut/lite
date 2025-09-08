from typing import Optional, Tuple, Dict, Any

def resolve_shop_quote(league: str, prop: str, player_name: str | None) -> Optional[Dict[str, float]]:
    """
    Returns {"line": float, "american": float} for FanDuel-only (filtered by |american| <= ODDS_MAX_ABS),
    or None if not available.
      MLB: HITS_0_5, TB_1_5 (fixed lines 0.5 / 1.5)
      NFL: REC, RUSH_YDS, REC_YDS, PASS_YDS (use market's point)
    """
    try:
        if not player_name:
            return None

        if league == "mlb":
            from services.odds_fanduel import get_fd_mlb_price
            got = get_fd_mlb_price(player_name, prop)
            if got:
                line, american = got
                return {"line": float(line), "american": float(american)}

        elif league == "nfl":
            from services.odds_fanduel import get_fd_nfl_quote
            got = get_fd_nfl_quote(player_name, prop)
            if got:
                line, american = got
                return {"line": float(line), "american": float(american)}

        return None
    except Exception:
        return None

# Back-compat: original function that returned only the price
def resolve_shop_price(league: str, prop: str, player_name: str | None, player_id: int | None):
    q = resolve_shop_quote(league, prop, player_name)
    return q["american"] if q else None
