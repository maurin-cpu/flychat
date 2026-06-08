"""
Liste ALLE aktuellen Spots, bei denen TORN die Thermik zerreisst (anker-frei,
Spalten-Tag [THERMAL-TORN-UNUSABLE] = das Produktiv-Gate-Signal), gruppiert nach
Spot und Tag, mit max Hoehenwind als Kontext.
"""
import sys, os
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from chat_engine import WingcastEngine

MIN_CLIMB = config.THERMAL_QUALITY_MIN_CLIMB
PROD_MIN = config.PRODUCTIVE_CLIMB_MIN

engine = WingcastEngine()
engine.load_weather_from_cache()
orig_tq = engine._thermal_quality_tags

# spot -> {date: [torn_h, maxwind]}
per = defaultdict(lambda: defaultdict(lambda: [0, 0]))
CUR = {"spot": "?", "date": "?"}


def _maxwind(pl_data, elev, ttop):
    mx = 0
    for lv in config.PRESSURE_LEVELS:
        h = pl_data.get(f"geopotential_height_{lv}hPa")
        w = pl_data.get(f"wind_speed_{lv}hPa")
        if h is None or w is None:
            continue
        if elev < h <= ttop and isinstance(w, (int, float)):
            mx = max(mx, w)
    return mx


def wrapped(wind_speed_10m, wind_gusts_10m, pl_data, elevation_m, thermal_top_m,
            climb_rate_ms, region_id=None, altitude_gusts=None):
    tags, debug = orig_tq(wind_speed_10m, wind_gusts_10m, pl_data, elevation_m,
                          thermal_top_m, climb_rate_ms, region_id, altitude_gusts)
    try:
        if (isinstance(climb_rate_ms, (int, float)) and climb_rate_ms >= PROD_MIN
                and "[THERMAL-TORN-UNUSABLE]" in tags):
            rec = per[CUR["spot"]][CUR["date"]]
            rec[0] += 1
            rec[1] = max(rec[1], _maxwind(pl_data, elevation_m, thermal_top_m))
    except Exception:
        pass
    return tags, debug


engine._thermal_quality_tags = wrapped

wd = engine.weather_data or {}
spots = [s for s in engine.spots if s.get("name") in wd]
dates = sorted({ts.split("T")[0] for s in spots[:1]
                for ts in wd.get(s["name"], {}).get("hourly_data", {})})
for spot in spots:
    CUR["spot"] = spot["name"]
    for d in dates:
        CUR["date"] = d
        try:
            engine._build_single_spot_context(spot, d)
        except Exception:
            pass

# Ausgabe: Spots nach Gesamt-TORN-Stunden sortiert
totals = {name: sum(v[0] for v in days.values()) for name, days in per.items()}
order = sorted(per.keys(), key=lambda n: totals[n], reverse=True)
total_h = sum(totals.values())

print("=" * 64)
print(f"Spots mit TORN-zerrissener Thermik (aktueller Cache, {dates[0]}..{dates[-1]})")
print("=" * 64)
print(f"{len(order)} Spots, {total_h} produktiv-gegatete TORN-Stunden gesamt\n")
print(f"{'Spot':<36} {'Std':>3}  Tage (h @ maxWind km/h)")
print("-" * 64)
for name in order:
    days = per[name]
    parts = [f"{d[-5:]}:{v[0]}h@{v[1]:.0f}" for d, v in sorted(days.items())]
    print(f"{name[:36]:<36} {totals[name]:>3}  {', '.join(parts)}")
