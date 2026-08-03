"""Echte XContest-Topouts vs. Region-Thermik P50/P75/best30.

Frage: Unterschaetzt der produktive P50 (Spot-Median) die real erreichte
Hoehe? Trifft P75 die Pilot-Realitaet besser?

Daten:
  - Topouts: validation/xcontest/_raw/topout_altitudes_2026-05-28_30.tsv (User-abgelesen)
  - Vorhersage: data/weather_archive/<date>.json, Spot.hourly_flight (max_height/lcl)
    -> Region-Tages-Peak (max ueber 10-17 Uhr) je Aggregator, wie ab_region_percentile.py.

Topout = max. erreichte Hoehe MSL = UNTERGRENZE der Wolkenbasis auf Route.
  -> unser 'lcl' (Basis) sollte >= Topout liegen.
  -> unser 'max_height' (Thermik-Decke) ist der naechste Vergleichswert.

CAVEAT: Topout wird irgendwo auf der Route erreicht, nicht zwingend ueber der
Launch-Region. Bei langen Fluegen (>120 km) ist die Launch-Region nur ein Anker.
"""
from __future__ import annotations
import csv
import json
import math
import os
import statistics as st
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVE = os.path.join(ROOT, "data", "weather_archive")
TOPOUT_TSV = os.path.join(ROOT, "validation/xcontest", "_raw",
                          "topout_altitudes_2026-05-28_30.tsv")
FLIGHT_HOURS = [f"{h:02d}:00" for h in range(10, 18)]
MIN_SPOTS = 3


def agg_p50(vals):
    return st.median(vals)


def agg_p75(vals):
    if len(vals) == 1:
        return vals[0]
    return st.quantiles(vals, n=4)[2]


def agg_best30(vals):
    k = max(1, math.ceil(0.30 * len(vals)))
    return st.mean(sorted(vals, reverse=True)[:k])


AGGS = {"P50": agg_p50, "P75": agg_p75, "best30": agg_best30}


def load_region_hfs(date):
    """-> {region: [hourly_flight, ...]}, {region: terrain_type}, {launch_name: region}"""
    fn = os.path.join(ARCHIVE, f"{date}.json")
    d = json.load(open(fn, encoding="utf-8"))
    byreg = defaultdict(list)
    tt = {}
    name2reg = {}
    for name, v in d.get("spots", {}).items():
        r = v.get("analyse_region")
        hf = v.get("hourly_flight")
        if r:
            name2reg[name] = r
            if isinstance(hf, dict):
                byreg[r].append(hf)
                if v.get("terrain_type"):
                    tt[r] = v["terrain_type"]
    return byreg, tt, name2reg


def region_day_peak(hfs, qty):
    """Pro Aggregator Tages-Peak (max ueber Flugstunden) der Groesse qty."""
    res = {}
    for a, fn in AGGS.items():
        peak = None
        for hh in FLIGHT_HOURS:
            vals = [hf[hh].get(qty) for hf in hfs
                    if hh in hf and isinstance(hf[hh].get(qty), (int, float))]
            if len(vals) < MIN_SPOTS:
                continue
            v = fn(vals)
            if peak is None or v > peak:
                peak = v
        res[a] = peak
    return res


def find_region(launch, name2reg):
    """Fuzzy: signifikante Launch-Token in Spot-Namen (Bindestrich = Trenner)."""
    toks = [t for t in launch.lower().replace("-", " ").split() if len(t) >= 3]
    for name, reg in name2reg.items():
        nl = name.lower().replace("-", " ")
        if toks and all(t in nl for t in toks[:2]):  # erste 1-2 Token muessen passen
            return reg
    for name, reg in name2reg.items():       # Fallback: erstes Token
        if toks and toks[0] in name.lower().replace("-", " "):
            return reg
    return None


def main():
    flights = []
    with open(TOPOUT_TSV, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            p = line.rstrip("\n").split("\t")
            flights.append({
                "pilot": p[0], "date": p[2][:10], "launch": p[3],
                "km": float(p[4]), "topout": int(p[7]),
            })

    cache = {}
    rows = []
    for fl in flights:
        date = fl["date"]
        if date not in cache:
            cache[date] = load_region_hfs(date)
        byreg, tt, name2reg = cache[date]
        reg = find_region(fl["launch"], name2reg)
        if reg is None or reg not in byreg or len(byreg[reg]) < MIN_SPOTS:
            rows.append({**fl, "region": reg, "tt": "?", "n": 0,
                         "mh": {}, "lcl": {}})
            continue
        hfs = byreg[reg]
        rows.append({
            **fl, "region": reg, "tt": tt.get(reg, "?"), "n": len(hfs),
            "mh": region_day_peak(hfs, "max_height"),
            "lcl": region_day_peak(hfs, "lcl"),
        })

    # ---- Tabelle ----
    print("=" * 116)
    print("TOPOUT vs REGION-VORHERSAGE  (max_height = Thermik-Decke, lcl = Basis; Tages-Peak je Aggregator)")
    print("=" * 116)
    hdr = (f"{'Pilot':<16}{'Dat':<6}{'Region':<22}{'km':>5}{'Topout':>7} | "
           f"{'mhP50':>6}{'mhP75':>6}{'mhB30':>6} | {'lclP50':>7}{'lclP75':>7}{'lclB30':>7}")
    print(hdr)
    print("-" * 116)
    for r in rows:
        mh, lcl = r["mh"], r["lcl"]
        def fmt(d, k):
            return f"{d.get(k):.0f}" if d.get(k) is not None else "--"
        print(f"{r['pilot'][:15]:<16}{r['date'][5:]:<6}{(r['region'] or '?')[:21]:<22}"
              f"{r['km']:>5.0f}{r['topout']:>7} | "
              f"{fmt(mh,'P50'):>6}{fmt(mh,'P75'):>6}{fmt(mh,'best30'):>6} | "
              f"{fmt(lcl,'P50'):>7}{fmt(lcl,'P75'):>7}{fmt(lcl,'best30'):>7}")

    # ---- Aggregat-Auswertung (nur Fluege mit Vorhersage) ----
    valid = [r for r in rows if r["mh"].get("P50") is not None]
    print("\n" + "=" * 70)
    print(f"AGGREGAT ueber {len(valid)} Fluege mit Region-Vorhersage")
    print("=" * 70)

    # max_height: Bias = Vorhersage - Topout. Negativ = Vorhersage zu tief.
    print("\nmax_height (Thermik-Decke) vs Topout:")
    print(f"  {'Aggregator':<10}{'mean Bias':>11}{'median Bias':>13}{'mean |Bias|':>13}"
          f"{'Topout>Vorh':>13}")
    for a in AGGS:
        bias = [r["mh"][a] - r["topout"] for r in valid if r["mh"].get(a) is not None]
        under = sum(1 for r in valid if r["mh"].get(a) is not None and r["topout"] > r["mh"][a])
        print(f"  {a:<10}{st.mean(bias):>+11.0f}{st.median(bias):>+13.0f}"
              f"{st.mean([abs(b) for b in bias]):>13.0f}{under:>10}/{len(bias)}")

    # lcl: sollte >= Topout (Basis ueber erreichter Hoehe). Verletzung = Basis < Topout.
    print("\nlcl (Wolkenbasis) vs Topout  [Basis SOLLTE >= Topout liegen]:")
    print(f"  {'Aggregator':<10}{'mean Bias':>11}{'median Bias':>13}{'Basis<Topout':>14}")
    for a in AGGS:
        bias = [r["lcl"][a] - r["topout"] for r in valid if r["lcl"].get(a) is not None]
        viol = sum(1 for r in valid if r["lcl"].get(a) is not None and r["lcl"][a] < r["topout"])
        print(f"  {a:<10}{st.mean(bias):>+11.0f}{st.median(bias):>+13.0f}{viol:>11}/{len(bias)}")

    print("\nLesart:")
    print("  max_height: 'Topout>Vorh' haeufig + negativer Bias = Decke zu tief -> P75 hebt an.")
    print("  lcl: 'Basis<Topout' = physikalisch unmoeglich (Pilot ueber Basis) = Vorhersage zu tief.")
    print("  Bester Aggregator: |Bias| klein UND wenige lcl-Verletzungen.")


if __name__ == "__main__":
    main()
