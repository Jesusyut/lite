# How to integrate the MLB Cache Kit

## 1) Install dependencies
Add these to your requirements (or `pip install -r requirements-mlb-cache.txt`):
- apscheduler
- redis
- requests
- pytz

## 2) Environment variables
Set in your Render/host:
- REDIS_URL=redis://default:password@host:port/0
- RUN_SCHEDULER=true          # only on ONE worker; set false elsewhere
- MLB_SEASON=2025             # optional; defaults to current year

## 3) Wire scheduler in your Flask app (app.py or main.py)
```python
from flask import Flask
from app_scheduler import maybe_start_scheduler

app = Flask(__name__)
maybe_start_scheduler()  # starts APScheduler if RUN_SCHEDULER=true

# ... your routes ...
```

If you use an app factory:
```python
def create_app():
    app = Flask(__name__)
    maybe_start_scheduler()
    return app
```

## 4) Read from cache inside your routes
Your request path should be **read-only** (no upstream calls). Example:
```python
from datetime import datetime
from pytz import timezone
from cache_ttl import cache_get
from flask import jsonify

PHOENIX = timezone("America/Phoenix")

@app.get("/debug/mlb/context")
def debug_context():
    today = datetime.now(PHOENIX).date()
    last10 = cache_get(f"mlb:{today}:last10") or {}
    season = cache_get(f"mlb:{today}:season_agg") or {}
    sched  = cache_get(f"mlb:{today}:schedule") or {}
    return jsonify({
        "last10_keys": len((last10.get("data") or {})),
        "season_keys": len((season.get("data") or {})),
        "has_schedule": bool(sched),
    })
```

## 5) Attach to your props pipeline
- After you pull odds, enhance each player prop by looking up the cached blobs:
  - players map: `cache_get(f"mlb:{today}:players")`
  - season aggregates: `cache_get(f"mlb:{today}:season_agg")["data"].get(player_id)`
  - last-10: `cache_get(f"mlb:{today}:last10")["data"].get(player_id)`
- Do **not** fetch from MLB inside the request handler.

## 6) Scale notes
- Deep warm once at 05:00 Phoenix; light schedule refresh at 05:10/12:10/17:10.
- Keep Redis memory in check by storing compact summaries rather than raw logs (or persist raw in SQLite if needed).
- Consider sharding deep jobs by team/alpha to reduce single-job pressure.
