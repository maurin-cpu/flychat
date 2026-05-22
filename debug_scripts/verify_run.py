"""Verifikations-Run: Spot-Subset fuer altitude_rating-Verifikation.

Volle 487 Spots dauern > 30 Min (Gemini-503 + JSON-Errors).
30 Spots evenly distributed reichen fuer altitude_rating-Bandbreite.
Region-Phase wird ausgelassen (Cache hat schon 49 valide Eintraege).
"""
import json
import logging
import time

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

from chat_engine import GleitcastEngine

wd = json.load(open('data/wetterdaten.json', encoding='utf-8'))
all_spots = sorted([k for k in wd.keys() if k != "_meta"])
step = max(1, len(all_spots) // 30)
spots_with_data = all_spots[::step][:30]
print(f"Subset: {len(spots_with_data)} of {len(all_spots)} spots", flush=True)

print("Init engine...", flush=True)
engine = GleitcastEngine()
engine.load_weather_from_cache()
print("Engine ready", flush=True)

t0 = time.time()

print(f"\n=== Spot analyses (subset {len(spots_with_data)}) ===", flush=True)
s_res = engine.run_spot_analyses(spot_names=spots_with_data)
print(f"  -> {s_res}", flush=True)

dt = time.time() - t0
print(f"\nDone in {dt:.1f}s", flush=True)
