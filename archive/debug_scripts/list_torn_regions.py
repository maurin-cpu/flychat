"""
Wie list_torn_spots.py, aber fuer REGIONEN (_build_single_region_context).
Listet Regionen, bei denen TORN die Thermik zerreisst (anker-frei, Spalten-Tag
[THERMAL-TORN-UNUSABLE] = Produktiv-Gate), gruppiert nach Region und Tag.
"""
import sys, os
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from chat_engine import WingcastEngine
from source_area import _load_regions

MIN_CLIMB = config.THERMAL_QUALITY_MIN_CLIMB
PROD_MIN = config.PRODUCTIVE_CLIMB_MIN

engine = WingcastEngine()
engine.load_weather_from_cache()
orig_tq = engine._thermal_quality_tags

per = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # region -> {date: [torn_h, maxwind]}
CUR = {"region": "?", "date": "?"}


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
            rec = per[CUR["region"]][CUR["date"]]
            rec[0] += 1
            rec[1] = max(rec[1], _maxwind(pl_data, elevation_m, thermal_top_m))
    except Exception:
        pass
    return tags, debug


engine._thermal_quality_tags = wrapped

regions = [r for r in _load_regions() if r["id"] in engine.region_weather_data]
# Tage aus der ersten Region
first = regions[0]
dates = sorted({ts.split("T")[0]
                for ts in engine.region_weather_data.get(first["id"], {}).get("hourly_data", {})})
for region in regions:
    CUR["region"] = region["region"]
    for d in dates:
        CUR["date"] = d
        try:
            engine._build_single_region_context(region, d)
        except Exception:
            pass

totals = {name: sum(v[0] for v in days.values()) for name, days in per.items()}
order = sorted(per.keys(), key=lambda n: totals[n], reverse=True)
total_h = sum(totals.values())

print("=" * 64)
print(f"REGIONEN mit TORN-zerrissener Thermik (Cache {dates[0]}..{dates[-1]})")
print("=" * 64)
print(f"{len(regions)} Regionen geprueft | {len(order)} betroffen | "
      f"{total_h} produktiv-gegatete TORN-Stunden\n")
print(f"{'Region':<24} {'Std':>3}  Tage (h @ maxWind km/h)")
print("-" * 64)
for name in order:
    parts = [f"{d[-5:]}:{v[0]}h@{v[1]:.0f}" for d, v in sorted(per[name].items())]
    print(f"{name[:24]:<24} {totals[name]:>3}  {', '.join(parts)}")
if not order:
    print("(keine Region betroffen)")
