import os
from datetime import datetime, timedelta, date

from apscheduler.schedulers.background import BackgroundScheduler
from pytz import timezone

from cache_ttl import cached_fetch, cache_set
from mlb import fetch_players_map, fetch_schedule, fetch_player_season, fetch_player_gamelogs, compute_last10_from_logs

PHOENIX_TZ = timezone("America/Phoenix")

SLOW_TTL = 24 * 3600
FAST_TTL = 15 * 60

def _today_local() -> date:
    return datetime.now(PHOENIX_TZ).date()

def warm_daily_deep() -> None:
    today = _today_local()
    players_blob = cached_fetch(f"mlb:{today}:players", SLOW_TTL, fetch_players_map)
    players = players_blob.get("players", {}) if isinstance(players_blob, dict) else {}

    def _season_all():
        out = {}
        for pid in players.keys():
            try:
                out[pid] = fetch_player_season(pid)
            except Exception as e:
                out[pid] = {"error": str(e)}
        return {"meta": {"cached_at": int(datetime.now().timestamp())}, "data": out}

    cached_fetch(f"mlb:{today}:season_agg", SLOW_TTL, _season_all)

    def _last10_all():
        out = {}
        for pid in players.keys():
            try:
                logs = fetch_player_gamelogs(pid, n=15)
                out[pid] = compute_last10_from_logs(logs)
            except Exception as e:
                out[pid] = {"error": str(e)}
        return {"meta": {"cached_at": int(datetime.now().timestamp())}, "data": out}

    cached_fetch(f"mlb:{today}:last10", SLOW_TTL, _last10_all)

def warm_midday_light() -> None:
    today = _today_local()
    def _sched():
        return fetch_schedule(today, today + timedelta(days=2))
    cached_fetch(f"mlb:{today}:schedule", SLOW_TTL, _sched)

def start_scheduler() -> BackgroundScheduler:
    sch = BackgroundScheduler(timezone=PHOENIX_TZ)
    sch.add_job(warm_daily_deep, 'cron', hour=5, minute=0)  # 05:00 Phoenix
    for hh in (5, 12, 17):  # 05:10, 12:10, 17:10 Phoenix
        sch.add_job(warm_midday_light, 'cron', hour=hh, minute=10)
    sch.start()
    return sch
