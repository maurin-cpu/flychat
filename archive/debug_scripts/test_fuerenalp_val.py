import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import fetch_weather

def test_fetch():
    name = "Fürenalp"
    lat = 46.8049
    lon = 8.4419
    
    hourly, pressure, ref_points = fetch_weather.get_weather_for_location(name, lat, lon)
    if hourly:
        print("T=None für 02.04 12:00?", hourly.get('2026-04-02T12:00', {}).get('temperature_2m'))
    else:
        print("Fehlschlag!")

if __name__ == "__main__":
    test_fetch()
