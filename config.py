"""
Konfigurationsdatei für Flychat
Adaptiert von uetliberg_ticker/config.py - Multi-Spot, Chat-basiert.
"""

import os
from pathlib import Path

# ============================================================================
# API-KONFIGURATION (Open-Meteo)
# ============================================================================

API_URL = "https://api.open-meteo.com/v1/forecast"
API_MODEL = "meteoswiss_icon_ch1"  # MeteoSwiss ICON CH1 - supports cloud_base
API_TIMEOUT = 30
FORECAST_DAYS = 3
TIMEZONE = "Europe/Zurich"

# ============================================================================
# FLUGSTUNDEN-KONFIGURATION
# ============================================================================

FLIGHT_HOURS_START = 10   # Start-Stunde für Flugstunden (0-23)
FLIGHT_HOURS_END = 17    # End-Stunde für Flugstunden (0-23, exklusiv)

# ============================================================================
# PFAD-KONFIGURATION
# ============================================================================

PROJECT_ROOT = Path(__file__).parent.absolute()
DATA_DIR = PROJECT_ROOT / "data"
CSV_PATH = DATA_DIR / "fluggebiete.csv"
WEATHER_JSON_PATH = DATA_DIR / "wetterdaten.json"

# ============================================================================
# WETTERPARAMETER
# ============================================================================

HOURLY_PARAMS = [
    "temperature_2m",
    "relative_humidity_2m",
    "cloud_base",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "cloud_cover",
    "precipitation",
    "rain",
    "precipitation_probability",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "sunshine_duration",
    "cape",
    "boundary_layer_height",
    "surface_pressure",
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
    "soil_moisture_0_to_1cm",
    "soil_temperature_0cm",
    "updraft",
    "et0_fao_evapotranspiration",
    "vapour_pressure_deficit",
    "snow_depth",
]

# Parameter die via GFS-Supplementary-Call geholt werden (bei icon_seamless oft null)
GFS_SUPPLEMENTARY_PARAMS = [
    "boundary_layer_height",
    "lifted_index",
    "convective_inhibition",
]

# ============================================================================
# HÖHENWIND-PARAMETER (Pressure Level Daten)
# ============================================================================

PRESSURE_LEVELS = [1000, 975, 950, 925, 900, 875, 850, 825, 800, 775, 750, 700, 600]

PRESSURE_LEVEL_PARAMS = []
for _level in PRESSURE_LEVELS:
    PRESSURE_LEVEL_PARAMS.extend([
        f"temperature_{_level}hPa",
        f"relative_humidity_{_level}hPa",
        f"wind_speed_{_level}hPa",
        f"wind_direction_{_level}hPa",
        f"geopotential_height_{_level}hPa"
    ])

# ============================================================================
# THERMIK-BERECHNUNGS-PARAMETER
# ============================================================================

THERMAL_PARAMS = {
    # --- Strahlung → Sensibler Wärmefluss (H) ---
    "direct_radiation_to_H": {
        "winter": 0.22,
        "spring": 0.28,
        "summer": 0.30,
        "autumn": 0.26,
    },
    "diffuse_radiation_to_H": {
        "winter": 0.08,
        "spring": 0.10,
        "summer": 0.14,
        "autumn": 0.11,
    },
    "global_radiation_to_H": {
        "winter": 0.15,
        "spring": 0.18,
        "summer": 0.22,
        "autumn": 0.18,
    },

    # --- H Hard-Cap (W/m²) ---
    "H_cap": {
        "winter": 150,
        "spring": 250,
        "summer": 300,
        "autumn": 200,
    },

    # --- Topografie-Bonus ---
    "topo_bonus_max": 1.4,
    "topo_bonus_H_fraction": 0.4,

    # --- Solare Überhitzung ---
    "solar_excess_max_C": 1.5,
    "solar_excess_H_divisor": 200,

    # --- Entrainment 2. Aufstieg ---
    "second_ascent_entrainment_factor": 0.75,

    # --- Climb-Factor ---
    "climb_factor": 0.50,
    "climb_factor_damping_threshold": 4.0,
    "climb_hard_cap": 4.5,

    # --- DWD-Updraft-Blending ---
    "use_dwd_updraft_blending": True,
    "dwd_updraft_scale": 2.0,

    # --- Terrain-Differenzierung (Mittelland vs. Alpin) ---
    # Höhenschwellen für lineare Interpolation
    "terrain_elev_low": 800,     # Unterhalb: reine Mittelland-Parameter
    "terrain_elev_high": 1800,   # Oberhalb: reine Alpin-Parameter

    # Alpine H-Cap (höher wegen Felswand-Heizung + Talwindsysteme)
    "alpine_H_cap": {
        "winter": 180,
        "spring": 310,
        "summer": 350,
        "autumn": 240,
    },

    # Alpine Entrainment (weniger Einmischung bei organisierten Alpen-Thermiken)
    "alpine_MU": 0.00015,

    # Cumulus-Entrainment-Reduktion über LCL (Morrison et al. 2021:
    # Feuchte Thermiken haben 1.7x kleinere Ausbreitungsraten → weniger Einmischung)
    "moist_entrainment_factor": 0.6,  # MU über LCL wird auf 60% reduziert (= 40% weniger Einmischung)

    # Alpine Schnee-Dämpfung (weniger aggressiv: Mischoberflächen Fels/Schnee)
    "alpine_snow_damping_factor": 0.50,   # Mittelland: 0.20 (80% Reduktion)
    "alpine_snow_H_max": 150,             # Mittelland: 50 W/m²
}

# ============================================================================
# INSTANTDB-KONFIGURATION
# ============================================================================

INSTANTDB_APP_ID = "325047cb-0c83-4630-8573-3e59e6dafe54"
INSTANTDB_ADMIN_TOKEN = os.environ.get("INSTANTDB_ADMIN_TOKEN")
INSTANTDB_API_URL = "https://api.instantdb.com"