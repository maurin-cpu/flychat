"""
Verify Schritt 2 (TORN-Binaer-Gate): Stunden mit [THERMAL-TORN-UNUSABLE] und
produktivem Climb fallen jetzt aus den Produktiv-Zaehlern.

Zaehlt per Thermik-Stunde:
  - hat Spalten-Tag [THERMAL-TORN-UNUSABLE]?  (anker-frei, = Gate-Signal)
  - und Climb >= PRODUCTIVE_CLIMB_MIN?        (waere sonst produktiv-Kandidat)
Die Schnittmenge = Stunden, die Schritt 2 aus productive_thermal_h entfernt
(modulo band_usable, das nur weiter reduziert). Aggregiert nach Spot.
"""
import sys, os
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from chat_engine import GleitcastEngine

MIN_CLIMB = config.THERMAL_QUALITY_MIN_CLIMB
PROD_MIN = config.PRODUCTIVE_CLIMB_MIN

engine = GleitcastEngine()
engine.load_weather_from_cache()
orig_tq = engine._thermal_quality_tags

per_spot = defaultdict(int)
tot = {"thermal": 0, "torn": 0, "torn_prod": 0}
CUR = {"spot": "?"}


def wrapped(wind_speed_10m, wind_gusts_10m, pl_data, elevation_m, thermal_top_m,
            climb_rate_ms, region_id=None, altitude_gusts=None):
    tags, debug = orig_tq(wind_speed_10m, wind_gusts_10m, pl_data, elevation_m,
                          thermal_top_m, climb_rate_ms, region_id, altitude_gusts)
    try:
        if isinstance(climb_rate_ms, (int, float)) and climb_rate_ms >= MIN_CLIMB:
            tot["thermal"] += 1
            if "[THERMAL-TORN-UNUSABLE]" in tags:
                tot["torn"] += 1
                if climb_rate_ms >= PROD_MIN:
                    tot["torn_prod"] += 1
                    per_spot[CUR["spot"]] += 1
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
print("VERIFY TORN-Binaer-Gate (Schritt 2)")
print("=" * 60)
print(f"Thermik-Stunden:                          {tot['thermal']}")
print(f"mit [THERMAL-TORN-UNUSABLE] (anker-frei): {tot['torn']}")
print(f"davon Climb >= {PROD_MIN} (jetzt rausgegated):  {tot['torn_prod']}")
print(f"Betroffene Spots:                         {len(per_spot)}")
print()
print("Top betroffene Spots (rausgegatete produktive TORN-Std):")
for name, n in sorted(per_spot.items(), key=lambda kv: kv[1], reverse=True)[:12]:
    print(f"  {name[:40]:<40} {n}")
