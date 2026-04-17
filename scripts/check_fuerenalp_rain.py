import os
import sys

# Add parent dir to path to import local modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from source_area import get_reference_points
from spots import load_spots, get_spot_by_name
import requests

spots = load_spots()
fuerenalp = get_spot_by_name(spots, "Fürenalp")
if not fuerenalp:
    print("Fürenalp not found in spots")
    sys.exit(1)

lat = fuerenalp["latitude"]
lon = fuerenalp["longitude"]
print(f"Fürenalp coords: lat={lat}, lon={lon}")

ref_points = get_reference_points("Fürenalp", lat, lon)
print(f"Ref points ({len(ref_points)}): {ref_points}")

lat_str = ",".join(str(round(p[0], 4)) for p in ref_points)
lon_str = ",".join(str(round(p[1], 4)) for p in ref_points)

# Since thermal model is icon_d2 and fallback is icon_eu
# Wind is meteoswiss_icon_ch1
params = {
    "latitude": lat_str,
    "longitude": lon_str,
    "models": config.THERMAL_MODEL, # Let's check thermal model first, and fallback
    "hourly": "precipitation",
    "forecast_days": 5,
    "timezone": config.TIMEZONE,
}

print(f"Fetching {config.THERMAL_MODEL}...")
resp = requests.get(config.API_URL, params=params)
data_list = resp.json() if isinstance(resp.json(), list) else [resp.json()]

for d in data_list:
    times = d.get("hourly", {}).get("time", [])
    precip = d.get("hourly", {}).get("precipitation", [])
    if not times:
        print("No hourly valid data")
        continue
    print(f"Model ID: {d.get('id', 'N/A')}, lat={d.get('latitude')}, lon={d.get('longitude')}")
    # Print precip for wednesday (April 1st)
    for t, p in zip(times, precip):
        if "04-01" in t and 10 <= int(t[11:13]) <= 17:
             print(f"  {t}: {p} mm")

print(f"\nFetching {config.FALLBACK_MODEL}...")
params["models"] = config.FALLBACK_MODEL
resp = requests.get(config.API_URL, params=params)
data_list = resp.json() if isinstance(resp.json(), list) else [resp.json()]

for d in data_list:
    times = d.get("hourly", {}).get("time", [])
    precip = d.get("hourly", {}).get("precipitation", [])
    if not times:
        print("No hourly valid data")
        continue
    print(f"Model ID: {d.get('id', 'N/A')}, lat={d.get('latitude')}, lon={d.get('longitude')}")
    for t, p in zip(times, precip):
        if "04-01" in t and 10 <= int(t[11:13]) <= 17:
             print(f"  {t}: {p} mm")
             
# Test aggregation logic
from fetch_weather import get_weather_for_location
print("\nFetching with fetch_weather.py get_weather_for_location...")
hourly, _, _ = get_weather_for_location("Fürenalp", lat, lon)
for ts, hd in hourly.items():
    if "04-01" in ts and 10 <= int(ts[11:13]) <= 17:
        print(f"  {ts}: precipitation = {hd.get('precipitation')} mm")

