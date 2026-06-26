"""
Faehrt die Band-Cap-Diagnostik gegen den Foehn-Cache (statt Live-Cache).
Setzt config.WEATHER_JSON_PATH auf den Foehn-Cache UM, bevor die Skripte laden —
der Live-Cache (data/wetterdaten.json) wird NICHT angefasst.

Usage: python3 debug_scripts/run_foehn_diagnostics.py [DATE]
"""
import sys, os, pathlib, runpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import config

DATE = sys.argv[1] if len(sys.argv) > 1 else "2026-05-28"
FOEHN = pathlib.Path(os.path.dirname(HERE)) / "data" / f"foehn_cache_{DATE}.json"
assert FOEHN.exists(), f"Foehn-Cache fehlt: {FOEHN} — erst build_foehn_cache.py laufen lassen"

# Live-Cache-Pfad UMBIEGEN auf den Foehn-Cache (load_cached_weather liest zur Laufzeit).
config.WEATHER_JSON_PATH = FOEHN
print(f"### Foehn-Diagnostik gegen {FOEHN.name}  (Live-Cache unberuehrt)\n")

SCRIPTS = [
    "region_band_cap_potential.py",
    "spot_band_cap_potential.py",
    "verify_band_cap.py",
    "test_torn_regions_echtheit.py",
]
for s in SCRIPTS:
    print("\n" + "#" * 72)
    print(f"### {s}")
    print("#" * 72)
    try:
        runpy.run_path(os.path.join(HERE, s), run_name="__main__")
    except SystemExit:
        pass
    except Exception as e:
        import traceback
        print(f"!!! {s} FEHLER: {e}")
        traceback.print_exc()
