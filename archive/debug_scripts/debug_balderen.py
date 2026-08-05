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
        
        print("Time  | T_surf | T_850 | T_700 | H_flux | Cloud | BLH_gfs | CAPE")
        print("-" * 75)
        for ts in sorted(b_data.keys()):
            if "2026-04-03" in ts:
                hour = int(ts[11:13])
                if 12 <= hour <= 19:
                    surf_t = b_data[ts].get('temperature_2m')
                    h_flux = b_data[ts].get('surface_sensible_heat_flux')
                    cloud = b_data[ts].get('cloud_cover')
                    blh = b_data[ts].get('boundary_layer_height_gfs')
                    cape = b_data[ts].get('cape')
                    
                    p = p_data.get(ts, {})
                    t850 = p.get('temperature_850hPa')
                    t700 = p.get('temperature_700hPa')
                    
                    def fmt(v, f): return format(v, f) if v is not None else "  N/A"
                    print(f"{ts[11:16]} | {fmt(surf_t,'>6.1f')} | {fmt(t850,'>5.1f')} | {fmt(t700,'>5.1f')} | {fmt(h_flux,'>6.0f')} | {fmt(cloud,'>5.0f')} | {fmt(blh,'>7.0f')} | {fmt(cape,'>4.0f')}")
except Exception as e:
    print(e)
