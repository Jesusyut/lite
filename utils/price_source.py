# utils/price_source.py
from typing import Optional

def resolve_shop_price(league: str, prop: str, player_name: str | None, player_id: int | None) -> Optional[float]:
    try:
        from services.odds_adapter import get_price
        return get_price(league, prop, player_name=player_name, player_id=player_id)
    except Exception:
        return None
