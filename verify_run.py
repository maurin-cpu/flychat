"""Verifikations-Run mit Cache-Bug-Fix.

Triggert LLM-Analyse fuer Regionen + die 28 Spots mit Wetterdaten.
Schreibt jetzt korrekt safety_band, experience_score, comfort_index,
altitude_rating + 5 Safety-Sub-Ratings in den Cache.
"""
import json
import logging
import time

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

from chat_engine import GleitcastEngine

# Subset: nur Spots mit Wetterdaten
wd = json.load(open('data/wetterdaten.json', encoding='utf-8'))
spots_with_data = [k for k in wd.keys() if k != "_meta"]
print(f"Spots mit Wetterdaten: {len(spots_with_data)}", flush=True)

print("Init engine...", flush=True)
engine = GleitcastEngine()
engine.load_weather_from_cache()
print(f"Engine ready", flush=True)

t0 = time.time()

print("\n=== Region analyses ===", flush=True)
r_res = engine.run_region_analyses()
print(f"  -> {r_res}", flush=True)

print(f"\n=== Spot analyses (nur {len(spots_with_data)} Spots mit Daten) ===", flush=True)
s_res = engine.run_spot_analyses(spot_names=spots_with_data)
print(f"  → {s_res}", flush=True)

dt = time.time() - t0
print(f"\nDone in {dt:.1f}s", flush=True)
