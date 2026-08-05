"""
Debug: Vergleich unserer Thermik-Berechnung mit XC Therm Daten
für östliches Mittelland, 2. + 3. April 2026.

Zeigt Stunde für Stunde: H, BLH (Encroachment vs Parcel vs Final), climb_rate
um zu verstehen, warum unsere Thermik zu lange dauert.
"""
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from thermik_calculator import (
    calculate_thermal_profile, calculate_dewpoint, _compute_free_atm_gamma
)
import config

DATA_PATH = _ROOT / "data" / "wetterdaten.json"

def load_data():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def run_analysis(spot_name="Balderen"):
    data = load_data()
    spot = data.get(spot_name)
    if not spot:
        print(f"Spot '{spot_name}' nicht gefunden! Verfügbar: {[k for k in data.keys() if k != '_meta']}")
        return

    elevation = spot.get("elevation_m", 730) or 730
    slope_az = spot.get("slope_azimuth")
    slope_ang = spot.get("slope_angle")
    hourly = spot.get("hourly_data", {})
    pressure = spot.get("pressure_level_data", {})

    # Analyse für 2. und 3. April
    for target_date in ["2026-04-02", "2026-04-03"]:
        print(f"\n{'='*120}")
        print(f"  {spot_name} ({elevation}m) — {target_date}")
        print(f"{'='*120}")
        print(f"{'MESZ':>6} | {'T°C':>5} | {'H_est':>5} | {'BLH_enc':>7} | "
              f"{'M_BLH':>6} | {'G_BLH':>6} | {'raw':>6} | {'final':>6} | "
              f"{'Iner':>5} | {'z_i':>5} | {'w*_D':>5} | {'climb':>5} | {'Rat':>3} | Notes")
        print("-" * 120)

        prev_max_h = None
        cumulative_bf = 0.0
        peak_H = 0.0
        peak_sw = 0.0

        times_today = sorted([t for t in hourly.keys() if t.startswith(target_date)])

        for timestamp in times_today:
            h_data = hourly[timestamp]
            p_data = pressure.get(timestamp, {})

            # Pressure levels
            p_levels = []
            for level in config.PRESSURE_LEVELS:
                h_key = f"geopotential_height_{level}hPa"
                t_key = f"temperature_{level}hPa"
                h_val = p_data.get(h_key)
                t_val = p_data.get(t_key)
                if h_val is not None and t_val is not None:
                    p_levels.append({"pressure": level, "height": h_val, "temp": t_val})

            surf_temp = h_data.get("temperature_2m")
            rh = h_data.get("relative_humidity_2m", 50)
            surf_dew = calculate_dewpoint(surf_temp, rh) if surf_temp else None

            if surf_temp is None or not p_levels:
                continue

            therm = calculate_thermal_profile(
                surface_temp=surf_temp,
                surface_dewpoint=surf_dew,
                elevation_m=elevation,
                pressure_levels_data=p_levels,
                boundary_layer_height_agl=h_data.get("boundary_layer_height"),
                sunshine_duration_s=h_data.get("sunshine_duration"),
                surface_sensible_heat_flux=h_data.get("surface_sensible_heat_flux"),
                surface_latent_heat_flux=h_data.get("surface_latent_heat_flux"),
                shortwave_radiation=h_data.get("shortwave_radiation"),
                direct_radiation=h_data.get("direct_radiation"),
                diffuse_radiation=h_data.get("diffuse_radiation"),
                soil_moisture=h_data.get("soil_moisture_0_to_1cm"),
                soil_temperature=h_data.get("soil_temperature_0cm"),
                updraft=h_data.get("updraft"),
                et0=h_data.get("et0_fao_evapotranspiration"),
                vpd=h_data.get("vapour_pressure_deficit"),
                lifted_index=h_data.get("lifted_index"),
                convective_inhibition=h_data.get("convective_inhibition"),
                snow_depth=h_data.get("snow_depth"),
                timestamp=timestamp,
                slope_azimuth=slope_az,
                slope_angle=slope_ang,
                low_cloud=h_data.get("cloud_cover_low", 0),
                mid_cloud=h_data.get("cloud_cover_mid", 0),
                high_cloud=h_data.get("cloud_cover_high", 0),
                boundary_layer_height_gfs=h_data.get("boundary_layer_height_gfs"),
                previous_max_height=prev_max_h,
                cumulative_buoyancy=cumulative_bf,
                peak_H=peak_H,
                peak_shortwave=peak_sw,
            )

            if "error" in therm:
                print(f"{timestamp[11:16]:>6} | ERROR: {therm['error']}")
                continue

            diag = therm.get("diagnostics", {})
            warns = therm.get("data_warnings", [])

            # Extrahiere Schlüsselwerte
            H = diag.get("sensible_heat_flux", 0)
            enc_blh = diag.get("encroachment_blh")
            final_blh = therm["max_height"]
            climb = therm["climb_rate"]
            rating = therm["rating"]
            w_d = diag.get("w_star_deardorff", 0)
            z_i = diag.get("thermal_depth_m", 0)
            cum = diag.get("cumulative_buoyancy", 0)
            gamma = diag.get("gamma_theta", 0)
            buoy_contrib = diag.get("buoyancy_contribution", 0)

            # Inertia-Info aus Warnings extrahieren
            inertia_str = ""
            notes_parts = []
            for w in warns:
                if "Inertia" in w:
                    inertia_str = "INERT"
                    # Extrahiere Rohwert
                    if "Rohwert" in w:
                        try:
                            raw_val = w.split("Rohwert wäre ")[1].split("m")[0]
                            notes_parts.append(f"raw={raw_val}m")
                        except:
                            pass
                if "Encroachment-Cap" in w:
                    notes_parts.append("ENC-CAP")
                if "H geschätzt" in w or "H aus Global" in w:
                    pass  # Normal, nicht anzeigen

            direct = h_data.get("direct_radiation", 0)
            diffuse = h_data.get("diffuse_radiation", 0)
            blh_model = h_data.get("boundary_layer_height")  # ICON-D2 Modell-BLH (AGL)
            blh_gfs_val = h_data.get("boundary_layer_height_gfs")  # GFS Modell-BLH (AGL)
            blh_model_msl = (elevation + blh_model) if blh_model else None
            blh_gfs_msl = (elevation + blh_gfs_val) if blh_gfs_val else None

            enc_str = f"{enc_blh:.0f}" if enc_blh else "  -  "
            blh_m_str = f"{blh_model_msl:.0f}" if blh_model_msl else "   -"
            blh_g_str = f"{blh_gfs_msl:.0f}" if blh_gfs_msl else "   -"
            notes = ", ".join(notes_parts) if notes_parts else ""

            # Parcel raw value aus warnings
            raw_str = ""
            for w in warns:
                if "Rohwert" in w:
                    try:
                        raw_val = w.split("Rohwert wäre ")[1].split("m")[0]
                        raw_str = raw_val
                    except:
                        pass
            if not raw_str:
                raw_str = f"{final_blh:.0f}" if not inertia_str else ""

            hour_str = timestamp[11:16]
            print(f"{hour_str:>6} | {surf_temp:5.1f} | {H:5.0f} | {enc_str:>7} | "
                  f"{blh_m_str:>6} | {blh_g_str:>6} | {raw_str:>6} | {final_blh:>6.0f} | "
                  f"{inertia_str:>5} | {z_i:5.0f} | {w_d:5.2f} | {climb:5.1f} | {rating:>3} | {notes}")

            # State update
            prev_max_h = final_blh
            cumulative_bf += buoy_contrib
            peak_H = max(peak_H, H)
            sw = h_data.get("shortwave_radiation")
            if sw is not None:
                peak_sw = max(peak_sw, sw)


if __name__ == "__main__":
    run_analysis("Balderen")
