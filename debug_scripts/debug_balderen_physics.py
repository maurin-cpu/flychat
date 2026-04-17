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
        
        print("Time  | T_surf | T_850 | T_700 | Cloud | C_Base | H_flux | Direct | Diff")
        print("-" * 85)
        for ts in sorted(b_data.keys()):
            if "2026-04-03" in ts:
                hour = int(ts[11:13])
                if 12 <= hour <= 20:
                    hf = b_data[ts]
                    p = p_data.get(ts, {})
                    
                    surf_t = hf.get('temperature_2m')
                    t850 = p.get('temperature_850hPa')
                    t700 = p.get('temperature_700hPa')
                    cloud = hf.get('cloud_cover')
                    c_base = hf.get('cloud_base')
                    h_flux = hf.get('surface_sensible_heat_flux')
                    dir_rad = hf.get('direct_radiation')
                    diff_rad = hf.get('diffuse_radiation')
                    
                    def fmt(v, f): return format(v, f) if v is not None else "  N/A"
                    print(f"{ts[11:16]} | {fmt(surf_t,'>6.1f')} | {fmt(t850,'>5.1f')} | {fmt(t700,'>5.1f')} | {fmt(cloud,'>5.0f')} | {fmt(c_base,'>6.0f')} | {fmt(h_flux,'>6.0f')} | {fmt(dir_rad,'>6.0f')} | {fmt(diff_rad,'>4.0f')}")
except Exception as e:
    print(e)
