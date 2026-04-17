import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
try:
    with open(_ROOT / "data" / "wetterdaten.json", "r", encoding="utf-8") as f:
        d = json.load(f)
        b_data = d.get('Balderen', {}).get('hourly_data', {})
        p_data = d.get('Balderen', {}).get('pressure_level_data', {})
        
        from chat_engine import FlychatEngine
        
        # Override to disable inertia for the test
        import thermik_calculator
        
        eng = FlychatEngine()
        spot = [s for s in eng.spots if s['name'] == 'Balderen'][0]
        
        print("Time  | Climb | Max_H | Rating | Warnings")
        print("-" * 70)
        for ts in sorted(b_data.keys()):
            if "2026-04-03" in ts:
                hour = int(ts[11:13])
                if 12 <= hour <= 19:
                    hf = b_data[ts]
                    pl = p_data.get(ts, {})
                    
                    therm = eng._calculate_thermal_raw(hf, pl, spot['elevation_m'], ts, spot, prev_max_h=None)
                    climb = therm.get('climb_rate', 0)
                    mxh = therm.get('max_height', 0)
                    rating = therm.get('rating', 0)
                    warns = therm.get('data_warnings', [])
                    print(f"{ts[11:16]} | {climb:>5.1f} | {mxh:>5.0f} | {rating:>6d} | {warns}")
except Exception as e:
    print(e)
