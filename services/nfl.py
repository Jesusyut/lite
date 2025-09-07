import csv, pathlib

CSV = pathlib.Path("data/nfl_weekly.csv")  # columns: date,player,team,opponent,rec,recYds,rush,rushYds,targets

def last5_trends(player: str):
    name = (player or "").strip().lower()
    if not name or not CSV.exists():
        return {"n": 0}
    rows = []
    with open(CSV, newline="") as fh:
        for r in csv.DictReader(fh):
            if (r.get("player","").strip().lower()) == name:
                rows.append(r)
    rows = sorted(rows, key=lambda r: r.get("date",""), reverse=True)[:5]
    if not rows:
        return {"n": 0}

    def as_int(x):
        try: return int(x)
        except: return 0
    rec_hit   = sum(1 for r in rows if as_int(r.get("rec",0))      >= 4)   # Over 3.5 receptions
    rush_hit  = sum(1 for r in rows if as_int(r.get("rushYds",0))  >= 50)  # Over 49.5 rush yards
    return {
        "n": len(rows),
        "rec_over35_rate": round(100.0*rec_hit/len(rows), 1),
        "rush_over49_rate": round(100.0*rush_hit/len(rows), 1),
    }

