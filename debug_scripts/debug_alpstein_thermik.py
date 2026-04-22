"""
Debug: Welche Caps druecken das Thermik-Top fuer Alpstein 24.04.?
Zeigt data_warnings der Thermik-Berechnung.
"""
import sys, os, io
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from chat_engine import GleitcastEngine

engine = GleitcastEngine()
engine.load_weather_from_cache()

rwd = engine.region_weather_data
if "alpstein" not in rwd:
    print("alpstein nicht geladen")
    sys.exit(1)

alp = rwd["alpstein"]
print(f"Keys: {list(alp.keys())}")

from thermik_calculator import calculate_thermal_profile, calculate_dewpoint
import config

hourly = alp.get("hourly_data", {})
pl_all = alp.get("pressure_level_data", {})
elev = alp.get("elevation_ref", 1640)
target_day = os.environ.get("TARGET_DAY", "2026-04-24")

prev_max_h = None
cumulative_bf = 0.0
peak_H = 0.0
peak_sw = 0.0

for ts in sorted(hourly.keys()):
    if not ts.startswith(target_day):
        continue
    h_str = ts.split("T")[1] if "T" in ts else ts
    hour_int = int(h_str.split(":")[0])
    if hour_int < 6 or hour_int > 18:
        continue
    data = hourly[ts]
    pl_data = pl_all.get(ts, {})
    p_levels = []
    for lvl in config.PRESSURE_LEVELS:
        hv = pl_data.get(f"geopotential_height_{lvl}hPa")
        tv = pl_data.get(f"temperature_{lvl}hPa")
        if hv is not None and tv is not None:
            p_levels.append({"pressure": lvl, "height": hv, "temp": tv})
    dew = calculate_dewpoint(data.get("temperature_2m"), data.get("relative_humidity_2m", 50))
    try:
        therm = calculate_thermal_profile(
            surface_temp=data.get("temperature_2m"),
            surface_dewpoint=dew,
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
            region_id="alpstein",
        )
    except Exception as e:
        print(f"{ts}: FEHLER {e}")
        continue

    climb = therm.get("climb_rate")
    mh = therm.get("max_height")
    lcl = therm.get("lcl")
    gfs = data.get("boundary_layer_height_gfs")
    gfs2 = data.get("boundary_layer_height")
    sw = therm.get("shortwave_radiation") or data.get("shortwave_radiation")
    H = therm.get("H_input") or therm.get("sensible_heat_flux")
    warnings = therm.get("data_warnings") or []
    print(f"\n=== {ts} === elev={elev}m")
    print(f"  climb       : {climb} m/s")
    print(f"  max_height  : {mh} m MSL  (band={mh-elev if mh else 0}m AGL)")
    print(f"  lcl         : {lcl} m MSL  (lcl-elev={lcl-elev if lcl else 0}m)")
    print(f"  BLH_GFS     : {gfs}  (boundary_layer_height={gfs2})")
    print(f"  H           : {H}  SW={sw}")
    print(f"  T/RH(2m)    : {data.get('temperature_2m')}°C  RH={data.get('relative_humidity_2m')}%  dew={dew:.1f}°C")
    print(f"  PL-Profil (Geopot/Temp):")
    for lvl in config.PRESSURE_LEVELS:
        hv = pl_data.get(f"geopotential_height_{lvl}hPa")
        tv = pl_data.get(f"temperature_{lvl}hPa")
        if hv is not None and tv is not None and hv > elev - 200 and hv < elev + 3500:
            print(f"    {lvl}hPa: h={hv:.0f}m  T={tv:.1f}°C")
    if warnings:
        for w in warnings:
            print(f"    ! {w}")

    # Update running state for next hour
    prev_max_h = mh
    if H and H > 0:
        cumulative_bf += (H / (1.2 * 1005)) * 3600
    if H and H > peak_H:
        peak_H = H
    if sw and sw > peak_sw:
        peak_sw = sw
