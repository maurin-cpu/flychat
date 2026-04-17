"""Patch: Fill missing region pressure-level data from nearest spot data.

The thermal batch for regions only fetches temperature_XhPa but not
geopotential_height/wind_speed/wind_direction on pressure levels.
This script patches the cached JSON by copying PL data from the nearest spot
that has valid data for the same timestamps.
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

cache_path = config.WEATHER_JSON_PATH
print(f"Loading cache: {cache_path}")
with open(cache_path, "r", encoding="utf-8") as f:
    data = json.load(f)

regions = data.get("_regions", {})
spots = {k: v for k, v in data.items() if k not in ("_meta", "_regions")}

if not regions:
    print("No regions in cache!")
    sys.exit(1)

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

# PL params that come from wind batch (missing in thermal batch for regions)
wind_pl_params = [p for p in config.PRESSURE_LEVEL_PARAMS
                  if p.startswith("wind_speed_") or p.startswith("wind_direction_") or p.startswith("geopotential_height_")]

patched_regions = 0
patched_timestamps = 0

for rid, rdata in regions.items():
    pl = rdata.get("pressure_level_data", {})
    if not pl:
        continue

    # Find timestamps with missing PL data
    missing_timestamps = []
    for ts, pdata in pl.items():
        has_geo = any(pdata.get(f"geopotential_height_{lv}hPa") is not None for lv in config.PRESSURE_LEVELS)
        if not has_geo:
            missing_timestamps.append(ts)

    if not missing_timestamps:
        continue

    # Find nearest spot with valid PL data
    rlat = rdata.get("latitude", 0)
    rlon = rdata.get("longitude", 0)
    # Use reference points if no lat/lon
    refs = rdata.get("reference_points", [])
    if (rlat == 0 or rlon == 0) and refs:
        rlat, rlon = refs[0][0], refs[0][1]

    best_spot = None
    best_dist = float("inf")
    for sname, sdata in spots.items():
        dist = haversine_km(rlat, rlon, sdata.get("latitude", 0), sdata.get("longitude", 0))
        # Check if this spot has valid PL data for missing timestamps
        s_pl = sdata.get("pressure_level_data", {})
        if missing_timestamps[0] in s_pl:
            test_data = s_pl[missing_timestamps[0]]
            has_geo = any(test_data.get(f"geopotential_height_{lv}hPa") is not None for lv in config.PRESSURE_LEVELS)
            if has_geo and dist < best_dist:
                best_dist = dist
                best_spot = sname

    if not best_spot:
        print(f"  {rid}: No nearby spot with valid PL data!")
        continue

    spot_pl = spots[best_spot]["pressure_level_data"]
    count = 0
    for ts in missing_timestamps:
        if ts not in spot_pl:
            continue
        spot_entry = spot_pl[ts]
        for param in wind_pl_params:
            val = spot_entry.get(param)
            if val is not None and pl[ts].get(param) is None:
                pl[ts][param] = val
                count += 1

    if count > 0:
        patched_timestamps += len(missing_timestamps)
        patched_regions += 1
        print(f"  {rid}: patched {len(missing_timestamps)} timestamps from {best_spot} ({best_dist:.0f}km), {count} values filled")

print(f"\nTotal: {patched_regions} regions, {patched_timestamps} timestamps patched")

if patched_regions > 0:
    print(f"Saving to {cache_path}...")
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print("Done! Restart the server to load the patched cache.")
else:
    print("No patches needed.")
