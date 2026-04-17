import sys
from pathlib import Path

import requests

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
import config
from source_area import get_reference_points

def debug_api():
    name = "Fürenalp"
    lat = 46.8049
    lon = 8.4419
    
    ref_points = get_reference_points(name, lat, lon)
    lat_str = ",".join(str(round(p[0], 4)) for p in ref_points)
    lon_str = ",".join(str(round(p[1], 4)) for p in ref_points)
    
    params = {
        "latitude": lat_str,
        "longitude": lon_str,
        "hourly": ",".join(config.HOURLY_PARAMS),
        "models": config.THERMAL_MODEL,
        "timezone": config.TIMEZONE,
        "elevation": "nan"
    }
    
    print(f"URL: {config.API_URL}?latitude={lat_str}&longitude={lon_str}&models={config.THERMAL_MODEL}")
    r = requests.get(config.API_URL, params=params)
    data = r.json()
    
    primary = data[0]
    temps = primary["hourly"]["temperature_2m"]
    times = primary["hourly"]["time"]
    
    print("Primary Coordinate:", primary["latitude"], primary["longitude"])
    for i, t in enumerate(times):
        if "12:00" in t:
            print(f"{t} -> temp: {temps[i]}")

if __name__ == "__main__":
    debug_api()
