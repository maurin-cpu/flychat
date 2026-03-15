import json
from thermik_calculator import calculate_thermal_profile

with open("data/wetterdaten.json", "r", encoding="utf-8") as f:
    data = json.load(f)

spot_name = "Balderen"
if spot_name in data:
    print(f"\n--- {spot_name} am 12.03. (Regtherm-Logic Check) ---")
    hourly = data[spot_name].get("hourly_data", {})
    pl_data = data[spot_name].get("pressure_level_data", {})
    elevation = 730

    for ts in sorted(hourly.keys()):
        if "2026-03-12" in ts:
            time_part = ts.split("T")[1][:5]
            if "10:00" <= time_part <= "16:00":
                val = hourly[ts]
                
                # Re-calculate with new logic to see diagnostics
                p_level_list = []
                pl_hour = pl_data.get(ts, {})
                for level in [1000, 975, 950, 925, 900, 875, 850, 825, 800, 775, 750, 700, 600]:
                    h_val = pl_hour.get(f"geopotential_height_{level}hPa")
                    t_val = pl_hour.get(f"temperature_{level}hPa")
                    if h_val is not None and t_val is not None:
                        p_level_list.append({"pressure": level, "height": h_val, "temp": t_val})

                res = calculate_thermal_profile(
                    surface_temp=val.get("temperature_2m"),
                    surface_dewpoint=val.get("temperature_2m") - 5, # Approx
                    elevation_m=elevation,
                    pressure_levels_data=p_level_list,
                    boundary_layer_height_agl=val.get("boundary_layer_height"),
                    direct_radiation=val.get("direct_radiation"),
                    low_cloud=val.get("cloud_cover_low", 0),
                    mid_cloud=val.get("cloud_cover_mid", 0),
                    high_cloud=val.get("cloud_cover_high", 0),
                    timestamp=ts
                )
                
                diag = res.get("diagnostics", {})
                si = diag.get("sun_index")
                sf = diag.get("sun_factor")
                climb = res.get("climb_rate")
                rating = res.get("rating")
                
                print(f"{time_part} | SunIndex: {si}% | SunFactor: {sf:.3f} | Climb: {climb}m/s | Rating: {rating}/10")
