# Return a single american price for a player/prop, or None.
# Wire this to YOUR odds provider modules. Safe to leave as-is if you don't have them.

from typing import Optional

def get_price(league: str, prop: str, player_name: str | None = None, player_id: int | None = None) -> Optional[float]:
    try:
        if league == "mlb":
            try:
                from odds_api import fetch_player_props
            except Exception:
                return None
            market_map = {
                "HITS_0_5": "player_hits_over_under",
                "TB_1_5":   "player_total_bases_over_under",
            }
            market = market_map.get(prop)
            if not market or not player_name:
                return None
            data = fetch_player_props(market=market)  # add date/filters in your fn
            for row in data or []:
                if row.get("player") and player_name.lower() in str(row["player"]).lower():
                    offer = (row.get("shop") or {}).get("over") or {}
                    if "american" in offer:
                        return float(offer["american"])
            return None

        elif league == "nfl":
            try:
                from nfl_odds_api import fetch_nfl_player_props
            except Exception:
                return None
            market_map = {
                "REC_3_5":   "player_receptions_over_under",
                "RUSH_49_5": "player_rushing_yards_over_under",
            }
            market = market_map.get(prop)
            if not market or not player_name:
                return None
            data = fetch_nfl_player_props(market=market)
            for row in data or []:
                if row.get("player") and player_name.lower() in str(row["player"]).lower():
                    offer = (row.get("shop") or {}).get("over") or {}
                    if "american" in offer:
                        return float(offer["american"])
            return None

        else:
            return None
    except Exception:
        return None

