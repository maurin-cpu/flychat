import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import fetch_weather
import config

def debug_fetch():
    spots = [
        {"name": "Balderen", "latitude": 47.33, "longitude": 8.52, "fluggebiet": "Uetliberg", "elevation_m": 850},
        {"name": "First", "latitude": 46.66, "longitude": 8.04, "fluggebiet": "Grindelwald", "elevation_m": 2160},
        {"name": "Tümpfeli", "latitude": 46.90, "longitude": 8.41, "fluggebiet": "Niederbauen", "elevation_m": 1570},
        {"name": "Brunnihütte", "latitude": 46.84, "longitude": 8.41, "fluggebiet": "Engelberg", "elevation_m": 1860},
        {"name": "Fürenalp", "latitude": 46.8049, "longitude": 8.4419, "fluggebiet": "Engelberg", "elevation_m": 1840},
    ]
    
    # Just run fetch for Fürenalp to see if it's reproducible when simulating the bulk sequence
    # Wait, let's look at the ACTUAL wetterdaten.json
    with open(_ROOT / "data" / "wetterdaten.json", "r", encoding="utf-8") as f:
        d = json.load(f)
        spot_data = d.get('Fürenalp', {}).get('hourly_data', {})
        
    for ts in sorted(spot_data.keys()):
        if "12:00" in ts:
            val = spot_data[ts].get('temperature_2m')
            print(f"{ts} -> temperature_2m: {val}")

if __name__ == "__main__":
    debug_fetch()
