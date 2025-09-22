# app.py
from flask import Flask, request, jsonify, send_from_directory
from services.mlb import (
    todays_matchups, search_player,
    batter_trends_last10, resolve_player_id, batter_trends_last10_cached
)
from services.nfl import last5_trends
try:
    from services.nfl_apisports import search_player as api_search, player_last5_trends as api_last5
    HAVE_API = True
except Exception:
    HAVE_API = False

from utils.prob import american_to_prob
from utils.price_source import resolve_shop_price, resolve_shop_quote
from app_scheduler import maybe_start_scheduler

# ---- single Flask app (don’t create a second one) ----
app = Flask(__name__, static_url_path='', static_folder='static')
maybe_start_scheduler()  # starts APScheduler if RUN_SCHEDULER=true

@app.get("/")
def root():
    return send_from_directory("static", "index.html")

# --- MLB ---
@app.get("/api/mlb/today")
def mlb_today():
    return jsonify(todays_matchups())

@app.get("/api/mlb/search")
def mlb_search():
    q = request.args.get("q","").strip()
    if not q: return jsonify([])
    try:
        return jsonify(search_player(q)[:10])
    except Exception:
        return jsonify([])

@app.get("/api/mlb/player/<int:pid>/trends")
def mlb_player_trends(pid):
    nm = request.args.get("name","").strip() or None
    try:
        d = batter_trends_last10(pid, player_name=nm) or {}
        return jsonify({
            "n": d.get("n", 0),
            "hits_rate": float(d.get("hits_rate") or 0.0),
            "tb2_rate":  float(d.get("tb2_rate")  or 0.0),
            "hits_series": d.get("hits_series") or [],
            "tb2_series":  d.get("tb2_series")  or [],
        })
    except Exception:
        return jsonify({"n": 0, "hits_rate": 0.0, "tb2_rate": 0.0, "hits_series": [], "tb2_series": []})

# --- NFL (unchanged) ---
@app.get("/api/nfl/player/search")
def nfl_search():
    q = request.args.get("q","").strip()
    if not q or not HAVE_API: return jsonify([])
    try:
        js = api_search(q)
        out=[]
        for r in js.get("response", []):
            out.append({"id": r.get("id") or r.get("player",{}).get("id"),
                        "name": r.get("name") or r.get("player",{}).get("name")})
        return jsonify(out[:10])
    except Exception:
        return jsonify([])

@app.get("/api/nfl/player/<int:pid>/trends")
def nfl_player_trends(pid):
    season = int(request.args.get("season", "2024"))
    if HAVE_API:
        try:
            return jsonify(api_last5(pid, season))
        except Exception:
            pass
    name = request.args.get("name","")
    return jsonify(last5_trends(name))

# --- Evaluate (unchanged) ---
@app.post("/api/evaluate")
def evaluate():
    try:
        j = request.get_json() or {}
        league   = j.get("league")
        prop     = j.get("prop")
        american = j.get("american", None)
        used_line = None

        if american in (None, ""):
            quote = resolve_shop_price(
                league=league, prop=prop,
                player_name=j.get("player_name"),
                player_id=j.get("player_id"),
            )
            if isinstance(quote, tuple):
                used_line, american = quote
            elif isinstance(quote, (int, float)):
                american = quote

        p_break_even = american_to_prob(american) if american not in (None, "") else None

        if league == "mlb":
            name = (j.get("player_name") or "").strip()
            pid  = j.get("player_id")
            if not pid and name:
                try: pid = resolve_player_id(name)
                except Exception: pid = None
            if not pid and not name:
                return jsonify({"error": "MLB needs player_id or player_name"}), 400
            try:
                t = batter_trends_last10(int(pid) if pid else 0, player_name=name)
            except Exception:
                t = {}
            if prop == "HITS_0_5":
                p_trend = float(t.get("hits_rate") or 0.0) / 100.0
                used_line = 0.5 if used_line is None else used_line
            elif prop == "TB_1_5":
                p_trend = float(t.get("tb2_rate") or 0.0) / 100.0
                used_line = 1.5 if used_line is None else used_line
            else:
                return jsonify({"error": "bad mlb prop"}), 400

        elif league == "nfl":
            name = (j.get("player_name") or "").strip()
            if not name and not j.get("player_id"):
                return jsonify({"error": "NFL needs player_name"}), 400
            t = last5_trends(name)
            if prop == "REC":
                p_trend = float(t.get("rec_over35_rate") or 0.0) / 100.0
            elif prop == "RUSH_YDS":
                p_trend = float(t.get("rush_over49_rate") or 0.0) / 100.0
            elif prop in ("REC_YDS", "PASS_YDS"):
                p_trend = 0.0
            else:
                return jsonify({"error": "bad nfl prop"}), 400
        else:
            return jsonify({"error": "bad league"}), 400

        tag = "Fade"
        if p_trend >= 0.58: tag = "Straight"
        elif p_trend >= 0.52: tag = "Parlay leg"

        return jsonify({
            "p_trend": round(p_trend, 4),
            "break_even_prob": round(p_break_even, 4) if p_break_even is not None else None,
            "used_line": used_line,
            "tag": tag
        })
    except Exception as e:
        return jsonify({"error": f"evaluate failed: {type(e).__name__}: {e}"}), 500

# --- Top Picks (MLB): cache-first + background warm (single definition) ---
from concurrent.futures import ThreadPoolExecutor
import threading, time
from flask import current_app

_warm_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=3)

def _warm_names_and_trends_async(names_to_resolve, pids_to_warm):
    """
    Resolve missing names to ids, then warm trends for all pids (non-blocking).
    """
    from services.mlb import resolve_player_id, batter_trends_last10
    uniq_names = list({n for n in names_to_resolve if n})
    uniq_pids  = list({int(p) for p in pids_to_warm if p})

    def _resolve_and_warm(name):
        try:
            pid = resolve_player_id(name)  # may hit Stats API once
            if pid:
                batter_trends_last10(pid)  # warm trend cache
        except Exception:
            pass

    def _warm_pid(pid):
        try:
            batter_trends_last10(pid)
        except Exception:
            pass

    with _warm_lock:
        for nm in uniq_names:
            _executor.submit(_resolve_and_warm, nm)
        for pid in uniq_pids:
            _executor.submit(_warm_pid, pid)

@app.get("/api/top/mlb")
def top_mlb():
    try:
        from services.odds_fanduel import list_fd_mlb_candidates
        # IMPORTANT: cache-only reads here
        from services.mlb import resolve_player_id_cached, batter_trends_last10_cached
        from utils.prob import american_to_prob

        limit         = min(max(int(request.args.get("limit", "12")), 1), 24)
        max_cands     = min(max(int(request.args.get("max_cands", "40")), 5), 200)
        budget_s      = float(request.args.get("budget_s", "2.0"))      # quick first paint
        min_edge      = float(request.args.get("min_edge", "0.02"))
        min_trend     = float(request.args.get("min_trend", "0.55"))
        allow_neg     = request.args.get("allow_negative", "0") == "1"
        events        = max(1, int(request.args.get("events", "8")))
        per_event_cap = max(5, int(request.args.get("per_event_cap", "20")))

        t0 = time.time()
        try:
            cands = list_fd_mlb_candidates(max_events=events, per_event_cap=per_event_cap)
        except Exception as e:
            return jsonify({"error": f"odds fetch failed: {e}"}), 502

        cands = cands[:max_cands]

        picks, names_to_resolve, pids_to_warm = [], [], []

        for c in cands:
            if len(picks) >= limit or (time.time() - t0) > budget_s:
                break

            name = c["player_name"]
            pid  = resolve_player_id_cached(name)  # never hits network
            if not pid:
                # queue name for background resolution; skip for now
                names_to_resolve.append(name)
                continue

            t = batter_trends_last10_cached(pid)  # never hits network
            if t is None:
                # queue pid for background warm; skip for now
                pids_to_warm.append(pid)
                continue

            if c["prop"] == "HITS_0_5":
                p_trend = (t.get("hits_rate") or 0) / 100.0
                spark   = t.get("hits_series") or []
            else:
                p_trend = (t.get("tb2_rate") or 0) / 100.0
                spark   = t.get("tb2_series") or []

            p_be = american_to_prob(c["american"])
            if p_be is None:
                continue
            edge = p_trend - p_be

            if not allow_neg:
                if p_trend < min_trend: continue
                if edge   < min_edge:   continue

            tag = "Fade"
            if p_trend >= 0.58: tag = "Straight"
            elif p_trend >= 0.52: tag = "Parlay leg"

            picks.append({
                "player_id": pid, "player_name": name, "prop": c["prop"],
                "line": float(c["line"]), "american": float(c["american"]),
                "break_even_prob": round(p_be, 4), "p_trend": round(p_trend, 4),
                "edge": round(edge, 4), "tag": tag, "spark": spark
            })

        # fire background warmers (resolve missing names, then warm trends)
        if names_to_resolve or pids_to_warm:
            _warm_names_and_trends_async(names_to_resolve, pids_to_warm)

        picks.sort(key=lambda x: x["edge"], reverse=True)
        return jsonify(picks[:limit])

    except Exception as e:
        current_app.logger.exception("top_mlb failed")
        return jsonify({"error": f"top_mlb_failed: {type(e).__name__}: {e}"}), 500


# --- Top Picks (NFL): stub so the NFL tab doesn't 404 ---
@app.get("/api/top/nfl")
def top_nfl():
    # Return empty list (UI shows “No picks”). Replace with real NFL logic later.
    return jsonify([])
