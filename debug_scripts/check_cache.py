"""Quick check of weather cache to debug missing data for today."""
import json
import sys
from datetime import datetime

cache_path = "C:/Users/user/OneDrive/Projekte/gleitcast/data/wetterdaten.json"
with open(cache_path, "r", encoding="utf-8") as f:
    d = json.load(f)

print("Meta:", json.dumps(d.get("_meta", {}), indent=2))

spots = [k for k in d.keys() if k != "_meta"]
print(f"\nSpots: {len(spots)}")

if not spots:
    print("NO SPOTS FOUND!")
    sys.exit(1)

s = spots[0]
print(f"First spot: {s}")
sd = d.get(s, {})
print(f"Keys: {list(sd.keys())}")

# Check hourly data
hourly = sd.get("hourly_data", {})
print(f"\nHourly timestamps: {len(hourly)}")
h_times = sorted(hourly.keys())
if h_times:
    print(f"Hourly first: {h_times[0]}")
    print(f"Hourly last: {h_times[-1]}")
    today_h = [t for t in h_times if t.startswith("2026-04-12")]
    print(f"Hourly today: {len(today_h)} timestamps")

# Check pressure level data
pl = sd.get("pressure_level_data", {})
print(f"\nPressure level timestamps: {len(pl)}")
times = sorted(pl.keys())
if times:
    print(f"PL first: {times[0]}")
    print(f"PL last: {times[-1]}")
    today_times = [t for t in times if t.startswith("2026-04-12")]
    print(f"PL today: {len(today_times)} timestamps")
    if today_times:
        print(f"PL today first: {today_times[0]}")
        print(f"PL today last: {today_times[-1]}")
        # Check content of first today timestamp
        first_data = pl[today_times[0]]
        geo_keys = [k for k in first_data.keys() if "geopotential" in k]
        print(f"\nGeopotential keys in first today entry: {geo_keys}")
        for gk in geo_keys[:5]:
            print(f"  {gk}: {first_data[gk]}")
        wind_keys = [k for k in first_data.keys() if "wind_speed" in k and "hPa" in k]
        print(f"\nWind speed keys: {wind_keys}")
        for wk in wind_keys[:5]:
            print(f"  {wk}: {first_data[wk]}")
    else:
        print("NO pressure level data for today!")
        # What dates DO we have?
        dates = set()
        for t in times:
            dates.add(t[:10])
        print(f"Available dates: {sorted(dates)}")
else:
    print("NO pressure level data at all!")

# Check system time
print(f"\nSystem datetime.now(): {datetime.now()}")
print(f"Today str: {datetime.now().strftime('%Y-%m-%d')}")
