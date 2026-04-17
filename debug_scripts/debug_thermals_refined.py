import json
import sys
import os
from datetime import datetime

# Set Python path to include current directory
sys.path.append(os.getcwd())

from thermik_calculator import calculate_thermal_profile, calculate_dewpoint
import config
from spots import load_spots, get_spot_by_name

def debug_thermals(spot_name, target_date):
    spots = load_spots()
    spot = get_spot_by_name(spots, spot_name)
    if not spot:
        print(f"Error: Spot '{spot_name}' not found")
        return

    print(f"=== Thermal Debug: {spot['name']} ===")
    print(f"Launch Elevation: {spot['elevation_m']}m MSL")

    # Load weather data
    if not config.WEATHER_JSON_PATH.exists():
        print(f"Error: Weather data not found at {config.WEATHER_JSON_PATH}")
        return

    with open(config.WEATHER_JSON_PATH, "r", encoding="utf-8") as f:
        all_weather = json.load(f)

    spot_weather = all_weather.get(spot["name"])
    if not spot_weather:
        print(f"Error: No weather data for {spot['name']}")
        return

    hourly_data = spot_weather.get("hourly_data", {})
    pressure_level_data = spot_weather.get("pressure_level_data", {})

    print(f"Analyzing date: {target_date}")
    print("-" * 60)

    sorted_times = sorted(hourly_data.keys())
    found = False
    for ts in sorted_times:
        if not ts.startswith(target_date):
            continue
        
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        # Focus on typical flying hours
        if not (9 <= dt.hour <= 18):
            continue

        found = True
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

        time_str = ts.split("T")[1][:5]
        if "error" in therm:
            print(f"{time_str} | Error: {therm['error']}")
        else:
            climb = therm.get('climb_rate', 0)
            top = therm.get('max_height', 0)
            rating = therm.get('rating', 0)
            print(f"{time_str} | Rating: {rating}/10 | Climb: {climb:.1f} m/s | Top: {top}m MSL")
            if 'diagnostics' in therm:
                d = therm['diagnostics']
                print(f"      [Diag] H_flux: {d.get('H_sensible_flux',0):.1f} W/m2 | SunIdx: {therm.get('sun_index',0):.1f}%")

    if not found:
        print(f"No data found for date {target_date}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Deep debug thermal profiles")
    parser.add_argument("--spot", type=str, default="Balderen", help="Spot name")
    parser.add_argument("--date", type=str, help="Date (YYYY-MM-DD), defaults to today", default=datetime.now().strftime("%Y-%m-%d"))
    args = parser.parse_args()
    
    debug_thermals(args.spot, args.date)
