"""
Verifikation Band-Cap (Regionen): zaehlt ueber den ECHTEN Engine-Pfad, wie viele
TORN-gegatete Region-Stunden der Band-Cap rettet (= productive statt gestrichen),
und mit welcher gedeckelten Hoehe. Nutzt debug['torn_floor_m'] wie der Gate-Code.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from chat_engine import GleitcastEngine
from source_area import _load_regions
from thermik_calculator import get_terrain_zone, min_band_depth

PROD_MIN = config.PRODUCTIVE_CLIMB_MIN
engine = GleitcastEngine()
engine.load_weather_from_cache()
orig_tq = engine._thermal_quality_tags

saved, killed = [], []
CUR = {"region": "?"}


def wrapped(wind_speed_10m, wind_gusts_10m, pl_data, elevation_m, thermal_top_m,
            climb_rate_ms, region_id=None, altitude_gusts=None):
    tags, debug = orig_tq(wind_speed_10m, wind_gusts_10m, pl_data, elevation_m,
                          thermal_top_m, climb_rate_ms, region_id, altitude_gusts)
    try:
        if (isinstance(climb_rate_ms, (int, float)) and climb_rate_ms >= PROD_MIN
                and "[THERMAL-TORN-UNUSABLE]" in tags):
            zone = get_terrain_zone(elevation_m, region_id)
            need = min_band_depth(climb_rate_ms, zone)
            floor = debug.get("torn_floor_m")
            rec = {"region": CUR["region"], "elev": elevation_m, "top": thermal_top_m,
                   "floor": floor, "climb": climb_rate_ms, "need": need}
            if isinstance(floor, (int, float)) and (floor - elevation_m) >= need:
                rec["usable_below"] = floor - elevation_m
                saved.append(rec)
            else:
                killed.append(rec)
    except Exception:
        pass
    return tags, debug


engine._thermal_quality_tags = wrapped
regions = [r for r in _load_regions() if r["id"] in engine.region_weather_data]
dates = sorted({ts.split("T")[0]
                for ts in engine.region_weather_data[regions[0]["id"]].get("hourly_data", {})})
for region in regions:
    CUR["region"] = region["region"]
    for d in dates:
        try:
            engine._build_single_region_context(region, d)
        except Exception:
            pass

tot = len(saved) + len(killed)
print("=" * 64)
print(f"BAND-CAP Verifikation (Regionen) — {tot} TORN-gegatete Produktiv-Stunden")
print("=" * 64)
print(f"GERETTET (Band darunter fliegbar): {len(saved)}")
print(f"weiter GESTRICHEN (Riss zu tief):  {len(killed)}")
print()
print("Gerettete Stunden (gedeckelt auf Riss-Hoehe):")
for r in sorted(saved, key=lambda x: -x["usable_below"]):
    print(f"  {r['region']:<24} Riss@{r['floor']:.0f}m | fliegbar {r['usable_below']:.0f}m "
          f"(braucht {r['need']:.0f}) | roh-Top war {r['top']:.0f}m | climb {r['climb']:.1f}")
