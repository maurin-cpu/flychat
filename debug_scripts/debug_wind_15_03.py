
import json
import sys
import os
from datetime import datetime

# Set Python path to include current directory
sys.path.append(os.getcwd())

import config
from spots import load_spots, get_spot_by_name

def debug_wind():
    spots = load_spots()
    spot = get_spot_by_name(spots, "Balderen")
    if not spot:
        print("Spot Balderen not found")
        return

    print(f"Spot: {spot['name']}, Elevation: {spot['elevation_m']}m MSL")

    # Load weather data
    if not config.WEATHER_JSON_PATH.exists():
        print(f"Weather data not found at {config.WEATHER_JSON_PATH}")
        return

    with open(config.WEATHER_JSON_PATH, "r", encoding="utf-8") as f:
        all_weather = json.load(f)

    spot_weather = all_weather.get(spot["name"])
    if not spot_weather:
        print(f"No weather data for {spot['name']}")
        return

    hourly_data = spot_weather.get("hourly_data", {})

    target_date = "2026-03-15"
    print(f"Analyzing Wind for: {target_date}")

    sorted_times = sorted(hourly_data.keys())
    print(f"{'Time':<20} | {'Wind (km/h)':<12} | {'Gusts (km/h)':<12} | {'Dir':<5} | {'Tags':<20}")
    print("-" * 80)
    for ts in sorted_times:
        if not ts.startswith(target_date):
            continue
        
        data = hourly_data[ts]
        speed = data.get("wind_speed_10m", 0)
        gusts = data.get("wind_gusts_10m", 0)
        direction = data.get("wind_direction_10m", 0)
        
        # Approximate direction
        dirs = ["N", "NNO", "NO", "ONO", "O", "OSO", "SO", "SSO", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
        dir_idx = int((direction + 11.25) / 22.5) % 16
        dir_str = dirs[dir_idx]

        tags = []
        if speed >= 15: tags.append("SOARING-MIN")
        if speed >= 20: tags.append("SOARING-GOOD")
        
        print(f"{ts:<20} | {speed:<12.1} | {gusts:<12.1} | {dir_str:<5} | {', '.join(tags)}")

if __name__ == "__main__":
    debug_wind()
