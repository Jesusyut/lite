# app.py
from flask import Flask, request, jsonify, send_from_directory
from services.mlb import todays_matchups, search_player, batter_trends_last10, resolve_player_id
from services.nfl import last5_trends
try:
    from services.nfl_apisports import search_player as api_search, player_last5_trends as api_last5
    HAVE_API = True
except Exception:
    HAVE_API = False

from utils.prob import american_to_prob
from utils.price_source import resolve_shop_price, resolve_shop_quote



app = Flask(__name__, static_url_path='', static_folder='static')

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
    # allow optional name for API-Sports id resolution
    nm = request.args.get("name","").strip() or None
    try:
        d = batter_trends_last10(pid, player_name=nm)
        d = d or {}
        return jsonify({
            "n": d.get("n", 0),
            "hits_rate": float(d.get("hits_rate") or 0.0),
            "tb2_rate":  float(d.get("tb2_rate")  or 0.0),
            "hits_series": d.get("hits_series") or [],
            "tb2_series":  d.get("tb2_series")  or [],
        })
    except Exception:
        return jsonify({"n": 0, "hits_rate": 0.0, "tb2_rate": 0.0, "hits_series": [], "tb2_series": []})


# --- NFL ---
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
    # CSV fallback (name-based)
    name = request.args.get("name","")
    return jsonify(last5_trends(name))

# --- Evaluation (shared) ---

@app.post("/api/evaluate")
def evaluate():
    """
    body:
      league: 'mlb'|'nfl'
      prop:
        MLB: 'HITS_0_5' | 'TB_1_5'
        NFL: 'REC' | 'RUSH_YDS' | 'REC_YDS' | 'PASS_YDS'
      player_id (mlb) or player_name (nfl/mlb fallback)
      american (optional)
    """
    try:
        j = request.get_json() or {}
        league   = j.get("league")
        prop     = j.get("prop")
        american = j.get("american", None)
        used_line = None

        # --- Auto-fill odds from FanDuel when price is blank ---
        if american in (None, ""):
            from utils.price_source import resolve_shop_price
            quote = resolve_shop_price(
                league=league,
                prop=prop,
                player_name=j.get("player_name"),
                player_id=j.get("player_id"),
            )
            # resolve_shop_price may return a tuple (line, american) or just american
            if isinstance(quote, tuple):
                used_line, american = quote
            elif isinstance(quote, (int, float)):
                american = quote

        from utils.prob import american_to_prob
        p_break_even = american_to_prob(american) if american not in (None, "") else None

        # ---------------- MLB ----------------
        if league == "mlb":
            from services.mlb import batter_trends_last10, resolve_player_id

            name = (j.get("player_name") or "").strip()
            pid  = j.get("player_id")

            # If no id, try to resolve by name (API-SPORTS id)
            if not pid and name:
                try:
                    pid = resolve_player_id(name)
                except Exception:
                    pid = None

            # Need at least one of (id or name)
            if not pid and not name:
                return jsonify({"error": "MLB needs player_id or player_name"}), 400

            # Call trends with BOTH pid and name so service can self-resolve to API-SPORTS id
            try:
                t = batter_trends_last10(int(pid) if pid else 0, player_name=name)
            except Exception:
                t = {}

            if prop == "HITS_0_5":
                p_trend = float(t.get("hits_rate") or 0.0) / 100.0
                if used_line is None:
                    used_line = 0.5
            elif prop == "TB_1_5":
                p_trend = float(t.get("tb2_rate") or 0.0) / 100.0
                if used_line is None:
                    used_line = 1.5
            else:
                return jsonify({"error": "bad mlb prop"}), 400

        # ---------------- NFL ----------------
        elif league == "nfl":
            from services.nfl import last5_trends
            name = (j.get("player_name") or "").strip()
            if not name and not j.get("player_id"):
                return jsonify({"error": "NFL needs player_name"}), 400

            t = last5_trends(name)
            if prop == "REC":
                p_trend = float(t.get("rec_over35_rate") or 0.0) / 100.0
            elif prop == "RUSH_YDS":
                p_trend = float(t.get("rush_over49_rate") or 0.0) / 100.0
            elif prop in ("REC_YDS", "PASS_YDS"):
                # TODO: wire real yards trends later
                p_trend = 0.0
            else:
                return jsonify({"error": "bad nfl prop"}), 400

        else:
            return jsonify({"error": "bad league"}), 400

        # Tagging
        tag = "Fade"
        if p_trend >= 0.58:
            tag = "Straight"
        elif p_trend >= 0.52:
            tag = "Parlay leg"

        return jsonify({
            "p_trend": round(p_trend, 4),
            "break_even_prob": round(p_break_even, 4) if p_break_even is not None else None,
            "used_line": used_line,
            "tag": tag
        })
    except Exception as e:
        # Return JSON instead of HTML 500 so the UI can display the reason
        return jsonify({"error": f"evaluate failed: {type(e).__name__}: {e}"}), 500

        
# --- Top Picks (MLB) ---  (ONLY ONE definition — remove any duplicates!)
@app.get("/api/top/mlb")
def top_mlb():
    """
    Build MLB Top Picks from FanDuel batter props + last-10 trends.

    Query params:
      limit           : max results to return (default 12, max 24)
      max_cands       : cap candidate scan after odds (default 40)
      budget_s        : total compute time budget in seconds (default 8.0)
      min_edge        : require (p_trend - break_even_prob) >= min_edge (default 0.02 = 2%)
      min_trend       : require p_trend >= min_trend (default 0.55 = 55%)
      allow_negative  : if "1", include negative edges (default 0 = filter out)
      events          : how many MLB events to scan from odds (default 8)
      per_event_cap   : max props per event to consider before merge (default 30)
    """
    import time
    from services.odds_fanduel import list_fd_mlb_candidates
    from services.mlb import resolve_player_id, batter_trends_last10
    from utils.prob import american_to_prob

    # --- knobs (all local to this function) ---
    limit         = min(max(int(request.args.get("limit", "12")), 1), 24)
    max_cands     = min(max(int(request.args.get("max_cands", "40")), 5), 200)
    budget_s      = float(request.args.get("budget_s", "8.0"))
    min_edge      = float(request.args.get("min_edge", "0.02"))     # 2%
    min_trend     = float(request.args.get("min_trend", "0.55"))    # 55%
    allow_neg     = request.args.get("allow_negative", "0") == "1"
    events        = max(1, int(request.args.get("events", "8")))
    per_event_cap = max(5, int(request.args.get("per_event_cap", "30")))

    t0 = time.time()

    # --- odds → round-robin candidates across multiple events ---
    try:
        cands = list_fd_mlb_candidates(
            max_events=events, 
            per_event_cap=per_event_cap
        )
    except Exception as e:
        return jsonify({"error": f"odds fetch failed: {e}"}), 502

    cands = cands[:max_cands]

    picks = []
    for c in cands:
        if len(picks) >= limit or (time.time() - t0) > budget_s:
            break

        name = c["player_name"]
        pid = resolve_player_id(name)
        if not pid:
            continue

        try:
            t = batter_trends_last10(pid)
        except Exception:
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

        # only include positive-edge picks unless overridden
        if not allow_neg:
            if p_trend < min_trend:
                continue
            if edge < min_edge:
                continue

        tag = "Fade"
        if p_trend >= 0.58: tag = "Straight"
        elif p_trend >= 0.52: tag = "Parlay leg"

        picks.append({
            "player_id": pid,
            "player_name": name,
            "prop": c["prop"],
            "line": float(c["line"]),
            "american": float(c["american"]),
            "break_even_prob": round(p_be, 4),
            "p_trend": round(p_trend, 4),
            "edge": round(edge, 4),
            "tag": tag,
            "spark": spark
        })

    picks.sort(key=lambda x: x["edge"], reverse=True)
    return jsonify(picks[:limit])

