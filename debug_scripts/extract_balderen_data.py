
import json
import os

filepath = r"c:\Users\user\OneDrive\Projekte\flychat\data\wetterdaten.json"
spot = "Balderen"
target_date = "2026-03-15"

if not os.path.exists(filepath):
    print(f"File not found: {filepath}")
else:
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
        spot_data = data.get(spot, {}).get("hourly_data", {})
        sorted_times = sorted(spot_data.keys())
        print(f"--- {spot} Wind Data ---")
        for ts in sorted_times:
            if ts.startswith(target_date):
                dt_hour = int(ts.split('T')[1].split(':')[0])
                if 8 <= dt_hour <= 18:
                    h = spot_data[ts]
                    ws = h.get("wind_speed_10m", "N/A")
                    wg = h.get("wind_gusts_10m", "N/A")
                    wd = h.get("wind_direction_10m", "N/A")
                    print(f"{ts}: Wind {ws} km/h, Gusts {wg} km/h, Dir {wd}")
