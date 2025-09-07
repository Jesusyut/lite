# services/odds_adapter.py
# Goal: return an american price for a single player prop, or None.
# You already have modules like odds_api / nfl_odds_api; use them here.

from typing import Optional

def get_price(league: str, prop: str, player_name: str | None = None, player_id: int | None = None) -> Optional[float]:
    """
    league: 'mlb' | 'nfl'
    prop:   'HITS_0_5'|'TB_1_5'|'REC_3_5'|'RUSH_49_5'
    return: american price (e.g., -120) or None
    """
    try:
        if league == "mlb":
            # Example with your existing odds module – adapt to your actual shape
            from odds_api import fetch_player_props  # you had this earlier
            market_map = {
                "HITS_0_5": "player_hits_over_under",
                "TB_1_5":   "player_total_bases_over_under",
            }
            market = market_map.get(prop)
            if not market or not player_name: return None
            data = fetch_player_props(market=market)  # add date/filters as your fn supports
            # Find the matching player & side (assume 'over')
            for row in data or []:
                if row.get("player") and player_name.lower() in row["player"].lower():
                    offer = (row.get("shop") or {}).get("over")  # adjust to your structure
                    if offer and "american" in offer:
                        return float(offer["american"])
            return None

        elif league == "nfl":
            from nfl_odds_api import fetch_nfl_player_props  # your module
            market_map = {
                "REC_3_5":   "player_receptions_over_under",
                "RUSH_49_5": "player_rushing_yards_over_under",
            }
            market = market_map.get(prop)
            if not market or not player_name: return None
            data = fetch_nfl_player_props(market=market)
            for row in data or []:
                if row.get("player") and player_name.lower() in row["player"].lower():
                    offer = (row.get("shop") or {}).get("over")
                    if offer and "american" in offer:
                        return float(offer["american"])
            return None

        else:
            return None
    except Exception:
        return None
