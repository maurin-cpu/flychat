"""Test the rock-face fix across all snowy alpine regions.

Shows peak thermal climb and max altitude for the busiest hour (13:00) of each
voralpen/alpen/hochalpin region. Compares regions with snow cover (where the
fix activates) vs. snow-free.
"""
import json
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import thermik_calculator as tc
from thermik_calculator import calculate_thermal_profile, calculate_dewpoint


def calc_day(region_id_key, region_data, target_day):
    """Compute peak hour metrics for one region/day."""
    elev = region_data["elevation_ref"]
    zone = tc.get_terrain_zone(elev, region_id=None)
    hourly = region_data["hourly_data"]
    pressure = region_data["pressure_level_data"]

    sorted_ts = sorted(hourly.keys())
    day_ts = [t for t in sorted_ts if t.startswith(target_day)]

    prev_max_h = None
    cumulative_bf = 0.0
    peak_H = 0.0
    peak_sw = 0.0

    peak_climb = 0.0
    peak_climb_hour = ""
    peak_max_h = 0
    peak_rating = 0
    snow_seen = 0.0
    rock_face_active = False

    for ts in day_ts:
        data = hourly[ts]

        p_levels = []
        if ts in pressure:
            for level in config.PRESSURE_LEVELS:
                h_val = pressure[ts].get(f"geopotential_height_{level}hPa")
                t_val = pressure[ts].get(f"temperature_{level}hPa")
                if h_val is not None and t_val is not None:
                    p_levels.append({"pressure": level, "height": h_val, "temp": t_val})

        surf_temp = data.get("temperature_2m")
        if surf_temp is None or not p_levels:
            continue

        snow = data.get("snow_depth") or 0
        if snow > snow_seen:
            snow_seen = snow

        therm = calculate_thermal_profile(
            surface_temp=surf_temp,
            surface_dewpoint=calculate_dewpoint(surf_temp, data.get("relative_humidity_2m", 50)),
            elevation_m=elev,
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
            snow_depth=snow,
            timestamp=ts,
            low_cloud=data.get("cloud_cover_low", 0),
            mid_cloud=data.get("cloud_cover_mid", 0),
            high_cloud=data.get("cloud_cover_high", 0),
            previous_max_height=prev_max_h,
            cumulative_buoyancy=cumulative_bf,
            peak_H=peak_H,
            peak_shortwave=peak_sw,
        )

        if "error" in therm:
            continue

        climb = therm.get("climb_rate", 0) or 0
        rating = therm.get("rating", 0) or 0
        max_h = therm.get("max_height", 0) or 0
        diag = therm.get("diagnostics", {})
        warnings = therm.get("data_warnings", []) or []
        prev_max_h = max_h if max_h else prev_max_h
        cumulative_bf += diag.get("buoyancy_contribution", 0)
        peak_H = max(peak_H, diag.get("sensible_heat_flux", 0))
        peak_sw = max(peak_sw, data.get("shortwave_radiation") or 0)

        if any("Rock-Face" in w for w in warnings):
            rock_face_active = True

        if climb > peak_climb:
            peak_climb = climb
            peak_climb_hour = ts[-5:]
            peak_max_h = max_h
            peak_rating = rating

    return {
        "zone": zone,
        "elev": elev,
        "snow": snow_seen,
        "peak_climb": peak_climb,
        "peak_hour": peak_climb_hour,
        "peak_max_h": peak_max_h,
        "peak_rating": peak_rating,
        "peak_agl": peak_max_h - elev if peak_max_h else 0,
        "rock_face": rock_face_active,
    }


def main():
    cache_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "wetterdaten.json",
    )
    with open(cache_path, "r", encoding="utf-8") as f:
        cache = json.load(f)

    regions = cache.get("_regions", {})
    target = "2026-04-07"

    print(f"=== Peak thermals 2026-04-07 (alle Regionen, sortiert nach Zone+Schnee) ===\n")
    print(f"{'Region':<26} {'Zone':<11} {'elev':>5} {'snow':>5} "
          f"{'peak':>5} {'rating':>6} {'h_msl':>6} {'AGL':>5} {'time':>6} {'rock?'}")
    print("-" * 100)

    rows = []
    for rid, rdata in regions.items():
        try:
            r = calc_day(rid, rdata, target)
            r["id"] = rid
            rows.append(r)
        except Exception as e:
            print(f"FAIL {rid}: {e}")

    # Sort: zone order, then snow desc
    zone_order = {"mittelland": 0, "jura": 1, "voralpen": 2, "alpen": 3, "hochalpin": 4}
    rows.sort(key=lambda r: (zone_order.get(r["zone"], 99), -r["snow"]))

    for r in rows:
        rock = "YES" if r["rock_face"] else "no"
        print(f"{r['id'][:25]:<26} {r['zone']:<11} {r['elev']:>5} {r['snow']:>5.2f} "
              f"{r['peak_climb']:>5.2f} {r['peak_rating']:>6} {r['peak_max_h']:>6.0f} "
              f"{r['peak_agl']:>5.0f} {r['peak_hour']:>6}  {rock}")

    print()
    print("Zone summary:")
    for zone in ["mittelland", "jura", "voralpen", "alpen", "hochalpin"]:
        zr = [r for r in rows if r["zone"] == zone]
        if not zr:
            continue
        snowy = [r for r in zr if r["snow"] > 0.05]
        rocked = [r for r in zr if r["rock_face"]]
        print(f"  {zone:<11}: {len(zr):>2} regions, {len(snowy):>2} schneebedeckt, "
              f"{len(rocked):>2} mit Rock-Face Branch aktiv")


if __name__ == "__main__":
    main()
