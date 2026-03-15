
import json
import sys
import os
from datetime import datetime

# Set Python path to include current directory
sys.path.append(os.getcwd())

from thermik_calculator import calculate_thermal_profile, calculate_dewpoint
import config
from spots import load_spots, get_spot_by_name

def debug_thermals():
    spots = load_spots()
    spot = get_spot_by_name(spots, "Balderen")
    if not spot:
        print("Spot Balderen not found")
        return

    print(f"Spot: {spot['name']}, Launch Elevation: {spot['elevation_m']}m MSL")

    # Load weather data
    if not config.WEATHER_JSON_PATH.exists():
        print(f"Weather data not found at {config.WEATHER_JSON_PATH}")
        return

    with open(config.WEATHER_JSON_PATH, "r", encoding="utf-8") as f:
        all_weather = json.load(f)

    spot_weather = all_weather.get(spot["name"])
    if not spot_weather:
        print(f"No weather data for {spot['name']}")
        return

    hourly_data = spot_weather.get("hourly_data", {})
    pressure_level_data = spot_weather.get("pressure_level_data", {})

    target_date = "2026-03-15"
    print(f"Analyzing date: {target_date}")

    sorted_times = sorted(hourly_data.keys())
    for ts in sorted_times:
        if not ts.startswith(target_date):
            continue
        
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if not (10 <= dt.hour <= 16):
            continue

        data = hourly_data[ts]
        pl_data = pressure_level_data.get(ts, {})

        p_levels = []
        for level in config.PRESSURE_LEVELS:
            h_val = pl_data.get(f"geopotential_height_{level}hPa")
            t_val = pl_data.get(f"temperature_{level}hPa")
            if h_val is not None and t_val is not None:
                p_levels.append({"pressure": level, "height": h_val, "temp": t_val})

        surf_temp = data.get("temperature_2m")
        surf_rh = data.get("relative_humidity_2m", 50)
        surf_dew = calculate_dewpoint(surf_temp, surf_rh)
        
        print(f"--- {ts} ---")
        print(f"  Surf: T={surf_temp}C, RH={surf_rh}%, DP={surf_dew:.1f}C")
        print(f"  SWR: {data.get('shortwave_radiation')} W/m2, Sunshine: {data.get('sunshine_duration')}s")
        print(f"  SHF: {data.get('surface_sensible_heat_flux')} W/m2")
        
        therm = calculate_thermal_profile(
            surface_temp=surf_temp,
            surface_dewpoint=surf_dew,
            elevation_m=spot["elevation_m"],
            pressure_levels_data=p_levels,
            boundary_layer_height_agl=data.get("boundary_layer_height"),
            sunshine_duration_s=data.get("sunshine_duration"),
            surface_sensible_heat_flux=data.get("surface_sensible_heat_flux"),
            shortwave_radiation=data.get("shortwave_radiation"),
            direct_radiation=data.get("direct_radiation"),
            diffuse_radiation=data.get("diffuse_radiation"),
            soil_moisture=data.get("soil_moisture_0_to_1cm"),
            timestamp=ts,
            slope_azimuth=spot.get("slope_azimuth"),
            slope_angle=spot.get("slope_angle"),
            low_cloud=data.get("cloud_cover_low", 0),
            mid_cloud=data.get("cloud_cover_mid", 0),
            high_cloud=data.get("cloud_cover_high", 0),
        )

        if "error" in therm:
            print(f"  Error: {therm['error']}")
        else:
            depth = therm['max_height'] - spot['elevation_m']
            print(f"  Climb: {therm['climb_rate']} m/s, Top: {therm['max_height']} m MSL, Depth: {depth}m")
            print(f"  Rating: {therm['rating']}/10")
            if therm.get("data_warnings"):
                for w in therm["data_warnings"]:
                    print(f"  Warning: {w}")

if __name__ == "__main__":
    debug_thermals()
