import json
from datetime import datetime
from thermik_calculator import calculate_thermal_profile, calculate_thermic_clouds

def deep_debug_16_03():
    with open('data/wetterdaten.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    balderen = data['Balderen']
    hourly = balderen.get('hourly_data', {})
    pl_data = balderen.get('pressure_level_data', {})
    
    print(f"--- Deep Debug Balderen 16.03. (10:00 vs 11:00) ---")
    
    import config
    for hour_target in [10, 11, 12]:
        ts = f"2026-03-16T{hour_target:02d}:00"
        if ts not in hourly: continue
        
        d = hourly[ts]
        low = d.get('cloud_cover_low', 0)
        mid = d.get('cloud_cover_mid', 0)
        high = d.get('cloud_cover_high', 0)
        
        c_res = calculate_thermic_clouds(low, mid, high)
        
        p_levels = []
        if ts in pl_data:
            for level in config.PRESSURE_LEVELS:
                h_val = pl_data[ts].get(f"geopotential_height_{level}hPa")
                t_val = pl_data[ts].get(f"temperature_{level}hPa")
                if h_val is not None and t_val is not None:
                    p_levels.append({"pressure": level, "height": h_val, "temp": t_val})

        therm = calculate_thermal_profile(
            surface_temp=d.get("temperature_2m"),
            surface_dewpoint=d.get("temperature_2m"),
            elevation_m=balderen.get("elevation_m", 730),
            pressure_levels_data=p_levels,
            boundary_layer_height_agl=d.get("boundary_layer_height"),
            sunshine_duration_s=d.get("sunshine_duration"),
            shortwave_radiation=d.get("shortwave_radiation"),
            low_cloud=low,
            mid_cloud=mid,
            high_cloud=high,
            timestamp=ts
        )

        print(f"\nSTUNDE {hour_target:02d}:00")
        print(f"  Clouds: Low={low}%, Mid={mid}%, High={high}% -> Score={c_res['display_cloud']:.1f}%")
        print(f"  SunIndex: {c_res['sun_index']:.1f}% -> SunFactor: {c_res['sun_factor']:.3f}")
        print(f"  Radiation: {d.get('shortwave_radiation')} W/m2")
        print(f"  Climb: {therm.get('climb_rate'):.2f} m/s | Rating: {therm.get('rating')}/10")
        
        if 'diagnostics' in therm:
            diag = therm['diagnostics']
            h_flux = diag.get('H_sensible_flux')
            w_parcel = diag.get('w_star_parcel')
            print(f"  Diag: H_flux={h_flux if h_flux is not None else 0:.1f} W/m2 | w_star_parcel={w_parcel if w_parcel is not None else 0:.2f}")
            print(f"  MaxAlt: {therm.get('max_height')}m MSL")

if __name__ == "__main__":
    deep_debug_16_03()
