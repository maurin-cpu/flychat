import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import fetch_weather
import chat_engine

def do_refresh():
    # Increase delay to avoid 40 calls / min rate limit
    fetch_weather.API_DELAY_BETWEEN_CALLS = 2.0
    fetch_weather.API_DELAY_BETWEEN_SPOTS = 5.0
    
    engine = chat_engine.WingcastEngine()
    print(f"Lade {len(engine.spots)} Spots...")
    engine.weather_data = fetch_weather.fetch_all_spots(engine.spots, save_to_file=True)
    
    # Check Fürenalp
    f_data = engine.weather_data.get("Fürenalp", {}).get("hourly_data", {})
    if f_data:
        days = sorted(list(set(t[:10] for t in f_data.keys())))
        print("Tage für Fürenalp:", days)
        t12_day4 = "2026-04-02T12:00"
        if t12_day4 in f_data:
            print("Day 4 Temp:", f_data[t12_day4].get('temperature_2m'))
    else:
        print("Fürenalp nicht im Cache.")

if __name__ == "__main__":
    do_refresh()
