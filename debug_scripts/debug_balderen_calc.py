import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
try:
    with open(_ROOT / "data" / "wetterdaten.json", "r", encoding="utf-8") as f:
        d = json.load(f)
        b_data = d.get('Balderen', {}).get('hourly_data', {})
        p_data = d.get('Balderen', {}).get('pressure_level_data', {})

        from chat_engine import WingcastEngine
        from thermik_calculator import compute_daily_thermals
        import config

        eng = WingcastEngine()
        spot = [s for s in eng.spots if s['name'] == 'Balderen'][0]

        daily = compute_daily_thermals(
            b_data, p_data, spot['elevation_m'], config.PRESSURE_LEVELS,
            slope_azimuth=spot.get('slope_azimuth'),
            slope_angle=spot.get('slope_angle'),
        )

        print("Time  | Climb | Max_H | Rating | Warnings")
        print("-" * 70)
        for ts in sorted(b_data.keys()):
            if "2026-04-03" in ts:
                hour = int(ts[11:13])
                if 12 <= hour <= 19:
                    therm = daily.get(ts) or {}
                    climb = therm.get('climb_rate', 0)
                    mxh = therm.get('max_height', 0)
                    rating = therm.get('rating', 0)
                    warns = therm.get('data_warnings', [])
                    print(f"{ts[11:16]} | {climb:>5.1f} | {mxh:>5.0f} | {rating:>6d} | {warns}")
except Exception as e:
    print(e)
