from flask import Flask, request, jsonify, send_from_directory

# MLB (free API)
from services.mlb import todays_matchups, search_player as mlb_search_players, batter_trends_last10

# NFL CSV fallback (no API cost)
from services.nfl import last5_trends as csv_last5

# NFL API-Sports (optional; cached + budgeted)
try:
    from services.nfl_apisports import (
        search_player as nfl_api_search,
        player_last5_trends as nfl_api_last5,
    )
    HAVE_API = True
except Exception:
    HAVE_API = False

from utils.prob import american_to_prob
from utils.price_source import resolve_shop_price, resolve_shop_quote


app = Flask(__name__, static_url_path="", static_folder="static")

@app.get("/")
def root():
    return send_from_directory("static", "index.html")

# -------- MLB --------
@app.get("/api/mlb/today")
def mlb_today():
    return jsonify(todays_matchups())

@app.get("/api/mlb/search")
def mlb_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    return jsonify(mlb_search_players(q)[:10])

@app.get("/api/mlb/player/<int:pid>/trends")
def mlb_player_trends(pid):
    return jsonify(batter_trends_last10(pid))

# -------- NFL --------
@app.get("/api/nfl/player/search")
def nfl_search():
    """
    Searches NFL players via API-Sports if available.
    Falls back to empty list (CSV flow is name-based).
    """
    q = request.args.get("q", "").strip()
    if not q or not HAVE_API:
        return jsonify([])
    try:
        js = nfl_api_search(q)
        out = []
        for r in js.get("response", []):
            pid = r.get("id") or (r.get("player") or {}).get("id")
            name = r.get("name") or (r.get("player") or {}).get("name")
            if pid and name:
                out.append({"id": pid, "name": name})
        return jsonify(out[:10])
    except Exception:
        return jsonify([])

@app.get("/api/nfl/player/<int:pid>/trends")
def nfl_player_trends(pid):
    """
    If API-Sports present, return last-5 trends by player id/season.
    Else, allow ?name= to use CSV fallback.
    """
    season = int(request.args.get("season", "2024"))
    if HAVE_API:
        try:
            return jsonify(nfl_api_last5(pid, season))
        except Exception:
            pass  # fall through to CSV

    name = request.args.get("name", "").strip()
    return jsonify(csv_last5(name))

# -------- Evaluate (shared) --------
@app.post("/api/evaluate")
def evaluate():
    """
    body:
      league: 'mlb'|'nfl'
      prop:
        MLB -> 'HITS_0_5'|'TB_1_5'
        NFL -> 'REC'|'RUSH_YDS'|'REC_YDS'|'PASS_YDS'   (broader props)
      player_id (mlb or nfl when using API) OR player_name (nfl CSV fallback)
      american (optional, e.g., -120)  # if missing, we'll fetch FD price (±250 filter)
      season (optional, nfl; default 2024)
    """
    j = request.get_json() or {}
    league = j.get("league")
    prop   = j.get("prop")
    american = j.get("american")
    used_line = None

    # 1) Try to fetch FanDuel line+price if user left price blank (and sometimes for line discovery)
    quote = None
    if american in (None, ""):
        quote = resolve_shop_quote(league=league, prop=prop, player_name=j.get("player_name"))
        if quote:
            american = quote.get("american")
            used_line = quote.get("line")

    # 2) Break-even from price (if any)
    from utils.prob import american_to_prob
    p_break_even = american_to_prob(american) if american not in (None, "") else None

    # 3) Compute trend probability (MLB fixed, NFL broader/dynamic)
    if league == "mlb":
        from services.mlb import batter_trends_last10
        if not j.get("player_id"):
            return jsonify({"error": "player_id required for mlb"}), 400
        t = batter_trends_last10(int(j["player_id"]))
        if prop == "HITS_0_5":
            p_trend = (t.get("hits_rate") or 0) / 100.0
            used_line = used_line or 0.5
        elif prop == "TB_1_5":
            p_trend = (t.get("tb2_rate") or 0) / 100.0
            used_line = used_line or 1.5
        else:
            return jsonify({"error": "bad mlb prop"}), 400

    elif league == "nfl":
        season = int(j.get("season", 2024))
        # Map prop -> metric; default lines if no quote available
        metric_defaults = {
            "REC": 3.5,
            "RUSH_YDS": 49.5,
            "REC_YDS": 49.5,
            "PASS_YDS": 249.5,
        }
        metric = prop
        used_line = float(used_line if used_line is not None else metric_defaults.get(metric, 0.0))

        # Prefer API-Sports when we have player_id + API
        t = {}
        if 'player_id' in j and j['player_id'] and HAVE_API:
            try:
                from services.nfl_apisports import player_last5_dynamic
                t = player_last5_dynamic(int(j["player_id"]), season, metric, used_line)
            except Exception:
                t = {}
        if not t:
            # CSV fallback by player_name
            from services.nfl import last5_dynamic
            t = last5_dynamic(j.get("player_name","") or "", metric, used_line)

        p_trend = (t.get("rate") or 0) / 100.0
        if p_trend == 0 and t.get("n",0) == 0:
            return jsonify({"error":"No recent games for this player"}), 404

    else:
        return jsonify({"error": "bad league"}), 400

    # 4) Tag
    tag = "Fade"
    if p_trend >= 0.58:
        tag = "Straight"
    elif p_trend >= 0.52:
        tag = "Parlay leg"

    return jsonify({
        "p_trend": round(p_trend, 4),
        "break_even_prob": round(p_break_even, 4) if p_break_even is not None else None,
        "tag": tag,
        "used_line": used_line,
        "price_source": ("FanDuel" if quote else None)
    })
