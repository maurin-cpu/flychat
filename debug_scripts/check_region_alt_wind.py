"""Debug: Why does region altitude-wind API return no data for today?"""
import json
import sys
import os
import traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
import config

cache_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "wetterdaten.json")
with open(cache_path, "r", encoding="utf-8") as f:
    data = json.load(f)

regions = data.get("_regions", {})
region_id = "zentralschweizer_voralpen"
region_data = regions.get(region_id, {})

if not region_data:
    print(f"Region '{region_id}' nicht gefunden!")
    print(f"Verfuegbare Regionen: {list(regions.keys())[:5]}...")
    sys.exit(1)

pressure_level_data = region_data.get("pressure_level_data", {})
hourly_data = region_data.get("hourly_data", {})
elevation_ref = region_data.get("elevation_ref", 1200)

print(f"Region: {region_id}, elevation_ref: {elevation_ref}")
print(f"PL timestamps: {len(pressure_level_data)}")
print(f"Hourly timestamps: {len(hourly_data)}")

# Check which dates exist in PL data
pl_dates = set()
for ts in pressure_level_data.keys():
    pl_dates.add(ts[:10])
print(f"PL dates: {sorted(pl_dates)}")

# Check today's PL data
today_ts = [ts for ts in sorted(pressure_level_data.keys()) if ts.startswith("2026-04-12")]
print(f"\nToday PL timestamps: {len(today_ts)}")
if today_ts:
    first_ts = today_ts[0]
    first_data = pressure_level_data[first_ts]
    geo_keys = [k for k in first_data.keys() if "geopotential" in k]
    print(f"  Geopotential heights: {len(geo_keys)}")
    non_null_geo = sum(1 for k in geo_keys if first_data[k] is not None)
    print(f"  Non-null geopotential: {non_null_geo}")
    wind_keys = [k for k in first_data.keys() if "wind_speed" in k and "hPa" in k]
    non_null_wind = sum(1 for k in wind_keys if first_data[k] is not None)
    print(f"  Non-null wind speed: {non_null_wind}/{len(wind_keys)}")

# Now try calling format_altitude_wind_for_charts with error tracing
print("\n=== Testing format_altitude_wind_for_charts ===")
from web import format_altitude_wind_for_charts

# First: simple call without anchors
print("\n--- Without anchors ---")
alt_data = format_altitude_wind_for_charts(pressure_level_data, hourly_data, elevation_ref, region_id)
profiles = alt_data.get("profiles", [])
print(f"Profiles: {len(profiles)}")

profile_dates = set()
for p in profiles:
    profile_dates.add(p["time"][:10])
print(f"Profile dates: {sorted(profile_dates)}")

today_profiles = [p for p in profiles if p["time"].startswith("2026-04-12")]
print(f"Today profiles: {len(today_profiles)}")

# Now: with surface anchors (like the real endpoint does)
print("\n--- With surface anchors ---")
surface_anchor_by_time = {}
for timestamp, hour_data in hourly_data.items():
    gust = hour_data.get("wind_gusts_10m")
    ws = hour_data.get("wind_speed_10m")
    if gust is not None and ws is not None:
        surface_anchor_by_time[timestamp] = {
            "elevation_m": elevation_ref,
            "gust_kmh": float(gust),
            "wind_speed_kmh": float(ws),
        }
print(f"Surface anchors: {len(surface_anchor_by_time)}")

alt_data2 = format_altitude_wind_for_charts(
    pressure_level_data, hourly_data, elevation_ref, region_id,
    surface_anchor_by_time=surface_anchor_by_time,
)
profiles2 = alt_data2.get("profiles", [])
print(f"Profiles with anchors: {len(profiles2)}")

profile_dates2 = set()
for p in profiles2:
    profile_dates2.add(p["time"][:10])
print(f"Profile dates with anchors: {sorted(profile_dates2)}")

today_profiles2 = [p for p in profiles2 if p["time"].startswith("2026-04-12")]
print(f"Today profiles with anchors: {len(today_profiles2)}")

# If still no today profiles, debug individual timestamps
if len(today_profiles2) == 0:
    print("\n=== Debugging individual timestamps ===")
    for ts in today_ts[:3]:
        print(f"\n  Timestamp: {ts}")
        pdata = pressure_level_data[ts]
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            profile = {"time": dt.isoformat(), "levels": []}
            for level in config.PRESSURE_LEVELS:
                height = pdata.get(f"geopotential_height_{level}hPa")
                wind_speed = pdata.get(f"wind_speed_{level}hPa")
                wind_direction = pdata.get(f"wind_direction_{level}hPa")
                temperature = pdata.get(f"temperature_{level}hPa")
                if height is not None:
                    profile["levels"].append({
                        "pressure": level,
                        "altitude": height,
                        "wind_speed": wind_speed if wind_speed is not None else 0.0,
                        "wind_direction": wind_direction if wind_direction is not None else 0,
                        "temperature": temperature if temperature is not None else 0,
                    })
            print(f"  Levels: {len(profile['levels'])}")

            # Try estimate_altitude_gusts
            from gust_calculator import estimate_altitude_gusts
            surface = hourly_data.get(ts, {})
            print(f"  Surface wind: {surface.get('wind_speed_10m')}, gusts: {surface.get('wind_gusts_10m')}, BLH: {surface.get('boundary_layer_height')}")

            try:
                result = estimate_altitude_gusts(
                    wind_speed_10m=surface.get("wind_speed_10m"),
                    wind_gusts_10m=surface.get("wind_gusts_10m"),
                    pressure_levels_data=profile["levels"],
                    elevation_m=elevation_ref,
                    boundary_layer_height=surface.get("boundary_layer_height"),
                    region_id=region_id,
                )
                print(f"  estimate_altitude_gusts OK: {len(result)} levels")
            except Exception as e:
                print(f"  estimate_altitude_gusts FAILED: {e}")
                traceback.print_exc()

            # Try _oi_gust_correction path
            anchor = surface_anchor_by_time.get(ts)
            if anchor and profile["levels"]:
                print(f"  Surface anchor: elevation={anchor['elevation_m']}, gust={anchor['gust_kmh']}")
                try:
                    from web import _interp_ws, _interp_scalar, _oi_gust_correction
                    from gust_calculator import get_oi_scale_lengths, get_effective_L_up

                    levels = sorted(profile["levels"], key=lambda l: l["altitude"])
                    ws_pts = [(lv["altitude"], lv.get("wind_speed", 0), lv.get("wind_direction", 0), lv.get("temperature", 0)) for lv in levels]
                    gust_pts = sorted([(lv["altitude"], lv.get("wind_gusts", lv.get("wind_speed", 0))) for lv in levels], key=lambda x: x[0])

                    GRID_STEP = 250
                    GRID_MAX = 4000
                    grid_alts = list(range(0, GRID_MAX + 1, GRID_STEP))
                    print(f"  Grid alts: {grid_alts[:5]}...")

                    grid_gusts_bg = [_interp_scalar(gust_pts, a) for a in grid_alts]
                    grid_ws = []
                    grid_dir = []
                    grid_temp = []
                    for a in grid_alts:
                        ws_val, dir_val, temp_val = _interp_ws(ws_pts, a)
                        grid_ws.append(ws_val)
                        grid_dir.append(dir_val)
                        grid_temp.append(temp_val)

                    elev_anchor = anchor["elevation_m"]
                    ws_free_atm = _interp_scalar([(p[0], p[1]) for p in ws_pts], elev_anchor)
                    oi_anchors = [{
                        "elevation_m": elev_anchor,
                        "gust_kmh": anchor["gust_kmh"],
                        "wind_speed_kmh": ws_free_atm,
                    }]

                    _, L_down = get_oi_scale_lengths(elev_anchor, region_id)
                    blh = surface.get("boundary_layer_height") or surface.get("boundary_layer_height_gfs") or 0
                    L_up = get_effective_L_up(elev_anchor, region_id, blh)
                    print(f"  L_up={L_up}, L_down={L_down}, BLH={blh}")

                    grid_gusts_oi = _oi_gust_correction(grid_alts, grid_gusts_bg, grid_ws, oi_anchors, L_up, L_down)
                    print(f"  OI correction OK: {len(grid_gusts_oi)} points")

                except Exception as e:
                    print(f"  OI correction FAILED: {e}")
                    traceback.print_exc()

        except Exception as e:
            print(f"  FAILED: {e}")
            traceback.print_exc()
