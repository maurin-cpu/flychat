"""
Einmal-Diagnose: Mittelland Ost — ALLE Tage im Cache, pro Thermik-Stunde
die volle Wind-Leiter (Boden bis Thermik-Top + 2 Stufen drueber) mit
Scherung du_dz pro 100m. Suche speziell das Band mit ~33 km/h + Steigen,
das der User sieht, und pruefe ob es echt zerrissen ist (Scherung) oder
nur starker Absolutwind.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from chat_engine import WingcastEngine
from source_area import _load_regions
from thermik_calculator import get_terrain_zone

TARGET_NAME = "Mittelland Ost"
MIN_CLIMB = config.THERMAL_QUALITY_MIN_CLIMB

engine = WingcastEngine()
engine.load_weather_from_cache()
orig_tq = engine._thermal_quality_tags

calls = []  # (date_marker, data)
CUR = {"date": "?"}


def wrapped(wind_speed_10m, wind_gusts_10m, pl_data, elevation_m, thermal_top_m,
            climb_rate_ms, region_id=None, altitude_gusts=None):
    res = orig_tq(wind_speed_10m, wind_gusts_10m, pl_data, elevation_m,
                  thermal_top_m, climb_rate_ms, region_id, altitude_gusts)
    if isinstance(climb_rate_ms, (int, float)) and climb_rate_ms >= MIN_CLIMB:
        calls.append({"date": CUR["date"], "wind10": wind_speed_10m, "pl": pl_data,
                      "elev": elevation_m, "ttop": thermal_top_m,
                      "climb": climb_rate_ms, "region_id": region_id,
                      "tags": list(res[0])})
    return res


engine._thermal_quality_tags = wrapped

region = next(r for r in _load_regions()
              if r["region"] == TARGET_NAME and r["id"] in engine.region_weather_data)
dates = sorted({ts.split("T")[0]
                for ts in engine.region_weather_data[region["id"]].get("hourly_data", {})})
for d in dates:
    CUR["date"] = d
    try:
        engine._build_single_region_context(region, d)
    except Exception as e:
        print("ERR", d, e)

zone = get_terrain_zone(calls[0]["elev"], calls[0]["region_id"]) if calls else "?"
cfg = config.SHEAR_THRESHOLDS.get(zone, config.SHEAR_THRESHOLDS["alpen"])
warn, danger = cfg["warn"], cfg["danger"]


def ladder(pl, elev, ttop):
    """Sortierte (hoehe, wind) Stufen aus den Pressure-Levels, plus 10m unten."""
    pts = []
    for lv in config.PRESSURE_LEVELS:
        h = pl.get(f"geopotential_height_{lv}hPa")
        w = pl.get(f"wind_speed_{lv}hPa")
        if isinstance(h, (int, float)) and isinstance(w, (int, float)) and h > elev:
            pts.append((h, w))
    return sorted(pts)


print("=" * 78)
print(f"{TARGET_NAME} | Zone={zone} warn={warn} danger={danger} | elev={calls[0]['elev']:.0f}m")
print("=" * 78)

for c in calls:
    if c["climb"] < 1.0:
        continue  # nur ernsthafte Thermik-Stunden
    pts = ladder(c["pl"], c["elev"], c["ttop"])
    torn = "[THERMAL-TORN-UNUSABLE]" in c["tags"]
    print(f"\n{c['date']} | climb={c['climb']:.1f} | Top={c['ttop']:.0f}m "
          f"| TORN-gate={'JA' if torn else 'nein'}")
    prev = None
    for h, w in pts:
        inb = "  " if h <= c["ttop"] else " ^"   # ^ = ueber Thermik-Top
        if prev is not None:
            ph, pw = prev
            du = abs(w - pw) / (h - ph) * 100.0
            st = "DANGER" if du >= danger else "warn" if du >= warn else "ok"
        else:
            du, st = 0.0, "-"
        lc = engine._parabolic_climb(h, c["elev"], c["ttop"], c["climb"]) if h <= c["ttop"] else 0
        print(f"  {h:>6.0f}m{inb}  wind={w:>5.1f} km/h   du_dz={du:>5.2f} {st:<7} climb~{lc:.1f}")
        prev = (h, w)
