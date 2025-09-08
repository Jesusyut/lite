# utils/price_source.py
from typing import Optional, Tuple

def resolve_shop_price(
    league: str,
    prop: str,
    player_name: str | None,
    player_id: int | None,
) -> Optional[Tuple[float, float]]:
    """
    Auto-resolve (line, american) from FanDuel via The Odds API when price is blank.

    MLB:
      HITS_0_5, TB_1_5 -> event-wise odds using batter_* markets.
    NFL:
      REC, RUSH_YDS, REC_YDS, PASS_YDS -> event-wise odds using player_* markets.
    """
    try:
        if league == "mlb" and player_name:
            from services.odds_fanduel import get_fd_mlb_price
            got = get_fd_mlb_price(player_name, prop)
            if got:
                line, american = got
                return float(line), float(american)

        if league == "nfl" and player_name:
            from services.odds_fanduel import get_fd_nfl_quote
            got = get_fd_nfl_quote(player_name, prop)
            if got:
                line, american = got
                return float(line), float(american)

        return None
    except Exception:
        return None

# Back-compat: older code expects only the american price
def resolve_shop_quote(
    league: str,
    prop: str,
    player_name: str | None,
    player_id: int | None,
) -> Optional[float]:
    got = resolve_shop_price(league, prop, player_name, player_id)
    if got is None:
        return None
    _line, american = got
    return float(american)


