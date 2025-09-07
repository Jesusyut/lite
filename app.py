from flask import Flask, request, jsonify, send_from_directory

# MLB (free API)
from services.mlb import todays_matchups, search_player as mlb_search_players, batter_trends_last10

# NFL CSV fallback (no API cost)
from services.nfl import last5_trends as csv_last5

# NFL API-Sports (optional; cached upstream)
try:
    from services.nfl_apisports import (
        search_player as nfl_api_search,
        player_last5_trends as nfl_api_last5,
    )
    HAVE_API = True
except Exception:
    HAVE_API = False

from utils.prob import american_to_prob

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
      prop:   'HITS_0_5'|'TB_1_5'|'REC_3_5'|'RUSH_49_5'
      player_id (mlb or nfl when using API) OR player_name (nfl CSV fallback)
      american (optional, e.g., -120)
      season (optional, nfl; default 2024)
    """
    j = request.get_json() or {}
    league = j.get("league")
    prop = j.get("prop")
    american = j.get("american")
    p_break_even = american_to_prob(american) if american not in (None, "") else None

    if league == "mlb":
        t = batter_trends_last10(int(j.get("player_id")))
        if prop == "HITS_0_5":
            p_trend = (t["hits_rate"] or 0) / 100.0
        elif prop == "TB_1_5":
            p_trend = (t["tb2_rate"] or 0) / 100.0
        else:
            return jsonify({"error": "bad mlb prop"}), 400

    elif league == "nfl":
        season = int(j.get("season", 2024))
        p_trend = 0.0
        t = {}

        # Prefer API-Sports when we have player_id + API
        if HAVE_API and j.get("player_id"):
            try:
                t = nfl_api_last5(int(j["player_id"]), season)
            except Exception:
                t = {}

        # Fallback to CSV by name
        if not t:
            t = csv_last5(j.get("player_name", "") or "")

        if prop == "REC_3_5":
            p_trend = (t.get("rec_over35_rate") or 0) / 100.0
        elif prop == "RUSH_49_5":
            p_trend = (t.get("rush_over49_rate") or 0) / 100.0
        else:
            return jsonify({"error": "bad nfl prop"}), 400

    else:
        return jsonify({"error": "bad league"}), 400

    # Simple tagging
    tag = "Fade"
    if p_trend >= 0.58:
        tag = "Straight"
    elif p_trend >= 0.52:
        tag = "Parlay leg"

    return jsonify({
        "p_trend": round(p_trend, 4),
        "break_even_prob": round(p_break_even, 4) if p_break_even is not None else None,
        "tag": tag,
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)

