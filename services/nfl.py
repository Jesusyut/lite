import csv, pathlib
from typing import Dict, Any, Optional

CSV = pathlib.Path("data/nfl_weekly.csv")
# Expected columns (add as you can): date,player,team,opponent,rec,recYds,rush,rushYds,targets,passYds

def _as_int(x): 
    try: return int(float(x))
    except: return 0

def _last5_rows(name: str):
    name = (name or "").strip().lower()
    if not name or not CSV.exists(): return []
    rows = []
    with open(CSV, newline="") as fh:
        for r in csv.DictReader(fh):
            if (r.get("player","").strip().lower()) == name:
                rows.append(r)
    rows.sort(key=lambda r: r.get("date",""), reverse=True)
    return rows[:5]

def last5_trends(player: str):
    """Legacy fixed REC_3_5 / RUSH_49_5 support."""
    rows = _last5_rows(player)
    if not rows: return {"n": 0}
    rec_hit  = sum(1 for r in rows if _as_int(r.get("rec",0))     >= 4)
    rush_hit = sum(1 for r in rows if _as_int(r.get("rushYds",0)) >= 50)
    return {
        "n": len(rows),
        "rec_over35_rate": round(100.0*rec_hit/len(rows), 1),
        "rush_over49_rate": round(100.0*rush_hit/len(rows), 1),
    }

def last5_dynamic(player: str, metric: str, line: float) -> Dict[str, Any]:
    """
    Broader, dynamic thresholds using CSV (best-effort if fields exist):
      metric in {"REC","RUSH_YDS","REC_YDS","PASS_YDS"}
    """
    rows = _last5_rows(player)
    if not rows: return {"n": 0}

    hits = 0
    for r in rows:
        if metric == "REC":
            val = _as_int(r.get("rec",0))
        elif metric == "RUSH_YDS":
            val = _as_int(r.get("rushYds",0))
        elif metric == "REC_YDS":
            val = _as_int(r.get("recYds",0))
        elif metric == "PASS_YDS":
            val = _as_int(r.get("passYds",0))  # requires that column in CSV
        else:
            val = 0
        if val >= float(line):
            hits += 1

    n = len(rows)
    return {"n": n, "rate": round(100.0*hits/n, 1), "metric": metric, "line": float(line)}

