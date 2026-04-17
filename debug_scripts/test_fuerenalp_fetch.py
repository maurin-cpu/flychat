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
        times = list(hourly.keys())
        days = sorted(list(set(t[:10] for t in times)))
        print("Erfolgreich geholt! Tage:", days)
    else:
        print("Fehlschlag!")

if __name__ == "__main__":
    test_fetch()
