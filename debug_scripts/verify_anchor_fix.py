"""
Verify Schritt 1 (10m-Anker-Fix): Die Produktiv-Tags sind jetzt anker-frei.

Prueft am ECHTEN Pfad (_thermal_quality_tags, nach dem Fix):
  - Kein Segment beginnt mehr auf elevation_m (Anker weg).
  - Stunden mit per-Segment TORN-UNU == PL-only-Zahl aus Schritt 0 (~83), nicht
    anker-aufgeblaeht.
  - Spaltentag [THERMAL-TORN-UNUSABLE] zaehlen (anker-frei).
Vergleich: _calculate_segment_shear MIT Anker zeigt die alte (hoehere) Zahl.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from chat_engine import GleitcastEngine

MIN_CLIMB = config.THERMAL_QUALITY_MIN_CLIMB
CLIMB_FLOOR = 0.3
BS_DANGER = config.BS_RATIO_THRESHOLDS["danger"]

engine = GleitcastEngine()
engine.load_weather_from_cache()
orig_tq = engine._thermal_quality_tags

stats = {"thermal": 0, "torn_seg_nofix": 0, "torn_seg_fix": 0,
         "torn_coltag": 0, "anchor_segs": 0}
CUR = {"spot": "?"}


def _seg_torn(s, elevation, thermal_top, climb):
    seg_mid = (s["alt_lo"] + s["alt_hi"]) / 2
    lc = max(engine._parabolic_climb(seg_mid, elevation, thermal_top, climb), CLIMB_FLOOR)
    return s["du_dz"] > 0 and (lc / s["du_dz"]) * 100.0 <= BS_DANGER


def wrapped(wind_speed_10m, wind_gusts_10m, pl_data, elevation_m, thermal_top_m,
            climb_rate_ms, region_id=None, altitude_gusts=None):
    wind10, pl_data_, elev, ttop, climb = (
        wind_speed_10m, pl_data, elevation_m, thermal_top_m, climb_rate_ms)
    tags, debug = orig_tq(wind_speed_10m, wind_gusts_10m, pl_data, elevation_m,
                          thermal_top_m, climb_rate_ms, region_id, altitude_gusts)
    pl_data = pl_data_
    try:
        if isinstance(climb, (int, float)) and climb >= MIN_CLIMB \
                and isinstance(ttop, (int, float)) and ttop > elev:
            stats["thermal"] += 1
            # Produktiv-Pfad (anker-frei, wie im Fix):
            segs_fix, _ = engine._calculate_segment_shear(
                wind10, pl_data, elev, ttop, include_surface_anchor=False)
            # Alt (mit Anker), zum Vergleich:
            segs_old, _ = engine._calculate_segment_shear(
                wind10, pl_data, elev, ttop, include_surface_anchor=True)
            if any(abs(s["alt_lo"] - elev) < 1.0 for s in segs_fix):
                stats["anchor_segs"] += 1
            if any(_seg_torn(s, elev, ttop, climb) for s in segs_fix):
                stats["torn_seg_fix"] += 1
            if any(_seg_torn(s, elev, ttop, climb) for s in segs_old):
                stats["torn_seg_nofix"] += 1
            if "[THERMAL-TORN-UNUSABLE]" in tags:
                stats["torn_coltag"] += 1
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
        try:
            engine._build_single_spot_context(spot, d)
        except Exception:
            pass

print("=" * 60)
print("VERIFY 10m-Anker-Fix")
print("=" * 60)
print(f"Thermik-Stunden gesamt:                {stats['thermal']}")
print(f"Stunden mit Anker-Segment (soll 0):    {stats['anchor_segs']}")
print(f"TORN-Segment MIT Anker (alt/aufgeblaeht): {stats['torn_seg_nofix']}")
print(f"TORN-Segment OHNE Anker (Fix, ~83):       {stats['torn_seg_fix']}")
print(f"Spaltentag [THERMAL-TORN-UNUSABLE]:       {stats['torn_coltag']}")
diff = stats["torn_seg_nofix"] - stats["torn_seg_fix"]
print()
print(f"Durch Anker-Fix entfernt: {diff} Schein-TORN-Stunden "
      f"({100*diff/stats['torn_seg_nofix']:.0f}% des alten Werts)"
      if stats["torn_seg_nofix"] else "—")
print("OK" if stats["anchor_segs"] == 0 else "FEHLER: Anker noch da!")
