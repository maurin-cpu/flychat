"""
Debug: Warum productive_thermal_h < 4 fuer Alpstein/Ostschweiz 24.04.2026?

Baut exakt den Kontext wie _build_single_region_context und zeigt:
- Pro-Stunde climb, clouds, tq_tags
- productive_thermal_h / band_too_shallow_h
- worst_gf, thermal_top, band_depth
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chat_engine import WingcastEngine
from source_area import get_all_regions

engine = WingcastEngine()
engine.load_weather_from_cache()

target = None
for r in get_all_regions():
    if r.get("id") == "alpstein":
        target = r
        break

if not target:
    print("Region alpstein nicht gefunden")
    sys.exit(1)

date_str = "2026-04-24"
print(f"Region: {target['region']} (id={target['id']}, elev_ref={target.get('elevation_ref')}m)")
print(f"Datum:  {date_str}")
print("=" * 90)

import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

context = engine._build_single_region_context(target, date_str)
if not context:
    print("KEIN KONTEXT - pruefe Cache-Daten.")
    rwd = getattr(engine, "region_weather_data", {})
    if "alpstein" in rwd:
        print(f"  alpstein keys: {list(rwd['alpstein'].keys())[:5]}")
        if "hourly" in rwd["alpstein"]:
            ts = sorted(rwd["alpstein"]["hourly"].keys())
            print(f"  erste timestamps: {ts[:3]}")
            print(f"  letzte timestamps: {ts[-3:]}")
    sys.exit(1)

# Vollen Kontext ausgeben
print(context)
print("=" * 90)

# Zusaetzlich: cache_tq inspizieren
cache = getattr(engine, "_ctx_tq_cache", None)
if cache:
    key = f"{target['region']}|{date_str}"
    # Key-Variante probieren
    for k in list(cache.keys())[:20]:
        if "alpstein" in k.lower() or "Alpstein" in k:
            print(f"TQ-CACHE [{k}]: {cache[k]}")
            break
