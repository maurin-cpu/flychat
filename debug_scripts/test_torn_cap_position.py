"""
GO/NO-GO Test (a) + Wind-Filter fuer TQ_RATING_PLAN Band-Cap-Modell.

Frage: Taucht nach Abzug des 10m-Bodenankers echtes TORN-UNUSABLE auf —
besonders an STARK-WIND-Stunden (max Hoehenwind in der Schicht >= 30 / 40 km/h)?
Und wo in der Saeule (rel-Hoehe) liegt der tiefste echte Riss?

Geht ueber den ECHTEN Pfad (_build_single_spot_context rechnet climb/max_height)
mit Capture-Hook an _thermal_quality_tags. Repliziert Segment-TORN aus
weather_context.py L1144-1155 mit den echten Engine-Methoden.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from chat_engine import GleitcastEngine

CLIMB_FLOOR = 0.3
BS_DANGER = config.BS_RATIO_THRESHOLDS["danger"]
MIN_CLIMB = config.THERMAL_QUALITY_MIN_CLIMB

records = []          # je Thermik-Stunde ein dict
CURRENT = {"spot": "?"}

engine = GleitcastEngine()
engine.load_weather_from_cache()
orig_tq = engine._thermal_quality_tags


def _max_layer_pl_wind(pl_data, elevation, thermal_top):
    mx = None
    for lv in config.PRESSURE_LEVELS:
        h = pl_data.get(f"geopotential_height_{lv}hPa")
        w = pl_data.get(f"wind_speed_{lv}hPa")
        if h is None or w is None:
            continue
        if elevation < h <= thermal_top:
            mx = w if mx is None else max(mx, w)
    return mx


def _seg_torn(s, elevation, thermal_top, climb):
    seg_mid = (s["alt_lo"] + s["alt_hi"]) / 2
    lc = max(engine._parabolic_climb(seg_mid, elevation, thermal_top, climb), CLIMB_FLOOR)
    return s["du_dz"] > 0 and (lc / s["du_dz"]) * 100.0 <= BS_DANGER


def _capture(wind10, pl_data, elevation, thermal_top, climb):
    if not isinstance(climb, (int, float)) or climb < MIN_CLIMB:
        return
    if not isinstance(thermal_top, (int, float)) or thermal_top <= elevation:
        return
    segments, _ = engine._calculate_segment_shear(wind10, pl_data, elevation, thermal_top)
    if len(segments) < 1:
        return

    torn = [s for s in segments if _seg_torn(s, elevation, thermal_top, climb)]
    torn_pl = [s for s in torn if abs(s["alt_lo"] - elevation) >= 1.0]  # ohne 10m-Anker
    rel_pl = None
    if torn_pl:
        lo = min(torn_pl, key=lambda s: s["alt_lo"])
        rel_pl = max(0.0, min(1.0, (lo["alt_lo"] - elevation) / (thermal_top - elevation)))

    records.append({
        "spot": CURRENT["spot"],
        "maxpl": _max_layer_pl_wind(pl_data, elevation, thermal_top),
        "blmean": engine._calculate_bl_mean_wind(wind10, pl_data, elevation, thermal_top),
        "torn_anchor": bool(torn),
        "torn_pl": bool(torn_pl),
        "rel_pl": rel_pl,
    })


def wrapped_tq(wind_speed_10m, wind_gusts_10m, pl_data, elevation_m,
               thermal_top_m, climb_rate_ms, region_id=None, altitude_gusts=None):
    res = orig_tq(wind_speed_10m, wind_gusts_10m, pl_data, elevation_m,
                  thermal_top_m, climb_rate_ms, region_id, altitude_gusts)
    try:
        _capture(wind_speed_10m, pl_data, elevation_m, thermal_top_m, climb_rate_ms)
    except Exception:
        pass
    return res


engine._thermal_quality_tags = wrapped_tq

wd = engine.weather_data or {}
spots_with_data = [s for s in engine.spots if s.get("name") in wd]
dates = sorted({ts.split("T")[0]
                for s in spots_with_data[:1]
                for ts in wd.get(s["name"], {}).get("hourly_data", {})})
print(f"Spots: {len(spots_with_data)} | Tage: {dates}")
print("Baue Kontexte ...")
for spot in spots_with_data:
    CURRENT["spot"] = spot["name"]
    for d in dates:
        try:
            engine._build_single_spot_context(spot, d)
        except Exception:
            pass


def pct(a, b):
    return f"{100*a/b:.0f}%" if b else "-"


def torn_summary(rows, label):
    nt = sum(1 for r in rows if r["torn_pl"])
    print(f"  {label}: {len(rows)} Std, davon echtes TORN (PL-only): {nt} ({pct(nt, len(rows))})")
    rels = [r["rel_pl"] for r in rows if r["torn_pl"] and r["rel_pl"] is not None]
    if rels:
        b = sum(1 for r in rels if r < 0.33); m = sum(1 for r in rels if 0.33 <= r < 0.67)
        t = sum(1 for r in rels if r >= 0.67)
        print(f"      Position: unten {b} | mitte {m} | oben {t} | median rel "
              f"{sorted(rels)[len(rels)//2]:.2f}")


th = len(records)
withpl = [r for r in records if isinstance(r["maxpl"], (int, float))]
w30 = [r for r in withpl if r["maxpl"] >= 30]
w40 = [r for r in withpl if r["maxpl"] >= 40]
anchor_torn = sum(1 for r in records if r["torn_anchor"])
pl_torn = sum(1 for r in records if r["torn_pl"])

print()
print("=" * 70)
print("TEST: TORN nach Anker-Abzug, gefiltert auf Stark-Wind-Stunden")
print("=" * 70)
print(f"Thermik-Stunden gesamt: {th}")
print(f"  mit TORN inkl. 10m-Anker (Artefakt):   {anchor_torn} ({pct(anchor_torn, th)})")
print(f"  mit echtem TORN ohne Anker (PL-only):  {pl_torn} ({pct(pl_torn, th)})")
print()
if withpl:
    mxs = sorted((r["maxpl"] for r in withpl), reverse=True)
    print(f"Max Hoehenwind in der Schicht — Verteilung ueber {len(withpl)} Std:")
    print(f"  hoechster: {mxs[0]:.0f} km/h | median: {mxs[len(mxs)//2]:.0f} | "
          f">=30: {len(w30)} ({pct(len(w30), len(withpl))}) | "
          f">=40: {len(w40)} ({pct(len(w40), len(withpl))})")
print()
print("TORN-Auftreten nach Wind-Filter:")
torn_summary(withpl, "alle Stunden    ")
torn_summary(w30, "Wind >= 30 km/h ")
torn_summary(w40, "Wind >= 40 km/h ")
print()

# Windigste Stunden konkret zeigen
top = sorted(withpl, key=lambda r: r["maxpl"], reverse=True)[:12]
if top:
    print("Windigste Stunden (Spot | maxHoehenwind | BL-Mittel | TORN-PL?):")
    for r in top:
        bl = f"{r['blmean']:.0f}" if isinstance(r["blmean"], (int, float)) else "-"
        flag = "JA  rel=%.2f" % r["rel_pl"] if r["torn_pl"] else "nein"
        print(f"  {r['spot'][:34]:<34} {r['maxpl']:>4.0f} km/h | BL {bl:>3} | TORN {flag}")
print()
print("=" * 70)
print("VERDIKT:")
if pl_torn == 0:
    print("  NO-GO in dieser Lage: kein echtes TORN, auch nicht an den windigsten Stunden.")
    if w40:
        print(f"  Selbst bei >=40 km/h Hoehenwind ({len(w40)} Std): 0 echtes TORN.")
    elif not w30:
        print("  Cache enthaelt kaum/keine Stark-Wind-Stunden -> echte Foehn-Lage noetig.")
else:
    below = sum(1 for r in records if r["torn_pl"] and r["rel_pl"] is not None and r["rel_pl"] < 0.67)
    print(f"  Echtes TORN vorhanden: {pl_torn} Std, davon {below} unterhalb oberes Drittel.")
