"""
Echtheits-Split (shear-getrieben vs. climb-getrieben) fuer die REGION-TORN-Faelle.
Analog test_torn_shear_vs_climb.py, aber ueber _build_single_region_context.
Frage: Ist das Region-TORN (oft Flachland, Schwachwind) echt oder Artefakt?
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from chat_engine import WingcastEngine
from source_area import _load_regions
from thermik_calculator import get_terrain_zone

CLIMB_FLOOR = 0.3
BS_DANGER = config.BS_RATIO_THRESHOLDS["danger"]
MIN_CLIMB = config.THERMAL_QUALITY_MIN_CLIMB

engine = WingcastEngine()
engine.load_weather_from_cache()
orig_tq = engine._thermal_quality_tags
records = []


def _seg_torn(s, elevation, thermal_top, climb):
    seg_mid = (s["alt_lo"] + s["alt_hi"]) / 2
    lc = max(engine._parabolic_climb(seg_mid, elevation, thermal_top, climb), CLIMB_FLOOR)
    return s["du_dz"] > 0 and (lc / s["du_dz"]) * 100.0 <= BS_DANGER


def wrapped(wind_speed_10m, wind_gusts_10m, pl_data, elevation_m, thermal_top_m,
            climb_rate_ms, region_id=None, altitude_gusts=None):
    res = orig_tq(wind_speed_10m, wind_gusts_10m, pl_data, elevation_m,
                  thermal_top_m, climb_rate_ms, region_id, altitude_gusts)
    try:
        climb, elev, ttop = climb_rate_ms, elevation_m, thermal_top_m
        if not (isinstance(climb, (int, float)) and climb >= MIN_CLIMB):
            return res
        if not (isinstance(ttop, (int, float)) and ttop > elev):
            return res
        segs, _ = engine._calculate_segment_shear(wind_speed_10m, pl_data, elev, ttop)
        torn_pl = [s for s in segs if _seg_torn(s, elev, ttop, climb)
                   and abs(s["alt_lo"] - elev) >= 1.0]
        if not torn_pl:
            return res
        zone = get_terrain_zone(elev, region_id)
        cfg = config.SHEAR_THRESHOLDS.get(zone, config.SHEAR_THRESHOLDS["alpen"])
        seg = min(torn_pl, key=lambda s: s["alt_lo"])
        du = seg["du_dz"]
        klass = ("SHEAR-ECHT" if du >= cfg["danger"]
                 else "SHEAR-WARN" if du >= cfg["warn"] else "CLIMB-ARTEF")
        records.append({"du": du, "warn": cfg["warn"], "danger": cfg["danger"],
                        "zone": zone, "klass": klass,
                        "tears_peak": (climb / du) * 100.0 <= BS_DANGER})
    except Exception:
        pass
    return res


engine._thermal_quality_tags = wrapped

regions = [r for r in _load_regions() if r["id"] in engine.region_weather_data]
dates = sorted({ts.split("T")[0]
                for ts in engine.region_weather_data.get(regions[0]["id"], {}).get("hourly_data", {})})
for region in regions:
    for d in dates:
        try:
            engine._build_single_region_context(region, d)
        except Exception:
            pass


def pct(a, b):
    return f"{100*a/b:.0f}%" if b else "-"


n = len(records)
print("=" * 60)
print(f"REGION-TORN Echtheits-Split — {n} TORN-PL-Faelle")
print("=" * 60)
for k in ("SHEAR-ECHT", "SHEAR-WARN", "CLIMB-ARTEF"):
    rows = [r for r in records if r["klass"] == k]
    if rows:
        zones = {}
        for r in rows:
            zones[r["zone"]] = zones.get(r["zone"], 0) + 1
        tears = sum(1 for r in rows if r["tears_peak"])
        print(f"{k:<12}: {len(rows)} ({pct(len(rows), n)}) | "
              f"zerreisst Peak-Kern: {tears} ({pct(tears, len(rows))}) | Zonen: {zones}")
    else:
        print(f"{k:<12}: 0")
echt = sum(1 for r in records if r["klass"] != "CLIMB-ARTEF")
print("-" * 60)
print(f"shear-getrieben (echt): {echt} ({pct(echt, n)})  |  "
      f"climb-artefakt: {n - echt} ({pct(n - echt, n)})")
