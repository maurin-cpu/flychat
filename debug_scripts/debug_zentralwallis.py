"""Debug why Zentralwallis shows climb_rate=0 per hour despite all 6 calibration steps.

Uses the same call signature as web.py::format_data_for_charts.
"""
import json
import sys
import os
import io
from datetime import datetime

# Force utf-8 output so Umlauts and arrows survive on Windows cp1252
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import thermik_calculator as tc
from thermik_calculator import calculate_thermal_profile, calculate_dewpoint


def run_region(region_id_key, target_day=None):
    cache_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "wetterdaten.json",
    )
    with open(cache_path, "r", encoding="utf-8") as f:
        cache = json.load(f)

    region = cache["_regions"].get(region_id_key)
    if not region:
        print(f"ERROR: {region_id_key} not in cache")
        return

    elev_ref = region.get("elevation_ref")
    zone = tc.get_terrain_zone(elev_ref, region_id=None)
    print(f"\n=== {region_id_key} (elev_ref={elev_ref}, zone={zone}) ===")

    hourly = region.get("hourly_data", {})
    pressure = region.get("pressure_level_data", {})

    sorted_ts = sorted(hourly.keys())
    if target_day is None:
        target_day = sorted_ts[0][:10]
    day_ts = [t for t in sorted_ts if t.startswith(target_day)]

    # Day-state trackers (same as web.py)
    prev_max_h = None
    cumulative_bf = 0.0
    peak_H = 0.0
    peak_sw = 0.0

    print(f"Target day: {target_day}, hours: {len(day_ts)}")
    print(f"{'Time':<19} {'T2m':>5} {'SW':>6} {'snow':>5} {'H_sfc':>7} {'BLH':>5} {'rating':>6} {'climb':>6} {'max_h':>6}  warnings")

    for ts in day_ts:
        data = hourly[ts]

        # Build p_levels like web.py
        p_levels = []
        if ts in pressure:
            for level in config.PRESSURE_LEVELS:
                h_val = pressure[ts].get(f"geopotential_height_{level}hPa")
                t_val = pressure[ts].get(f"temperature_{level}hPa")
                if h_val is not None and t_val is not None:
                    p_levels.append({"pressure": level, "height": h_val, "temp": t_val})

        surf_temp = data.get("temperature_2m")
        surf_dew = calculate_dewpoint(surf_temp, data.get("relative_humidity_2m", 50))

        if surf_temp is None or not p_levels:
            continue

        therm = calculate_thermal_profile(
            surface_temp=surf_temp,
            surface_dewpoint=surf_dew,
            elevation_m=elev_ref,
            pressure_levels_data=p_levels,
            boundary_layer_height_agl=data.get("boundary_layer_height"),
            sunshine_duration_s=data.get("sunshine_duration"),
            surface_sensible_heat_flux=data.get("surface_sensible_heat_flux"),
            surface_latent_heat_flux=data.get("surface_latent_heat_flux"),
            shortwave_radiation=data.get("shortwave_radiation"),
            direct_radiation=data.get("direct_radiation"),
            diffuse_radiation=data.get("diffuse_radiation"),
            soil_moisture=data.get("soil_moisture_0_to_1cm"),
            soil_temperature=data.get("soil_temperature_0cm"),
            updraft=data.get("updraft"),
            et0=data.get("et0_fao_evapotranspiration"),
            vpd=data.get("vapour_pressure_deficit"),
            lifted_index=data.get("lifted_index"),
            convective_inhibition=data.get("convective_inhibition"),
            snow_depth=data.get("snow_depth"),
            timestamp=ts,
            low_cloud=data.get("cloud_cover_low", 0),
            mid_cloud=data.get("cloud_cover_mid", 0),
            high_cloud=data.get("cloud_cover_high", 0),
            boundary_layer_height_gfs=data.get("boundary_layer_height_gfs"),
            previous_max_height=prev_max_h,
            cumulative_buoyancy=cumulative_bf,
            peak_H=peak_H,
            peak_shortwave=peak_sw,
        )

        if "error" in therm:
            continue

        climb = therm.get("climb_rate", 0)
        rating = therm.get("rating", 0)
        max_h = therm.get("max_height", 0) or 0
        diag = therm.get("diagnostics", {})
        warnings = therm.get("data_warnings", [])
        prev_max_h = max_h if max_h else prev_max_h
        cumulative_bf += diag.get("buoyancy_contribution", 0)
        H_sfc = diag.get("sensible_heat_flux", 0)
        peak_H = max(peak_H, H_sfc)
        sw = data.get("shortwave_radiation") or 0
        peak_sw = max(peak_sw, sw)

        snow = data.get("snow_depth") or 0
        blh = data.get("boundary_layer_height")
        blh_str = f"{blh:.0f}" if blh is not None else "None"

        print(f"{ts:<19} {surf_temp:>5.1f} {sw:>6.0f} {snow:>5.2f} "
              f"{H_sfc:>7.1f} {blh_str:>5} {rating:>6} {climb:>6.2f} "
              f"{max_h:>6.0f}  {','.join(warnings) if warnings else ''}")


def main():
    # Today = first day in cache
    run_region("zentralwallis")
    print()
    run_region("berner_oberland")
    print()
    run_region("mittelland_ost")


if __name__ == "__main__":
    main()
