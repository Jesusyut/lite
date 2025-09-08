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
    return jsonify(search_player(q)[:10])

@app.get("/api/mlb/player/<int:pid>/trends")
def mlb_player_trends(pid):
    return jsonify(batter_trends_last10(pid))

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
      prop:   MLB 'HITS_0_5'|'TB_1_5'
              NFL 'REC'|'RUSH_YDS'|'REC_YDS'|'PASS_YDS'
      player_id (mlb) or player_name (nfl)
      american (optional)
    """
    try:
        j = request.get_json() or {}
        league   = j.get("league")
        prop     = j.get("prop")
        american = j.get("american", None)
        used_line = None

        # Auto-fill price (line, american) from FanDuel if empty
        if american in (None, ""):
            from utils.price_source import resolve_shop_price
            got = resolve_shop_price(
                league=league,
                prop=prop,
                player_name=j.get("player_name"),
                player_id=j.get("player_id"),
            )
            if got:
                used_line, american = got

        from utils.prob import american_to_prob
        p_break_even = american_to_prob(american) if american not in (None, "") else None

        if league == "mlb":
            from services.mlb import batter_trends_last10, resolve_player_id
            pid = j.get("player_id")
            if not pid:
                nm = j.get("player_name", "")
                pid = resolve_player_id(nm)
                if not pid:
                    return jsonify({"error":"MLB player could not be resolved"}), 400

            t = batter_trends_last10(int(pid))
            if prop == "HITS_0_5":
                p_trend = (t.get("hits_rate") or 0) / 100.0
            elif prop == "TB_1_5":
                p_trend = (t.get("tb2_rate")  or 0) / 100.0
            else:
                return jsonify({"error":"bad mlb prop"}), 400

        elif league == "nfl":
            from services.nfl import last5_trends
            name = j.get("player_name","")
            if not name:
                return jsonify({"error":"NFL needs player_name"}), 400
            t = last5_trends(name)
            if prop == "REC":
                p_trend = (t.get("rec_over35_rate")  or 0) / 100.0
            elif prop == "RUSH_YDS":
                p_trend = (t.get("rush_over49_rate") or 0) / 100.0
            elif prop in ("REC_YDS","PASS_YDS"):
                p_trend = 0.0  # expand when you wire yards trends
            else:
                return jsonify({"error":"bad nfl prop"}), 400
        else:
            return jsonify({"error":"bad league"}), 400

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
        # So you see the actual reason instead of a blank 500 page
        return jsonify({"error": f"evaluate failed: {type(e).__name__}: {e}"}), 500
        
# --- Top Picks (MLB) ---  (ONLY ONE definition — remove any duplicates!)
@app.get("/api/top/mlb")
def top_mlb():
    """
    Build MLB Top Picks from FanDuel batter props + last-10 trends.
    Safety rails:
      - ?limit= (default 12, max 24)
      - ?max_cands= (default 40)
      - ?budget_s= (default 8.0 total loop time)
    """
    import time
    from services.odds_fanduel import list_fd_mlb_candidates

    limit = min(max(int(request.args.get("limit", "12")), 1), 24)
    max_cands = min(max(int(request.args.get("max_cands", "40")), 5), 200)
    budget_s = float(request.args.get("budget_s", "8.0"))

    t0 = time.time()
    try:
        cands = list_fd_mlb_candidates()
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
            spark = t.get("hits_series") or []
        else:
            p_trend = (t.get("tb2_rate") or 0) / 100.0
            spark = t.get("tb2_series") or []

        p_be = american_to_prob(c["american"])
        if p_be is None:
            continue
        edge = p_trend - p_be

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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)


