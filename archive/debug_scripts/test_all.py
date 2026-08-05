import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import fetch_weather

def test_fetch_all():
    spots = [
        {"name": "Balderen", "latitude": 47.33, "longitude": 8.52, "fluggebiet": "Uetliberg", "elevation_m": 850},
        {"name": "Fürenalp", "latitude": 46.8049, "longitude": 8.4419, "fluggebiet": "Engelberg", "elevation_m": 1840},
    ]
    
    result = fetch_weather.fetch_all_spots(spots, save_to_file=False)
    for spot_name, data in result.items():
        if spot_name == "_meta": continue
        print(f"\nSpot: {spot_name}")
        hourly = data.get("hourly_data", {})
        times = sorted(hourly.keys())
        days = sorted(list(set(t[:10] for t in times)))
        print("Tage:", days)
        for d in days:
            t12 = f"{d}T12:00"
            if t12 in hourly:
                print(f"  12:00 Temp: {hourly[t12].get('temperature_2m')}  Wind: {hourly[t12].get('wind_speed_10m')}")

if __name__ == "__main__":
    test_fetch_all()
