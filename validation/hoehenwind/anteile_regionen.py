# -*- coding: utf-8 -*-
"""„Kaum Wind“ und „teils schwach“: Anteil je Punkt oder je Region?

Gleiche Daten wie kachel_schwellen.py / einigkeit_regionen.py. Region hat Wind, wenn
der Median ihrer Punkte (u/v-Komponenten) >= 10 km/h. Wahrheit an den 6 Gipfeln:
  ruhig          = höchstens 1 von 6 misst >= 10 km/h
  teils schwach  = mindestens 3 von 6 messen < 10 km/h (strenge Fassung, User-Entscheid)
Schreibt anteile_regionen.json.
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


def region_share_wind(samples, regions):
    by = {}
    for (s, d), reg in zip(samples, regions):
        by.setdefault(reg, []).append(er.uv(s, d))
    n = windy = 0
    for xs in by.values():
        if len(xs) < 2:
            continue
        n += 1
        if math.hypot(statistics.median(x[0] for x in xs), statistics.median(x[1] for x in xs)) >= ks.WIND_KMH:
            windy += 1
    return windy / n if n else None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pts, regs = ks.spots(), er.spot_regions()
    ks.spot_noon(pts)
    model = er.spot_samples_ordered(pts)
    obs = {a: rv.station_obs(a) for a in rv.STATIONS}
    rows = []
    for d, arr in sorted(model.items()):
        pairs = [(x, r) for x, r in zip(arr, regs) if x and x[0] is not None and x[1] is not None]
        if len(pairs) < 0.9 * len(pts):
            continue
        vals = [v for v in (rv.obs_noon(obs[a], dt.date.fromisoformat(d)) for a in rv.STATIONS) if v]
        if len(vals) < 5:
            continue
        weak = sum(v[0] < ks.WIND_KMH for v in vals)
        samples = [x for x, _ in pairs]
        rows.append({"d": d, "punkt": ks.features(samples)["share_wind"],
                     "region": region_share_wind(samples, [r for _, r in pairs]),
                     "ruhig": len(vals) - weak <= 1, "teils": weak >= 3})

    def halves(sel_rows, pred, truth_key):
        out = {}
        for half, f in (("alle", lambda r: True), ("jan_jun", lambda r: r["d"] < "2026-07-01"),
                        ("jul_nov", lambda r: r["d"] >= "2026-07-01")):
            xs = [r for r in sel_rows if f(r)]
            shown = [r for r in xs if pred(r)]
            truth_n = sum(r[truth_key] for r in xs)
            hit = sum(r[truth_key] for r in shown)
            out[half] = {"gezeigt": len(shown), "richtig_pct": round(100 * hit / len(shown)) if shown else None,
                         "erkannt_pct": round(100 * hit / truth_n) if truth_n else None}
        return out

    res = {"tage": len(rows), "kaum_wind": [], "teils_schwach": []}
    for kind in ("punkt", "region"):
        for X in (0.1, 0.2, 0.3, 0.4, 0.5):
            res["kaum_wind"].append({"art": kind, "X": X, **halves(rows, lambda r, X=X, k=kind: r[k] < X, "ruhig")})
        base = [r for r in rows if r[kind] >= 0.2]          # Tage, an denen ein Pfeil in Frage kommt
        for Z in (0.1, 0.2, 0.3, 0.4, 0.5):
            res["teils_schwach"].append({"art": kind, "Z": Z,
                                         **halves(base, lambda r, Z=Z, k=kind: 1 - r[k] >= Z, "teils")})
    (HERE / "anteile_regionen.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Tage {res['tage']}, gemessen ruhig {sum(r['ruhig'] for r in rows)}, teils schwach {sum(r['teils'] for r in rows)}")
    for key, thr in (("kaum_wind", "X"), ("teils_schwach", "Z")):
        print(f"\n{key}: art {thr} | alle gezeigt/richtig/erkannt | jan-jun richtig | jul-nov richtig")
        for r in res[key]:
            a, h1, h2 = r["alle"], r["jan_jun"], r["jul_nov"]
            print(f"  {r['art']:6s} {r[thr]:.1f} | {a['gezeigt']:3d} {a['richtig_pct']}% {a['erkannt_pct']}% | "
                  f"{h1['gezeigt']} {h1['richtig_pct']}% | {h2['gezeigt']} {h2['richtig_pct']}%")


if __name__ == "__main__":
    main()
