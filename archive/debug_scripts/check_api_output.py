"""Simulate what api_altitude_wind does to check if profiles exist for today."""
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
import config

cache_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "wetterdaten.json")
with open(cache_path, "r", encoding="utf-8") as f:
    data = json.load(f)

spot_name = "Balderen"
spot_data = data.get(spot_name, {})
pressure_level_data = spot_data.get("pressure_level_data", {})
hourly_data = spot_data.get("hourly_data", {})
elevation_m = spot_data.get("elevation_m")

print(f"Spot: {spot_name}, elevation: {elevation_m}")
print(f"PL timestamps: {len(pressure_level_data)}")
print(f"Hourly timestamps: {len(hourly_data)}")

# Simulate format_altitude_wind_for_charts (simplified - just check profile building)
from web import format_altitude_wind_for_charts

alt_data = format_altitude_wind_for_charts(pressure_level_data, hourly_data, elevation_m)
profiles = alt_data.get("profiles", [])
print(f"\nformat_altitude_wind_for_charts returned {len(profiles)} profiles")

if profiles:
    # Check dates
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    print(f"\nToday: {today_str}")

    by_day = {}
    for profile in profiles:
        try:
            dt = datetime.fromisoformat(profile["time"])
            date_str = dt.strftime("%Y-%m-%d")
            if date_str >= today_str:
                if date_str not in by_day:
                    by_day[date_str] = []
                by_day[date_str].append({
                    "hour": dt.hour,
                    "n_levels": len(profile["levels"]),
                })
        except Exception as e:
            print(f"  Error parsing {profile.get('time')}: {e}")

    max_date_str = (now.date() + timedelta(days=config.FORECAST_DAYS - 1)).strftime("%Y-%m-%d")
    sorted_dates = [d for d in sorted(by_day.keys()) if d <= max_date_str]

    print(f"\nDates in output: {sorted_dates}")
    for d in sorted_dates:
        hours = by_day[d]
        print(f"  {d}: {len(hours)} profiles, hours: {[h['hour'] for h in hours]}")
        print(f"    Levels per profile: {[h['n_levels'] for h in hours[:3]]}...")
else:
    print("\nNO PROFILES - checking individual timestamps...")
    sorted_times = sorted(pressure_level_data.keys())
    for ts in sorted_times[:5]:
        pdata = pressure_level_data[ts]
        levels_with_height = 0
        for level in config.PRESSURE_LEVELS:
            h = pdata.get(f"geopotential_height_{level}hPa")
            if h is not None:
                levels_with_height += 1
        print(f"  {ts}: {levels_with_height} levels with height data")

    # Try parsing first timestamp manually
    ts = sorted_times[0]
    print(f"\n  Manual parse of '{ts}':")
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        print(f"    Parsed: {dt}")
        print(f"    isoformat: {dt.isoformat()}")
        print(f"    Type: {'aware' if dt.tzinfo else 'naive'}")
    except Exception as e:
        print(f"    Error: {e}")
