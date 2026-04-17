"""Inspect the p_level profile for Zentralwallis at peak thermal hour."""
import json
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import thermik_calculator as tc

with open("data/wetterdaten.json", "r", encoding="utf-8") as f:
    cache = json.load(f)

zw = cache["_regions"]["zentralwallis"]
elev = zw["elevation_ref"]  # 2100
plev_data = zw["pressure_level_data"]
hourly = zw["hourly_data"]

ts = "2026-04-07T14:00"
p = plev_data[ts]
h = hourly[ts]

print(f"=== Zentralwallis 2026-04-07T14:00 ===")
print(f"elev_ref:    {elev}m")
print(f"T2m (surf):  {h.get('temperature_2m')} °C")
print(f"SW:          {h.get('shortwave_radiation')} W/m²")
print(f"snow_depth:  {h.get('snow_depth')}m")
print(f"BLH (om):    {h.get('boundary_layer_height')}")
print(f"BLH (gfs):   {h.get('boundary_layer_height_gfs')}")
print(f"RH2m:        {h.get('relative_humidity_2m')}%")
print()
print(f"{'hPa':>6} {'height_m':>10} {'temp_C':>8} {'RH%':>6}")

profile = []
for level in config.PRESSURE_LEVELS:
    hv = p.get(f"geopotential_height_{level}hPa")
    tv = p.get(f"temperature_{level}hPa")
    rh = p.get(f"relative_humidity_{level}hPa")
    if hv is not None and tv is not None:
        profile.append({"pressure": level, "height": hv, "temp": tv})
        print(f"{level:>6} {hv:>10.0f} {tv:>8.2f} {rh if rh is not None else 'n/a':>6}")

print()
# Compute parcel ascent manually
DALR = 9.8 / 1000  # K/m
surface_temp = h["temperature_2m"]
print(f"Parcel starts at {elev}m with T={surface_temp:.2f}°C")
print()
print(f"{'h_msl':>7} {'parcel_T':>10} {'env_T':>8} {'delta':>7}  {'rises?'}")

prev_h = elev
parcel_t = surface_temp
for layer in sorted(profile, key=lambda l: l["height"]):
    h_msl = layer["height"]
    env_t = layer["temp"]
    if h_msl <= elev:
        print(f"{h_msl:>7.0f} {'-':>10} {env_t:>8.2f} {'-':>7}  (below elev_ref)")
        continue
    dh = h_msl - prev_h
    parcel_t -= DALR * dh
    rises = parcel_t > env_t
    delta = parcel_t - env_t
    print(f"{h_msl:>7.0f} {parcel_t:>10.2f} {env_t:>8.2f} {delta:>7.2f}  {rises}")
    if not rises:
        print("  -> PARCEL STOPS HERE (env warmer than parcel)")
        break
    prev_h = h_msl

print()
# Now try with an extra dT (simulate rock-face heating)
for extra_dT in [1.0, 2.0, 3.0, 5.0]:
    print(f"--- With virtual rock-face boost +{extra_dT:.1f}°C ---")
    parcel_t = surface_temp + extra_dT
    prev_h = elev
    max_h_reached = elev
    for layer in sorted(profile, key=lambda l: l["height"]):
        h_msl = layer["height"]
        env_t = layer["temp"]
        if h_msl <= elev:
            continue
        dh = h_msl - prev_h
        parcel_t -= DALR * dh
        if parcel_t > env_t:
            max_h_reached = h_msl
            prev_h = h_msl
        else:
            break
    print(f"  max_h reached: {max_h_reached:.0f}m ({max_h_reached - elev:.0f}m AGL)")
