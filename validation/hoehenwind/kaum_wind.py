# -*- coding: utf-8 -*-
"""„Kaum Wind“ verbessern: andere Regel? andere Wahrheit?

Wahrheit A: die 6 Gipfel aus richtung_vs_staerke (ruhig = höchstens 1 misst >= 10 km/h)
Wahrheit B: 15 exponierte Gipfel >= 2100 m inkl. Tessin (Matro) und Westalpen
            (ruhig = höchstens 20 % messen >= 10 km/h)
Regeln (alle je Region, Median der Punkte):
  anteil<20 / anteil<30  Anteil Regionen mit Wind (>= 10 km/h)
  max<15 / max<20        stärkste Region unter 15 / 20 km/h
  mittel<10              mittlere Regionsstärke (skalar) unter 10 km/h
Schreibt kaum_wind.json.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))
import einigkeit_regionen as er  # noqa: E402
import kachel_schwellen as ks  # noqa: E402
import richtung_vs_staerke as rv  # noqa: E402

STATIONS_B = ["ATT", "CMA", "COV", "DIA", "EGH", "GOR", "GUE", "JUN", "MTR", "NAS",
              "PIL", "PMA", "SAE", "TIT", "WFJ"]


def region_speeds(samples, regions):
    by = {}
    for (s, d), reg in zip(samples, regions):
        by.setdefault(reg, []).append(er.uv(s, d))
    return [math.hypot(statistics.median(x[0] for x in xs), statistics.median(x[1] for x in xs))
            for xs in by.values() if len(xs) >= 2]


RULES = {
    "anteil<20": lambda sp: sum(s >= 10 for s in sp) / len(sp) < 0.2,
    "anteil<30": lambda sp: sum(s >= 10 for s in sp) / len(sp) < 0.3,
    "max<15": lambda sp: max(sp) < 15,
    "max<20": lambda sp: max(sp) < 20,
    "mittel<10": lambda sp: statistics.mean(sp) < 10,
}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pts, regs = ks.spots(), er.spot_regions()
    ks.spot_noon(pts)
    model = er.spot_samples_ordered(pts)
    obs = {a: rv.station_obs(a) for a in sorted(set(rv.STATIONS) | set(STATIONS_B))}
    rows = []
    for d, arr in sorted(model.items()):
        pairs = [(x, r) for x, r in zip(arr, regs) if x and x[0] is not None and x[1] is not None]
        if len(pairs) < 0.9 * len(pts):
            continue
        day = dt.date.fromisoformat(d)
        meas = {a: rv.obs_noon(obs[a], day) for a in obs}
        a_vals = [meas[a] for a in rv.STATIONS if meas[a]]
        b_vals = [meas[a] for a in STATIONS_B if meas[a]]
        if len(a_vals) < 5 or len(b_vals) < 12:
            continue
        sp = region_speeds([x for x, _ in pairs], [r for _, r in pairs])
        rows.append({"d": d, "sp": sp,
                     "A": sum(v[0] >= 10 for v in a_vals) <= 1,
                     "B": sum(v[0] >= 10 for v in b_vals) / len(b_vals) <= 0.2})
    res = {"tage": len(rows), "ruhig_A": sum(r["A"] for r in rows), "ruhig_B": sum(r["B"] for r in rows),
           "regeln": []}
    for name, rule in RULES.items():
        shown = [r for r in rows if rule(r["sp"])]
        row = {"regel": name, "gezeigt": len(shown)}
        for t in ("A", "B"):
            hit = sum(r[t] for r in shown)
            row[t] = {"richtig_pct": round(100 * hit / len(shown)) if shown else None,
                      "erkannt_pct": round(100 * hit / res[f"ruhig_{t}"]) if res[f"ruhig_{t}"] else None}
            for half, f in (("h1", lambda r: r["d"] < "2026-07-01"), ("h2", lambda r: r["d"] >= "2026-07-01")):
                s = [r for r in shown if f(r)]
                row[t][half] = f"{round(100 * sum(r[t] for r in s) / len(s)) if s else '-'}% (n={len(s)})"
        res["regeln"].append(row)
    (HERE / "kaum_wind.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Tage {res['tage']}, ruhig gemessen: 6 Gipfel {res['ruhig_A']}, 15 Gipfel {res['ruhig_B']}")
    for r in res["regeln"]:
        print(f"{r['regel']:10s} gezeigt {r['gezeigt']:3d} | 6 Gipfel: richtig {r['A']['richtig_pct']}% erkannt "
              f"{r['A']['erkannt_pct']}% [{r['A']['h1']} / {r['A']['h2']}] | 15 Gipfel: richtig "
              f"{r['B']['richtig_pct']}% erkannt {r['B']['erkannt_pct']}% [{r['B']['h1']} / {r['B']['h2']}]")


if __name__ == "__main__":
    main()
