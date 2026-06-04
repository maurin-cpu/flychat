"""A/B-Test: Region-Thermik-Aggregation Median (P50) vs P75 vs Beste-30%.

Frage: Welcher Aggregator ueber die Spots einer Region beschreibt die
Pilot-Realitaet am besten? Heute produktiv: P50 (Spot-Median, fetch_weather.py:830).

Datenquelle: data/weather_archive/*.json (pro Spot stuendlich max_height/climb_rate/lcl
in hourly_flight). KEINE Neuberechnung noetig — wir aggregieren die bereits
gerechneten Spot-Werte nur anders.

Zwei nicht-zirkulaere Pruefungen:
  TEIL A  Magnitude vs Tier-Erwartung (cloudbase_terrain_tiers.md):
          Landet die Tages-Peak-Basis im realistischen Band des Terrains?
          Median-Verdacht: zu tief (unter "Standard"). P75 besser? Beste-30% zu hoch?
  TEIL B  XC-Diskriminierung gegen echte best_km (xcontest_validation/observations.csv):
          Korreliert der Region-Wert an WIRKLICH geflogenen Top-Tagen besser?

Aggregatoren je Region/Stunde, dann Tages-Peak ueber Flugstunden.
"""
from __future__ import annotations
import csv
import glob
import json
import math
import os
import statistics as st
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVE = os.path.join(ROOT, "data", "weather_archive")
XC_CSV = os.path.join(ROOT, "xcontest_validation", "observations.csv")
FLIGHT_HOURS = [f"{h:02d}:00" for h in range(10, 18)]
MIN_SPOTS = 3  # = SPOT_MEDIAN_MIN_SPOTS (Produktiv-Schwelle)

# Cloudbase-MSL-Baender pro Terrain (aus meteo_research/cloudbase_terrain_tiers.md)
# (standard_lo, standard_hi, xc_hi, hammer_hi)  -> Klassen-Grenzen
TIER_BANDS = {
    "mittelland": (1500, 1800, 2200, 2500),
    "jura":       (1700, 2000, 2400, 2800),
    "voralpen":   (2000, 2400, 2800, 3200),
    "alpen":      (2500, 3000, 3500, 4200),
    "hochalpin":  (3000, 3500, 4000, 5000),
}


def agg_p50(vals):
    return st.median(vals)


def agg_p75(vals):
    if len(vals) == 1:
        return vals[0]
    # lineare Interpolation, wie numpy/statistics.quantiles(method='exclusive')
    return st.quantiles(vals, n=4)[2]


def agg_best30(vals):
    """Mittel der besten 30 % der Spots (mind. 1)."""
    k = max(1, math.ceil(0.30 * len(vals)))
    top = sorted(vals, reverse=True)[:k]
    return st.mean(top)


AGGS = {"P50_median": agg_p50, "P75": agg_p75, "best30%": agg_best30}
QTY = ("climb_rate", "max_height", "lcl")


def load_archives():
    """-> {date: {region: [hourly_flight_dict, ...], '_tt': {region: terrain_type}}}"""
    out = {}
    for fn in sorted(glob.glob(os.path.join(ARCHIVE, "*.json"))):
        date = os.path.basename(fn)[:10]
        d = json.load(open(fn, encoding="utf-8"))
        byreg = defaultdict(list)
        tt = {}
        for v in d.get("spots", {}).values():
            r = v.get("analyse_region")
            hf = v.get("hourly_flight")
            if r and isinstance(hf, dict):
                byreg[r].append(hf)
                if v.get("terrain_type"):
                    tt[r] = v["terrain_type"]
        out[date] = {"reg": byreg, "tt": tt}
    return out


def region_day_peaks(hfs):
    """Pro Aggregator: Tages-Peak (max ueber Flugstunden) je Groesse.
    -> {agg: {qty: peak_value}}"""
    res = {a: {q: None for q in QTY} for a in AGGS}
    for q in QTY:
        for a, fn in AGGS.items():
            peak = None
            for hh in FLIGHT_HOURS:
                vals = [hf[hh].get(q) for hf in hfs
                        if hh in hf and isinstance(hf[hh].get(q), (int, float))]
                vals = [x for x in vals if x is not None]
                if len(vals) < MIN_SPOTS:
                    continue
                v = fn(vals)
                if peak is None or v > peak:
                    peak = v
            res[a][q] = peak
    return res


def classify_band(tt, base):
    """Klassifiziert Basis-MSL gegen Tier-Band."""
    b = TIER_BANDS.get(tt)
    if not b or base is None:
        return "?"
    s_lo, s_hi, xc_hi, ham_hi = b
    if base < s_lo:
        return "UNTER-Standard"
    if base <= s_hi:
        return "Standard"
    if base <= xc_hi:
        return "XC"
    if base <= ham_hi:
        return "Hammer"
    return "UEBER-Hammer"


def load_xc():
    """-> {(date, region): best_km}"""
    out = {}
    if not os.path.exists(XC_CSV):
        return out
    with open(XC_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                km = float(row.get("best_km") or 0)
            except ValueError:
                continue
            key = (row["date"], row["region"])
            out[key] = max(out.get(key, 0), km)
    return out


def main():
    arch = load_archives()
    xc = load_xc()
    dates = sorted(arch.keys())
    print(f"Archiv-Tage: {len(dates)} ({dates[0]}..{dates[-1]})  XC-Beobachtungen: {len(xc)}\n")

    # Sammle pro (date, region) die Peaks aller Aggregatoren
    rows = []  # {date, region, tt, agg-peaks..., best_km}
    for date in dates:
        for region, hfs in arch[date]["reg"].items():
            if len(hfs) < MIN_SPOTS:
                continue
            peaks = region_day_peaks(hfs)
            rows.append({
                "date": date, "region": region,
                "tt": arch[date]["tt"].get(region, "?"),
                "n_spots": len(hfs),
                "peaks": peaks,
                "best_km": xc.get((date, region)),
            })

    # ===== TEIL A: Magnitude vs Tier-Erwartung (Basis) =====
    print("=" * 70)
    print("TEIL A — Tages-Peak-WOLKENBASIS vs Tier-Erwartung")
    print("=" * 70)
    # Verschiebung P75/best30 gegenueber Median
    lift = {a: defaultdict(list) for a in AGGS}
    band_counts = {a: defaultdict(int) for a in AGGS}
    for r in rows:
        med = r["peaks"]["P50_median"]["lcl"]
        for a in AGGS:
            v = r["peaks"][a]["lcl"]
            if v is None:
                continue
            band_counts[a][classify_band(r["tt"], v)] += 1
            if med:
                lift[a]["lcl"].append(v - med)
    print(f"\nMittlere Basis-Anhebung ggue Median (m):")
    for a in AGGS:
        vals = lift[a]["lcl"]
        if vals:
            print(f"  {a:<12} {st.mean(vals):+6.0f} m   (median {st.median(vals):+.0f})")
    print(f"\nVerteilung Tages-Peak-Basis auf Tier-Klassen (n region-days):")
    classes = ["UNTER-Standard", "Standard", "XC", "Hammer", "UEBER-Hammer", "?"]
    print(f"  {'Aggregator':<12}" + "".join(f"{c:<16}" for c in classes))
    for a in AGGS:
        print(f"  {a:<12}" + "".join(f"{band_counts[a].get(c,0):<16}" for c in classes))
    print("\n  Lesart: viele 'UNTER-Standard' = unterschaetzt. Viele 'UEBER-Hammer' = uebertrieben.")

    # ===== TEIL B: XC-Diskriminierung gegen best_km =====
    print("\n" + "=" * 70)
    print("TEIL B — Region-Wert an ECHTEN Top-XC-Tagen (best_km)")
    print("=" * 70)
    xc_rows = [r for r in rows if r["best_km"] is not None and r["best_km"] > 0]
    print(f"\nRegion-Tage mit echtem XC-Flug (best_km>0): {len(xc_rows)}")
    if xc_rows:
        kms = sorted((r["best_km"] for r in xc_rows), reverse=True)
        thr = kms[max(0, len(kms) // 3 - 1)] if len(kms) >= 3 else kms[0]
        top = [r for r in xc_rows if r["best_km"] >= thr]
        rest = [r for r in xc_rows if r["best_km"] < thr]
        print(f"Top-Drittel-Schwelle: best_km >= {thr:.1f}  (Top n={len(top)}, Rest n={len(rest)})\n")
        print(f"  {'Groesse/Aggregator':<26}{'Top-XC-Tage':<16}{'Rest':<12}{'Spreizung':<10}")
        for q in QTY:
            unit = "m/s" if q == "climb_rate" else "m"
            for a in AGGS:
                tv = [r["peaks"][a][q] for r in top if r["peaks"][a][q] is not None]
                rv = [r["peaks"][a][q] for r in rest if r["peaks"][a][q] is not None]
                if not tv or not rv:
                    continue
                tm, rm = st.mean(tv), st.mean(rv)
                spread = tm - rm
                print(f"  {q+' '+a:<26}{tm:>8.1f}{unit:<7}{rm:>8.1f}{unit:<4}{spread:>+8.1f}")
            print()
        print("  Lesart: groessere 'Spreizung' (Top minus Rest) = der Aggregator")
        print("  trennt gute von schwachen XC-Tagen schaerfer = besserer Region-Indikator.")

    # Detail-Dump fuer Spot-Check (Wallis-aehnlich)
    print("\n" + "=" * 70)
    print("STICHPROBE — hochalpine Region-Tage (Basis-Peak je Aggregator)")
    print("=" * 70)
    ha = [r for r in rows if r["tt"] == "hochalpin"][:12]
    print(f"  {'Datum':<12}{'Region':<22}{'P50':<8}{'P75':<8}{'best30':<8}{'Tier(P75)':<14}")
    for r in ha:
        p = r["peaks"]
        l50 = p["P50_median"]["lcl"]; l75 = p["P75"]["lcl"]; lb3 = p["best30%"]["lcl"]
        if l50 is None:
            continue
        print(f"  {r['date']:<12}{r['region'][:20]:<22}{l50:<8.0f}{l75:<8.0f}{lb3:<8.0f}"
              f"{classify_band(r['tt'], l75):<14}")


if __name__ == "__main__":
    main()
