# utils/apisports_env.py
from __future__ import annotations
import os
from typing import Dict, Tuple

# Known default bases per sport if not provided
_DEFAULT_BASES = {
    "MLB": "https://v1.baseball.api-sports.io",
    "NFL": "https://v1.american-football.api-sports.io",
    "NBA": "https://v1.basketball.api-sports.io",
    "NHL": "https://v1.hockey.api-sports.io",
    "UFC": "https://v1.mma.api-sports.io",
}

def sport_cfg(sport: str) -> Tuple[str, Dict[str, str]]:
    """
    Returns (base_url, headers) for a sport.
    Precedence:
      1) APISPORTS_<SPORT>_RAPIDAPI_*  (RapidAPI)
      2) APISPORTS_<SPORT>_BASE + APISPORTS_<SPORT>_KEY (direct)
      3) APISPORTS_RAPIDAPI_* (generic RapidAPI)
      4) APISPORTS_BASE + APISPORTS_KEY (generic direct)
      5) Default base by sport (if base missing)
    """
    S = sport.strip().upper()

    # Sport-specific RapidAPI
    rapid_key = os.getenv(f"APISPORTS_{S}_RAPIDAPI_KEY")
    rapid_host = os.getenv(f"APISPORTS_{S}_RAPIDAPI_HOST")

    # Sport-specific direct
    base = os.getenv(f"APISPORTS_{S}_BASE")
    key  = os.getenv(f"APISPORTS_{S}_KEY")

    # Generic fallbacks
    if not rapid_key:
        rapid_key = os.getenv("APISPORTS_RAPIDAPI_KEY")
        if not rapid_host:
            rapid_host = os.getenv("APISPORTS_RAPIDAPI_HOST")

    if not base:
        base = os.getenv("APISPORTS_BASE")
    if not key:
        key = os.getenv("APISPORTS_KEY")

    # Choose provider: prefer RapidAPI if rapid_key present
    if rapid_key:
        if not rapid_host:
            # Best-effort host default from base or sport
            rapid_host = (_guess_host_from_base(base) 
                          or f"api-{_sport_slug(S)}.p.rapidapi.com")
        headers = {"x-rapidapi-key": rapid_key, "x-rapidapi-host": rapid_host}
        if not base:
            # base is optional for RapidAPI; but if set, we use it.
            base = f"https://{rapid_host}"
    else:
        # Direct mode
        if not key:
            raise RuntimeError(f"API-SPORTS: missing key for {S} (set APISPORTS_{S}_KEY or APISPORTS_KEY)")
        headers = {"x-apisports-key": key}
        if not base:
            base = _DEFAULT_BASES.get(S) or "https://v1.baseball.api-sports.io"

    return base.rstrip("/"), headers

def _sport_slug(S: str) -> str:
    # Map sport to the RapidAPI slug
    return {
        "MLB": "baseball",
        "NFL": "american-football",
        "NBA": "basketball",
        "NHL": "hockey",
        "UFC": "mma",
    }.get(S, S.lower())

def _guess_host_from_base(base: str | None) -> str | None:
    if not base: return None
    try:
        host = base.split("//",1)[1].split("/",1)[0]
        return host or None
    except Exception:
        return None
