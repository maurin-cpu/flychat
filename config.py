"""
Konfigurationsdatei für Gleitcast
Adaptiert von uetliberg_ticker/config.py - Multi-Spot, Chat-basiert.
"""

import atexit
import json
import logging
import os
import queue
import tempfile
import threading
from pathlib import Path

# .env so früh wie möglich laden, damit alle Importer (auch web.py, das nicht
# selbst load_dotenv aufruft) Zugriff auf Secrets wie OPENMETEO_API_KEY haben.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv optional

# ============================================================================
# API-KONFIGURATION (Open-Meteo)
# ============================================================================

# Open-Meteo API Key (optional). Wenn gesetzt → Customer API mit höheren Limits
# (5 Mio. Calls/Monat statt 10k/Tag im Free Tier).
OPENMETEO_API_KEY = os.environ.get("OPENMETEO_API_KEY", "").strip()

if OPENMETEO_API_KEY:
    API_URL = "https://customer-api.open-meteo.com/v1/forecast"
else:
    API_URL = "https://api.open-meteo.com/v1/forecast"


def with_api_key(params):
    """
    Helper: Injiziert apikey in das Open-Meteo Request-Params Dict, falls
    OPENMETEO_API_KEY gesetzt ist. Mutiert das Dict in-place und gibt es zurück.
    """
    if OPENMETEO_API_KEY:
        params["apikey"] = OPENMETEO_API_KEY
    return params

# Wettermodell-Hybrid:
# - WIND_MODEL: Wind/Böen/Leewarnungen -> lokal präziser (CH1)
# - THERMAL_MODEL: Thermik/Wolken/Strahlung -> robuster für Fliegbarkeit (ICON-D2)
WIND_MODEL = "meteoswiss_icon_ch1" #meteoswiss_icon_ch1, icon_d2, icon_eu
THERMAL_MODEL = "icon_d2"
FALLBACK_MODEL = "icon_eu"

# Multi-Modell Böenvergleich: MeteoSwiss ICON-CH1 (1km) und ICON-CH2 (2km)
CH1_MODEL = "meteoswiss_icon_ch1"
CH2_MODEL = "meteoswiss_icon_ch2"
CH_SURFACE_PARAMS = ["wind_speed_10m", "wind_direction_10m", "wind_gusts_10m"]
CH1_FORECAST_DAYS = 2  # CH1 hat nur ~33h Horizont
CH2_FORECAST_DAYS = 5  # CH2 hat 5 Tage Horizont

# Rückwärtskompatibilität für ältere Skripte
API_MODEL = WIND_MODEL

API_TIMEOUT = 30
FORECAST_DAYS = 5
# Vorhersage-Zeitachse: Wanduhrzeit Schweiz (MESZ/MEZ). Open-Meteo liefert `time` in dieser Zone.
TIMEZONE = "Europe/Zurich"

# Referenzpunkte auf der Karte anzeigen (Linien vom Startplatz zu den
# regionalen Thermik-Referenzpunkten beim Hover). False = ausgeblendet.
SHOW_REFERENCE_POINTS = False

# ============================================================================
# FLUGSTUNDEN-KONFIGURATION
# ============================================================================

FLIGHT_HOURS_START = 6    # Start-Stunde für Flugstunden (0-23)
FLIGHT_HOURS_END = 18    # End-Stunde für Flugstunden (0-23, exklusiv)

# ============================================================================
# WINDRICHTUNGS-TOLERANZ
# ============================================================================
# Erlaubte Abweichung der Windrichtung vom Startplatz-Sektor, als Prozent
# der Sektorbreite. Wird symmetrisch an beide Sektor-Enden angehängt.
# Beispiel: Sektor N-W (= 270°–360°, Breite 90°) + 10% → ±9° Puffer
#           → effektiv erlaubt von 261° bis 9°.
# 0.0 = strikt (nur innerhalb des deklarierten Sektors).
WIND_DIRECTION_TOLERANCE_PCT = 0.10

# ============================================================================
# PFAD-KONFIGURATION
# ============================================================================

PROJECT_ROOT = Path(__file__).parent.absolute()
DATA_DIR = PROJECT_ROOT / "data"

# Spot-CSV: "complete" = alle ~490 Startplätze, "test" = reduziertes Set für Entwicklung
# Umschalten: USE_SPOT_CSV = "test" oder "complete"
USE_SPOT_CSV = os.environ.get("GLEITCAST_SPOT_CSV", "complete")  # "complete" | "test"
CSV_PATH = DATA_DIR / f"fluggebiete_{USE_SPOT_CSV}.csv"
REGIONEN_GEOJSON_PATH = DATA_DIR / "regionen_referenzpunkte.geojson"
# Master-File fuer Region-Properties (Name, terrain_type, elevation_ref,
# kritischer_foehn, description). Geometrie + reference_points kommen aus
# der GeoJSON, alle textuellen Felder aus dieser CSV.
REGIONEN_CSV_PATH = DATA_DIR / "regionen.csv"

# Vercel: Nur /tmp ist schreibbar. Readonly-Daten (CSV, GeoJSON) bleiben in data/
if os.environ.get("VERCEL"):
    _WRITABLE_DIR = Path("/tmp/gleitcast")
    _WRITABLE_DIR.mkdir(parents=True, exist_ok=True)
    WEATHER_JSON_PATH = _WRITABLE_DIR / "wetterdaten.json"
    HISTORY_DIR = _WRITABLE_DIR / "history"
    STATION_DB_PATH = _WRITABLE_DIR / "station_observations.db"
    SUBSCRIBERS_DB_PATH = _WRITABLE_DIR / "subscribers.db"
    FEEDBACK_DB_PATH = _WRITABLE_DIR / "feedback.db"
else:
    WEATHER_JSON_PATH = DATA_DIR / "wetterdaten.json"
    HISTORY_DIR = DATA_DIR / "history"
    STATION_DB_PATH = DATA_DIR / "station_observations.db"
    SUBSCRIBERS_DB_PATH = DATA_DIR / "subscribers.db"
    FEEDBACK_DB_PATH = DATA_DIR / "feedback.db"

# ============================================================================
# SPOT SOURCE AREAS (manuelle Overrides fuer Referenzpunkte)
# ============================================================================
# Pro Spot koennen 4 regionale Referenzpunkte [lat, lon] definiert werden.
# Der Startplatz selbst wird automatisch als Punkt 1 hinzugefuegt.
# Spots ohne Eintrag nutzen die Punkte aus dem Regionen-GeoJSON.

SPOT_SOURCE_AREAS = {
    "Balderen": [
        [47.4150, 8.5900],   # Noerdlich (Altstetten/Hoengg)
        [47.2500, 8.7500],   # Sued-Oestlich (Meilen/Zuerichsee)
        [47.4300, 8.4700],   # Westlich (Dietikon/Schlieren)
        [47.1600, 8.6600],   # Suedlich (Horgen/Zugersee)
    ],
}

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
    "weather_code",  # WMO: 95/96/99 = Gewitter
]

# Parameter die via GFS-Supplementary-Call geholt werden (bei icon_seamless oft null)
GFS_SUPPLEMENTARY_PARAMS = [
    "lifted_index",
    "convective_inhibition",
]

# Parameter für den Cross-Check (werden als {param}_gfs gespeichert)
GFS_CROSSCHECK_PARAMS = [
    "boundary_layer_height",
]

# ============================================================================
# HÖHENWIND-PARAMETER (Pressure Level Daten)
# ============================================================================

PRESSURE_LEVELS = [1000, 975, 950, 925, 900, 875, 850, 825, 800, 775, 750, 700, 600]

PRESSURE_LEVEL_PARAMS = []
for _level in PRESSURE_LEVELS:
    PRESSURE_LEVEL_PARAMS.extend([
        f"temperature_{_level}hPa",
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
    "topo_bonus_max": 1.45,
    "topo_bonus_H_fraction": 0.4,

    # --- Solare Überhitzung ---
    "solar_excess_max_C": 2.5,
    "solar_excess_H_divisor": 100,

    # --- Entrainment 2. Aufstieg ---
    "second_ascent_entrainment_factor": 0.75,

    # --- Climb-Factor ---
    "climb_factor": {
        "winter": 0.60,
        "spring": 0.85,
        "summer": 0.80,
        "autumn": 0.70,
    },
    "climb_factor_damping_threshold": {
        "winter": 3.5,
        "spring": 4.5,
        "summer": 4.0,
        "autumn": 3.8,
    },
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

    # --- Pressure-Level-Interpolation (Schritt 1 der Terrain-Kalibrierung) ---
    # Vor dem Parcel-Ascent wird das Druckniveau-Profil linear auf feine
    # Hoehenschritte (m) interpoliert. Standard in RASP/RegTherm/XC-Therm.
    # Verbessert Aufloesung im Hochalpinen (native ICON-Levels 400-500 m).
    # 0 = deaktiviert. Default 100 m.
    # Quellen: meteo_research/thermal_model_calibration.md, Wang (2021),
    # Markowski & Richardson (2010).
    "parcel_interp_dz_m": 100,

    # --- GFS-PBL-Cap-Modus (Schritt 3 der Terrain-Kalibrierung) ---
    # Wie wird die GFS-Boundary-Layer-Hoehe als Obergrenze fuer max_thermal_height
    # behandelt? Drei Modi pro Terrain-Zone:
    #   - "hard"        : klassischer harter Cap (max_thermal_height = min(...)).
    #                     Sinnvoll im Mittelland, wo GFS BLH gut kalibriert ist.
    #   - "soft"        : 50/50-Blend zwischen Parcel-Ergebnis und GFS-BLH.
    #                     Vermeidet, dass eine leicht unterschaetzte GFS-BLH die
    #                     Thermik komplett wegschneidet.
    #   - "sanity_only" : Kein Cap, nur Warnung wenn Differenz gross. Wichtig im
    #                     Hochalpinen, weil GFS BLH dort um 200-500 m systematisch
    #                     unterschaetzt ist (Guo 2022).
    "gfs_pbl_cap_mode": {
        "mittelland": "hard",
        "jura":       "hard",
        "voralpen":   "soft",
        "alpen":      "soft",
        "hochalpin":  "sanity_only",
    },
    # Gewicht der GFS-BLH im "soft"-Blend (0.0 = ignorieren, 1.0 = harter Cap).
    # 0.5 = arithmetisches Mittel zwischen Parcel und GFS-BLH.
    "gfs_pbl_soft_weight": 0.5,
    # Schwelle (m) ab der im "sanity_only"-Modus eine Warnung emittiert wird.
    "gfs_pbl_sanity_warn_m": 1500,

    # --- Schnee-Daempfung (Schritt 4 der Terrain-Kalibrierung) ---
    # Wenn snow_depth > 5 cm, wird der sensible Waermefluss H reduziert (Albedo,
    # Schmelzwaerme). 5-Zonen-Aufteilung statt 2-Zonen-Interpolation:
    #   - Mittelland: Flache Wiesen unter Schnee → 80% Reduktion (factor 0.20)
    #   - Jura:       Bewaldet, etwas mehr Restwaerme → 70% Reduktion
    #   - Voralpen:   Mischhang/Wald, 60% Reduktion
    #   - Alpen:      Felswaende + Schnee mosaikartig, 50% Reduktion
    #   - Hochalpin:  Schneefreie Felsbaender, Sonnenintensitaet → 35% Reduktion
    # Quellen: meteo_research/thermal_model_calibration.md (Albedo-Profile),
    # docs/THERMIK_TERRAIN_KALIBRIERUNG.md.
    "snow_damping_factor": {
        "mittelland": 0.20,
        "jura":       0.30,
        "voralpen":   0.40,
        "alpen":      0.50,
        "hochalpin":  0.65,
    },
    "snow_H_max": {
        "mittelland":  50,
        "jura":       100,
        "voralpen":   120,
        "alpen":      150,
        "hochalpin":  180,
    },

    # --- H-Ramp statt harter H_MIN_THRESHOLD (Schritt 5 der Terrain-Kalibrierung) ---
    # Frueher: harter Schwellenwert H_MIN_THRESHOLD = 30 W/m^2 → unter dieser
    # Schwelle 0% Thermik, darueber 100%. Diskontinuierlich + nicht terrain-aware.
    # Neu: linearer Ramp [h_ramp_low, h_ramp_high] (W/m^2). Unter low = 0,
    # ueber high = full, linear in between. Hochalpine Felswaende koppeln
    # bereits bei niedrigem H Konvektion (Hangwindsysteme + organisierte Bloecke),
    # waehrend Mittelland-Flachterrain mehr Brutto-Heizung braucht, um den
    # Convective Trigger zu ueberwinden.
    "h_ramp_low": {
        "mittelland": 30,
        "jura":       25,
        "voralpen":   20,
        "alpen":      15,
        "hochalpin":  10,
    },
    "h_ramp_high": {
        "mittelland": 80,
        "jura":       70,
        "voralpen":   60,
        "alpen":      50,
        "hochalpin":  40,
    },

    # --- Entrainment MU 5-stufig (Schritt 6 der Terrain-Kalibrierung) ---
    # Vorher: MU=0.0002 + alpine_MU=0.00015 (2-Stufen-Interpolation).
    # Neu: 5-stufig pro Zone. Niedrigeres MU im Hochalpinen, weil dort
    # Talwindsysteme + Felswaende organisiertere, kompaktere Schlauche erzeugen
    # (geringere laterale Einmischung mit der Umgebungsluft).
    "entrainment_mu": {
        "mittelland": 0.00022,
        "jura":       0.00020,
        "voralpen":   0.00018,
        "alpen":      0.00015,
        "hochalpin":  0.00012,
    },

    # --- Climb-Factor terrain-Multiplikator (Schritt 6) ---
    # Multiplikator auf den jahreszeitlichen Basis-climb_factor. Im Hochalpinen
    # erzielen Gleitschirme einen groesseren Anteil des theoretischen w*, weil
    # die Schlauche enger und besser zentrierbar sind. Im Mittelland sind die
    # Bloecke breiter und unruhig - geringerer realer Wirkungsgrad.
    "climb_factor_terrain": {
        "mittelland": 0.95,
        "jura":       1.00,
        "voralpen":   1.05,
        "alpen":      1.10,
        "hochalpin":  1.15,
    },

    # --- Mindest-Thermikhoehe AGL (Schritt 2 der Terrain-Kalibrierung) ---
    # Unter dieser Schwelle ueber Startplatz wird die Thermik als nicht nutzbar
    # eingestuft (Rating <= 1, climb = 0).
    # Terrain-differenziert nach `gust_calculator`-Taxonomie (5 Klassen):
    #   - mittelland: Flache Lagen brauchen tiefe Grenzschicht um brauchbar zu
    #     sein (Startthermik oft > 400 m AGL bis verlaesslich).
    #   - jura: Mittelhoehe, etwas niedrigere Schwelle.
    #   - voralpen: Uebergangsbereich.
    #   - alpen: Felswaende und Hangwinde starten schon flach.
    #   - hochalpin: Hohe Gipfel, kurze aber intensive Ablosungen - 150 m
    #     AGL koennen bereits genuegen (Tessin/Wallis-Fix).
    # Die alte 150-m-Konstante galt pauschal und killte Hochgebirgs-Thermik
    # im Modell nicht, sondern verwarf Mittelland-Blasen zu grosszuegig.
    # Quellen: meteo_research/thermal_model_calibration.md,
    # docs/THERMIK_TERRAIN_KALIBRIERUNG.md.
    "min_thermal_depth_agl": {
        "mittelland": 400,
        "jura": 350,
        "voralpen": 300,
        "alpen": 200,
        "hochalpin": 150,
    },

    # --- Rock-Face Bonus bei Schneedecke (Zentralwallis-Fix) ---
    # Im (hoch-)alpinen Gelaende sind suedexponierte Felswaende im Fruehling
    # trotz Schneedecke schneefrei und erreichen Oberflaechentemperaturen von
    # 20-30 Grad C, waehrend T2m durch den Schnee auf ~0 Grad C gepinnt wird.
    # Dies erzeugt eine starke bodennahe Inversion, die den regionalen
    # Paketaufstieg sabotiert (Zentralwallis-Problem: max_h bleibt an elev_ref
    # kleben, obwohl 800 W/m^2 Einstrahlung vorhanden sind).
    #
    # Die beiden Parameter erlauben die solare Ueberhitzung auch unter Schnee,
    # wenn die Terrain-Zone Felswaende enthaelt. Mittelland/Jura: komplett
    # blockiert (keine Rock Faces).
    #
    # dt_excess(snow, alpin) = base_dt * rock_face_base_fraction + rock_face_dt_boost_C
    # mit base_dt = min(solar_excess_max_C, H / solar_excess_H_divisor)
    "rock_face_dt_boost_C": {
        "mittelland": 0.0,
        "jura":       0.0,
        "voralpen":   0.8,
        "alpen":      1.5,
        "hochalpin":  2.5,
    },
    "rock_face_base_fraction": {
        "mittelland": 0.0,
        "jura":       0.0,
        "voralpen":   0.3,
        "alpen":      0.5,
        "hochalpin":  0.7,
    },
}

# ============================================================================
# WIND-SCHERUNG / THERMIK-QUALITAET (Label-Schwellen fuer chat_engine.py)
# Basis: meteo_research/wind_shear_thermal_quality.md
# ============================================================================

# Vertikale Windscherung durch die Mischungsschicht (km/h pro 100 m).
# Ab WARN wird die Thermik sichtbar gekippt, ab DANGER zerrissen.
# Skalierung nach Terrain-Zone (groessere Zonen = groessere Blasen =
# widerstandsfaehiger gegen Scherung, Skalierung ~ sqrt(L_up/L_up_ref)).
#
# WICHTIG: Mittelland/Jura haben HOEHERE Schwellen als Alpen, weil sie auf
# tiefer Elevation liegen (700-1200m) und die normale Grenzschicht-Scherung
# (Ekman-Spirale: ruhig am Boden, 15-25km/h auf 1500m) IMMER 1.0-2.0
# km/h/100m erzeugt. Das ist kein gefaehrliches Wind-Event sondern der
# normale PBL-Gradient. In den Alpen (1800m+) liegt die Oberflaeche
# bereits in/ueber der Grenzschicht — dort zeigt die gleiche Scherung
# tatsaechlich ein Scherungsereignis an.
SHEAR_THRESHOLDS = {
    "mittelland": {"warn": 2.0, "danger": 3.5},
    "jura":       {"warn": 1.8, "danger": 3.0},
    "voralpen":   {"warn": 1.5, "danger": 2.5},
    "alpen":      {"warn": 1.8, "danger": 2.8},
    "hochalpin":  {"warn": 2.0, "danger": 3.0},
}

# Buoyancy-over-Shear-Ratio (Glendening / RASP).
# Proxy-Formel: simple_BS = (w* [m/s]) / (dU_dz [km/h/100m]) * 100
# Eichung zur Standardform: w*=2, dU=1km/h/100m -> simple_BS=200 (sehr gut)
#                           w*=2, dU=2km/h/100m -> simple_BS=100 (Grenze gut/mittel)
#                           w*=1, dU=2km/h/100m -> simple_BS= 50 (zerrissen-Grenze)
# Skaliert relativ zur Standard-B/S (>=10 gut, <=3 unfliegbar): Faktor ~20.
BS_RATIO_THRESHOLDS = {
    "warn":   100,   # entspricht B/S ~ 5  — Thermik wird spuerbar gestoert
    "danger": 60,    # entspricht B/S ~ 3  — Thermik zerrissen, nur Brocken
}

# Gust Factor: delta_gust [m/s] / w* [m/s]   (dimensionslos)
# delta_gust = (wind_gusts_10m - wind_speed_10m) / 3.6
# w* kommt aus climb_rate des Thermik-Modells.
GUST_FACTOR_THRESHOLDS = {
    "warn":   1.0,   # Turbulenz ~ Auftrieb, Blase fleckig
    "danger": 2.0,   # Turbulenz > 2x Auftrieb, Blase fragmentiert
}

# Konvektive Böen-Korrektur (Panofsky et al. 1977 + COSMO gust diagnostic):
# Auf konvektiven Tagen enthält wind_gusts_10m einen Beitrag von ~α × σ_u/w* × w*
# mit α ≈ 3.0 (COSMO) und σ_u/w* ≈ 0.6 (Panofsky 1977) → 1.8 × w*.
# Dieser Anteil IST die Thermik-Konvektion, keine mechanische Störung.
# Vor GF-Berechnung wird dieser Anteil abgezogen.
CONVECTIVE_GUST_BETA = 1.8

# Unter diesem mechanischen Exzess (m/s) wird bei GF >= danger
# FRAGMENTED statt UNUSABLE vergeben — das Problem ist schwache Thermik,
# nicht extreme Turbulenz.
GF_DANGER_MIN_MECHANICAL_MS = 3.0

# Mittlerer Grundwind durch die Mischungsschicht (km/h).
# Alternative/ergaenzende Schwelle falls SHEAR-Berechnung wegen fehlender
# pressure levels nicht verfuegbar ist.
BL_MEAN_WIND_THRESHOLDS = {
    "mittelland": {"warn": 20, "danger": 28},
    "jura":       {"warn": 22, "danger": 30},
    "voralpen":   {"warn": 25, "danger": 32},
    "alpen":      {"warn": 28, "danger": 35},
    "hochalpin":  {"warn": 30, "danger": 38},
}

# Minimum climb_rate fuer Tag-Aktivierung — unter diesem Wert wird keine
# Thermik-Qualitaets-Warnung ausgegeben (keine Thermik -> keine Zerrissenheit).
THERMAL_QUALITY_MIN_CLIMB = 0.3   # m/s

# Produktive-Thermik-Schwellen (Flyability-Tier-Berechnung)
PRODUCTIVE_CLIMB_MIN = 0.7      # m/s — Mindest-Climb fuer "produktive" Stunde
# Wolken-Schwellen: tief und mittel getrennt (meteo_research/cloud_cover_thermal_impact.md Sektion 6).
# Tiefe Wolken (<3000m) werfen direkten Schatten auf die Quellflaeche → harter Kill ab 80% (FAA).
# Mittlere Wolken (3000-6000m, Altostratus) reduzieren Einstrahlung nur indirekt, sitzen ueber der
# Thermik-Arbeitshoehe → "praktisch tot" laut FAA erst >87%, daher lockerer bei 90%.
PRODUCTIVE_LOW_CLOUD_MAX = 80   # % — Max cloud_cover_low fuer "produktive" Stunde
PRODUCTIVE_MID_CLOUD_MAX = 90   # % — Max cloud_cover_mid fuer "produktive" Stunde
PRODUCTIVE_CLOUD_MAX = 80       # % — DEPRECATED, behalten fuer Abwaertskompatibilitaet. Nutze LOW/MID getrennt.
PRODUCTIVE_HOURS_FOR_GREEN = 4  # Mindest-Stunden fuer gray->green Upgrade
PRODUCTIVE_HOURS_DOWNGRADE = 2  # Untere Schwelle: green/violet -> gray

# Violett-Kriterien (XC-Tag). LLM entscheidet final, aber TAGESPROFIL zeigt diese
# Schwellen als Violett-Kandidat-Hint. Research: meteo_research/cloud_cover_thermal_impact.md
# - Wolken-Maxima 50/50 matchen FAA-Daempfungsgrenze: darueber beginnt signifikante
#   Einstrahlungsreduktion (Altostratus ab ~50%, Cu-Dampfung ab 50-60%). Violett =
#   optimale Cu-Zone (12-50% SCT) oder Blau (0%), keine Ueberentwicklung.
# - Peak 2.5 m/s und 5h produktiv strenger als green (4h) = "gute Konsistenz" fuer XC.
# - ROUGH/UNUSABLE<30% = saubere Thermik, keine Bart-Zentrierungsprobleme.
VIOLET_PEAK_MIN = 2.5           # m/s — Mindest-Peak fuer Violett-Kandidat
VIOLET_HOURS_MIN = 5            # Mindest-produktive-Stunden fuer Violett
VIOLET_ROUGH_MAX = 30           # % — Max ROUGH-UNUSABLE-Anteil
VIOLET_UNUSABLE_MAX = 30        # % — Max Gesamt-UNUSABLE-Anteil
VIOLET_CLOUD_LOW_MAX = 50       # % — Max Ø tiefe Wolken ueber Thermikstunden
VIOLET_CLOUD_MID_MAX = 50       # % — Max Ø mittlere Wolken ueber Thermikstunden
VIOLET_RATING_MIN = 9           # Mindest-Rating (0-10) fuer violet — nur Ausnahmetage
# PRODUCTIVE_BAND_DEPTH_MIN entfernt (war 400 m, physikalisch unfundiert).
# Ersetzt durch thermik_calculator.min_band_depth(climb_peak, terrain_zone):
# climb-abhaengig (3 Kurbeln × 7 s × Netto-Steigen) und terrain-differenziert.
# Siehe meteo_research/band_depth_calibration.md.

# ─── Wind-Schwellen (Boden + Hoehe einheitlich, Spot + Region) ───
# Konservative Auslegung: Ab WIND_DANGER_KMH ist die Stunde gefaehrlich,
# zwischen WIND_WARN_KMH und WIND_DANGER_KMH "kraeftig" (sportlich).
# Gilt fuer Bodenwind (10m) UND Hoehenwind W(z) im Flugbereich.
# Flugbereich = elevation_ref bis thermal_top + 1000m (effective_ceiling).
WIND_WARN_KMH = 20              # Wind 20–30 km/h → [WIND-WARN] / [ALOFT-WIND-WARN]
WIND_DANGER_KMH = 30            # Wind > 30 km/h → [WIND-DANGER] / [ALOFT-WIND-DANGER]

# Idealbereich Bodenwind fuer Thermik-Spots (Default-Annahme).
# Soaring-Spots (z.B. Balderen) brauchen oft mehr — siehe Spot-Bemerkung im
# Datenblock. Fuer wind_safety_rating in der Sub-Rating-Bewertung (siehe
# skills/shared/_safety_subratings.md): 9-10 = innerhalb dieses Bereichs.
WIND_IDEAL_MIN_KMH = 5          # km/h — unter diesem: zu schwach fuer typische Bedingungen
WIND_IDEAL_MAX_KMH = 20         # km/h — ab diesem: ueber Komfortzone (= WIND_WARN_KMH)

# ─── Start-Fenster-Schwellen (Windrichtung + Gefahrenfreiheit) ───
# Eine "saubere Stunde" = WIND-OK (Spot-Sektor) UND keine DANGER-Tags.
# Tag-Status haengt am laengsten zusammenhaengenden Block sauberer Stunden:
#   < CLEAN_WINDOW_MIN_HOURS   → not_safe (kein ausreichendes Start-Fenster)
#   >= CLEAN_WINDOW_GREEN_HOURS → safe/green moeglich (LLM entscheidet conditional vs safe)
# Schwellen sind absichtlich identisch: keine Zwischenzone "max conditional" mehr —
# entweder reicht das Fenster (>=3h) oder nicht (<3h). Pre-Filter wendet dieselbe
# Schwelle deterministisch auf wind_ok_count an (siehe analyzers._prefilter_not_safe).
# WIND-WRONG Stunden NACH dem Start-Fenster sind kein Grund fuer UNFLIEGBAR —
# der Pilot ist bereits in der Luft, Landung i.d.R. auf separatem Landeplatz.
CLEAN_WINDOW_MIN_HOURS = 3       # h — unterhalb: not_safe
CLEAN_WINDOW_GREEN_HOURS = 3     # h — ab hier: safe/green moeglich

# Richtungsdreher-Anmerkung (nur caution_notes, KEIN Status-Downgrade):
# Erfasst den groessten Richtungsdreher innerhalb eines gleitenden Fensters von
# bis zu WIND_DIRECTION_SWING_WINDOW_H Stunden — sowohl abrupte 1h-Spruenge als
# auch langsames Drehen ueber 2-3h (z.B. 120° ueber 3h = unbestaendiger Wind).
# Ab WIND_DIRECTION_SWING_NOTE_DEG° gibt es einen Pilot-Hinweis in caution_notes.
WIND_DIRECTION_SWING_NOTE_DEG = 45   # Grad — Schwelle fuer caution_notes-Hinweis
WIND_DIRECTION_SWING_WINDOW_H = 3    # Stunden — max Fensterbreite fuer Drift-Erkennung

# ─── Boeen-Schwellen (Boden + Hoehe einheitlich, nur Spots) ───
# Boden: wind_gusts_10m (nach Bias-Korrektur + Multi-Modell-Merge).
# Hoehe: T(z) = W(z) + exp-Decay vom Bodenboeen-Exzess (Turbulenzrisiko).
GUST_WARN_KMH = 30              # Boeen > 30 km/h → [GUST-WARN] / [ALOFT-GUST-WARN]
GUST_DANGER_KMH = 40            # Boeen > 40 km/h → [GUST-DANGER] / [ALOFT-GUST-DANGER]

# ─── CAPE-Schwellen (Konvektionsenergie, J/kg) ───
# CAPE-DANGER (hart): extreme Instabilität ODER CAPE + Regen (aktive Ueberentwicklung).
# CAPE-WARN (soft):   Potenzial vorhanden, Modell prognostiziert keinen Trigger.
CAPE_WARN_JKG = 800             # CAPE > 800 J/kg → [CAPE-WARN]
CAPE_DANGER_JKG = 1500          # CAPE > 1500 J/kg → [CAPE-DANGER]

# Wind/Boeen-Trend Schwellen (Stunden) — gilt fuer Boden + Hoehe summiert:
# - CONDITIONAL_HOURS: safe → conditional (Trend-Pattern wirft sauberes Fenster).
# - NOTSAFE_HOURS:    Wind-Trend DURCHGEHEND_DANGER / EINGEKESSELT (Fenster<3h)
#                     → harter NO-GO. Boeen-Trend → LLM-Empfehlung "bevorzugt NoGo".
WIND_TREND_CONDITIONAL_HOURS = 3
WIND_TREND_NOTSAFE_HOURS = 3
GUST_TREND_FLOOR_HOURS = 3       # Min. Stunden fuer Boeen-Floor (Boden+Hoehe summiert)

# ============================================================================
# DRIFT-RENARRATE (Konsistenz LLM-Status vs. Sub-Rating-Floor)
# ============================================================================
# Wenn das LLM safety_status=safe schreibt aber min(subs)<4, eskaliert die
# Engine den Status (SubRatingFloor-Decision). Der LLM-Prosa-Text (summary,
# recommendation) bleibt dann erstmal mit der alten Status-Annahme stehen.
#
# Phase 1 (RENARRATE_ON_DRIFT=False): Telemetrie sammeln, kein Re-Narrate.
#                    Drift ist sichtbar in `_status_telemetry` jeder Analyse,
#                    summary kann gelegentlich vom Status abweichen.
# Phase 2 (RENARRATE_ON_DRIFT=True, AKTIV): bei erkanntem Drift kleiner
#                    Zusatzcall, der summary/recommendation passend zum
#                    eskalierten Status umschreibt. Sub-Ratings bleiben
#                    unangetastet (Forschungs-Datenpunkt). Mehrkosten: nur
#                    fuer Drift-Faelle, geschaetzt <1% Gesamtkosten.
RENARRATE_ON_DRIFT = True
# Modell fuer den Re-Narrate-Call. None = analysis_model (gleiches Modell).
# Setze auf z.B. "gpt-4o-mini" fuer billigeren Re-Narrate.
RENARRATE_MODEL = None

# ============================================================================
# INSTANTDB-KONFIGURATION
# ============================================================================

# ============================================================================
# STATIONSDATEN + BIAS-KORREKTUR
# ============================================================================

WINDS_MOBI_API = "https://winds.mobi/api/2.3"
STATION_SEARCH_RADIUS_KM = 30
STATION_MAX_ELEV_DIFF_M = 300   # Vorher 500 — enger, weniger Expositions-Verfälschung
STATION_MAX_PER_SPOT = 3
BIAS_CORRECTION_ENABLED = False   # Bias-Korrektur auf wind_gusts_10m anwenden (Spots + Regionen)
MULTI_MODEL_GUST_MERGE = False    # wind_gusts_10m = max(D2, CH1, CH2). False = nur WIND_MODEL verwenden
BIAS_LOOKBACK_DAYS = 14
BIAS_ALPHA = 0.85         # Exponentieller Gewichtungsfaktor (jüngere Paare stärker)
BIAS_MIN_PAIRS = 5        # Mindestanzahl Paare bevor Bias angewendet wird
BIAS_MAX_CORRECTION = 15  # Max ±15 km/h Korrektur (Sicherheitslimit)
BIAS_ELEV_DECAY_HG = 400  # H_g für Höhenkorrektur Station→Spot (m)

# ============================================================================
# TAEGLICHER ABLAUF (Wetter-Refresh + LLM-Analyse + Briefing-Versand)
# ============================================================================
# Sequenzieller Job: refresh_weather() -> build_briefing_data() (LLM) -> Mails.
# Wochentage: 0=Mo, 1=Di, 2=Mi, 3=Do, 4=Fr, 5=Sa, 6=So
DAILY_RUN_WEEKDAYS = {0, 1, 2, 3, 4, 5, 6}  # Default: jeden Tag
DAILY_RUN_HOUR     = 6
DAILY_RUN_MINUTE   = 0

# ============================================================================
# E-MAIL-BRIEFING (SMTP Infomaniak)
# ============================================================================
# BASE_URL = App-Domain (Flask), MARKETING_URL = Marketing-Webpage (Next.js).
# In Produktion: BASE_URL=https://app.gleitcast.ch, MARKETING_URL=https://gleitcast.ch
BASE_URL        = os.environ.get("GLEITCAST_BASE_URL",      "https://app.gleitcast.ch")
MARKETING_URL   = os.environ.get("GLEITCAST_MARKETING_URL", "https://gleitcast.ch")

# Infomaniak SMTP (Standardwerte aus ihrer Doku; Port 465 SSL oder 587 STARTTLS)
SMTP_HOST       = os.environ.get("SMTP_HOST", "mail.infomaniak.com")
SMTP_PORT       = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USE_SSL    = os.environ.get("SMTP_USE_SSL", "1") == "1"   # True = SSL:465, False = STARTTLS:587
SMTP_USER       = os.environ.get("SMTP_USER", "")               # meist = SENDER_EMAIL
SMTP_PASSWORD   = os.environ.get("SMTP_PASSWORD", "")
SENDER_EMAIL    = os.environ.get("SENDER_EMAIL", "briefing@example.invalid")
SENDER_NAME     = os.environ.get("SENDER_NAME", "Gleitcast")

# Admin-Dashboard: HTTP Basic Auth (nur Password-Check, User ignoriert).
# Leer = Admin-Routen geben 503 zurueck (deaktiviert).
ADMIN_PASSWORD  = os.environ.get("ADMIN_PASSWORD", "")

# ============================================================================
# ROUTING / GEOCODING (Phase 1)
# ============================================================================
# Public Valhalla (FOSSGIS-gehostet) für Isochronen + Routing.
# Public Nominatim für Geocoding. Bei Ausfall: kein Fallback — siehe routing.py.
VALHALLA_URL = os.environ.get("VALHALLA_URL", "https://valhalla1.openstreetmap.de")
NOMINATIM_URL = os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org")
ROUTING_TIMEOUT = 15  # seconds (Valhalla + Nominatim HTTP)
ROUTING_USER_AGENT = "Gleitcast/1.0 (paragliding weather app)"
GEOCODE_CACHE_TTL = 24 * 3600  # 24h in-memory cache für Nominatim

# ============================================================================
# LLM-PROVIDER + MODELL (Chat + Analyse getrennt konfigurierbar)
# ============================================================================
# Vier unterstuetzte Provider: "openai" | "anthropic" | "gemini" | "deepseek"
#   - openai    : gpt-4o-mini (guenstig, Batch-API, bekannt stabil)
#   - anthropic : Claude Haiku 4.5 (beste Tool-Call + DE-Qualitaet)
#   - gemini    : Gemini 2.5 Flash / Flash-Lite (guenstigste Option)
#   - deepseek  : DeepSeek-V3 (sehr guenstig, OpenAI-kompatibel, China-gehostet, keine Batch-API)
#
# Hybrid-Setup moeglich: z.B. Chat=deepseek (Prosa), Analyse=openai (Batch-Rabatt).
# Jeder aktive Provider braucht den entsprechenden API-Key als ENV-Variable.

CHAT_PROVIDER = os.environ.get("CHAT_PROVIDER", "openai").lower()
ANALYSIS_PROVIDER = os.environ.get("ANALYSIS_PROVIDER", "openai").lower()

# Modell pro Provider + Anwendung. ENV-Overrides erlauben Feintuning.
LLM_MODELS = {
    "openai": {
        "chat":     os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
        "analysis": os.environ.get("OPENAI_ANALYSIS_MODEL", "gpt-4o-mini"),
    },
    "anthropic": {
        "chat":     os.environ.get("ANTHROPIC_CHAT_MODEL", "claude-haiku-4-5"),
        "analysis": os.environ.get("ANTHROPIC_ANALYSIS_MODEL", "claude-haiku-4-5"),
    },
    "gemini": {
        "chat":     os.environ.get("GEMINI_CHAT_MODEL", "gemini-2.5-flash"),
        "analysis": os.environ.get("GEMINI_ANALYSIS_MODEL", "gemini-2.5-flash-lite"),
    },
    "deepseek": {
        # Verfuegbare Modelle:
        #   deepseek-chat       = V3 (general, billigste Option)
        #   deepseek-reasoner   = R1 (Reasoning)
        #   deepseek-v4-flash   = V4 Flash (284B MoE, $0.14/$0.28 per Mtok, 1M context)
        #   deepseek-v4-pro     = V4 Pro   (1.6T MoE, $1.74/$3.48 per Mtok, 1M context)
        "chat":     os.environ.get("DEEPSEEK_CHAT_MODEL", "deepseek-v4-flash"),
        "analysis": os.environ.get("DEEPSEEK_ANALYSIS_MODEL", "deepseek-v4-flash"),
    },
}

# Top-Level-Attribute fuer Admin-UI-Override (config_overrides.setattr greift hier).
# get_model() liest bevorzugt diese Attribute, damit Aenderungen via Admin-UI
# ohne Neustart wirken (chat_engine cached pro Init — Neustart trotzdem noetig,
# damit aktive Engine-Instanzen das neue Modell sehen).
OPENAI_CHAT_MODEL        = LLM_MODELS["openai"]["chat"]
OPENAI_ANALYSIS_MODEL    = LLM_MODELS["openai"]["analysis"]
ANTHROPIC_CHAT_MODEL     = LLM_MODELS["anthropic"]["chat"]
ANTHROPIC_ANALYSIS_MODEL = LLM_MODELS["anthropic"]["analysis"]
GEMINI_CHAT_MODEL        = LLM_MODELS["gemini"]["chat"]
GEMINI_ANALYSIS_MODEL    = LLM_MODELS["gemini"]["analysis"]
DEEPSEEK_CHAT_MODEL      = LLM_MODELS["deepseek"]["chat"]
DEEPSEEK_ANALYSIS_MODEL  = LLM_MODELS["deepseek"]["analysis"]

# Mapping Modellname -> Provider. Wird vom Admin-UI verwendet, um aus einem
# einzelnen CHAT_MODEL/ANALYSIS_MODEL-Dropdown den Provider abzuleiten.
# Bei neuen Modellen hier eintragen — sonst greift der Auto-Provider nicht.
MODEL_PROVIDER_MAP: dict[str, str] = {
    # OpenAI
    "gpt-5.5": "openai", "gpt-5.4": "openai", "gpt-5.4-mini": "openai",
    "gpt-5.4-nano": "openai", "gpt-5.3-codex": "openai",
    "gpt-4o": "openai", "gpt-4o-mini": "openai",
    # Anthropic
    "claude-opus-4-7": "anthropic", "claude-opus-4-6": "anthropic",
    "claude-sonnet-4-6": "anthropic", "claude-opus-4-5": "anthropic",
    "claude-sonnet-4-5": "anthropic", "claude-haiku-4-5": "anthropic",
    # Gemini
    "gemini-2.5-pro": "gemini", "gemini-2.5-flash": "gemini",
    "gemini-2.5-flash-lite": "gemini",
    # DeepSeek
    "deepseek-v4-pro": "deepseek", "deepseek-v4-flash": "deepseek",
    "deepseek-chat": "deepseek", "deepseek-reasoner": "deepseek",
}

# Single Source of Truth fuer Admin-UI: ein Modellname pro Anwendung.
# Provider wird beim Override automatisch via MODEL_PROVIDER_MAP abgeleitet
# und CHAT_PROVIDER/ANALYSIS_PROVIDER + per-provider-Modell-Attr nachgezogen.
def _resolve_provider_and_model(name: str, purpose: str) -> tuple[str, str]:
    """Toleriert wenn jemand einen Modellnamen statt Provider-Namen in ENV
    geschrieben hat (z.B. ANALYSIS_PROVIDER=deepseek-v4-pro). Liefert immer
    ein gueltiges (provider, model)-Paar."""
    if name in LLM_MODELS:
        return name, LLM_MODELS[name][purpose]
    if name in MODEL_PROVIDER_MAP:
        prov = MODEL_PROVIDER_MAP[name]
        logging.getLogger(__name__).warning(
            "%s_PROVIDER='%s' ist ein Modellname, kein Provider — interpretiere als provider=%s, model=%s.",
            purpose.upper(), name, prov, name)
        return prov, name
    logging.getLogger(__name__).warning(
        "%s_PROVIDER='%s' unbekannt — falle zurueck auf 'openai'.", purpose.upper(), name)
    return "openai", LLM_MODELS["openai"][purpose]


CHAT_PROVIDER, CHAT_MODEL         = _resolve_provider_and_model(CHAT_PROVIDER, "chat")
ANALYSIS_PROVIDER, ANALYSIS_MODEL = _resolve_provider_and_model(ANALYSIS_PROVIDER, "analysis")
# Per-provider-Attr nachziehen, damit get_model() konsistent bleibt
LLM_MODELS[CHAT_PROVIDER]["chat"]         = CHAT_MODEL
LLM_MODELS[ANALYSIS_PROVIDER]["analysis"] = ANALYSIS_MODEL
globals()[f"{CHAT_PROVIDER.upper()}_CHAT_MODEL"]         = CHAT_MODEL
globals()[f"{ANALYSIS_PROVIDER.upper()}_ANALYSIS_MODEL"] = ANALYSIS_MODEL

# API-Keys (nur der aktive Provider muss gesetzt sein)
OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")
DEEPSEEK_API_KEY  = os.environ.get("DEEPSEEK_API_KEY", "")

# Rueckwaertskompatibilitaet: OPENAI_MODEL (alter ENV-Name) ueberschreibt beide Defaults
_legacy_model = os.environ.get("OPENAI_MODEL", "").strip()
if _legacy_model:
    LLM_MODELS["openai"]["chat"] = _legacy_model
    LLM_MODELS["openai"]["analysis"] = _legacy_model


def get_api_key(provider: str) -> str:
    """Gibt den API-Key fuer einen Provider zurueck."""
    return {
        "openai":    OPENAI_API_KEY,
        "anthropic": ANTHROPIC_API_KEY,
        "gemini":    GEMINI_API_KEY,
        "deepseek":  DEEPSEEK_API_KEY,
    }.get(provider, "")


def get_model(provider: str, purpose: str) -> str:
    """purpose = 'chat' oder 'analysis'.

    Top-Level-Attribute (z.B. OPENAI_CHAT_MODEL) haben Vorrang vor LLM_MODELS,
    damit Admin-UI-Overrides via setattr(config, ...) sofort greifen.
    """
    attr = f"{provider.upper()}_{purpose.upper()}_MODEL"
    val = globals().get(attr)
    if val:
        return val
    return LLM_MODELS.get(provider, {}).get(purpose, "")


# ============================================================================
# LLM-ANALYSE-KONFIGURATION
# ============================================================================

# OPENAI_ANALYSIS_MODE — gilt AUSSCHLIESSLICH wenn ANALYSIS_PROVIDER=openai.
# "parallel" = schnell (viele gleichzeitige Calls), "batch" = guenstig
# (OpenAI Batch API, 50% billiger, dauert 5-30 Min).
#
# Anthropic, Gemini und DeepSeek haben KEINE Batch-API → bei diesen Providern
# wird der Wert zur Laufzeit ignoriert und immer parallel ausgefuehrt
# (Auto-Fallback unten + Dispatcher in engine/analyzers.py).
#
# Wird ueblicherweise via Admin-UI gesetzt (data/config_overrides.json), nicht ENV.
OPENAI_ANALYSIS_MODE = os.environ.get(
    "OPENAI_ANALYSIS_MODE",
    # Backwards-Compat: alter ENV-Name LLM_ANALYSIS_MODE als Fallback
    os.environ.get("LLM_ANALYSIS_MODE", "parallel"),
)
if OPENAI_ANALYSIS_MODE == "batch" and ANALYSIS_PROVIDER != "openai":
    logging.getLogger(__name__).warning(
        "OPENAI_ANALYSIS_MODE=batch greift nur mit ANALYSIS_PROVIDER=openai "
        "(aktuell: '%s'). Wird zur Laufzeit ignoriert → parallel.",
        ANALYSIS_PROVIDER,
    )
    OPENAI_ANALYSIS_MODE = "parallel"

# Anzahl paralleler LLM-Calls im "parallel"-Modus.
# OpenAI gpt-4o-mini erlaubt bis 500 RPM (Tier 1). Default 10 ist konservativ.
# Hoeher = schneller, aber mehr Quota-Verbrauch pro Sekunde.
LLM_MAX_WORKERS = int(os.environ.get("LLM_MAX_WORKERS", "20"))

# Poll-Intervall (Sekunden) im "batch"-Modus, wie oft der Batch-Status geprüft wird.
LLM_BATCH_POLL_INTERVAL = int(os.environ.get("LLM_BATCH_POLL_INTERVAL", "30"))

# Stall-Timeout (Sekunden): Wenn ein OpenAI-Batch so lange ohne Progress
# (completed-Counter unverändert) bleibt, wird er gecancelt und der Daily-Run
# fällt einmalig auf Parallel-Modus zurück. Default 60 min.
LLM_BATCH_STALL_TIMEOUT_S = int(os.environ.get("LLM_BATCH_STALL_TIMEOUT_S", "3600"))


# ============================================================================
# LLM-Kosten-Telemetrie
# Preise in USD pro 1 Mio Tokens. Schluessel: Modell-ID.
# - in / out          : Standard-Tarif (parallel/sync)
# - in_batch / out_batch : OpenAI Batch-API (50% Rabatt)
# - cached_in         : Anthropic Prompt-Cache-Hit (10%) bzw. OpenAI auto-cache (50%)
# Stand: 2026-04. Bei Preisaenderung hier zentral pflegen.
# ============================================================================
MODEL_PRICES = {
    "gpt-4o-mini":      {"in": 0.150, "out": 0.600, "cached_in": 0.075, "in_batch": 0.075, "out_batch": 0.300},
    "gpt-4o":           {"in": 2.500, "out": 10.000, "cached_in": 1.250, "in_batch": 1.250, "out_batch": 5.000},
    "gpt-4.1-mini":     {"in": 0.400, "out": 1.600, "cached_in": 0.100, "in_batch": 0.200, "out_batch": 0.800},
    "claude-haiku-4-5": {"in": 1.000, "out": 5.000, "cached_in": 0.100, "in_batch": 0.500, "out_batch": 2.500},
    "claude-sonnet-4-6":{"in": 3.000, "out": 15.000, "cached_in": 0.300, "in_batch": 1.500, "out_batch": 7.500},
    "gemini-2.5-flash": {"in": 0.300, "out": 2.500, "cached_in": 0.075, "in_batch": 0.150, "out_batch": 1.250},
    "gemini-2.5-flash-lite": {"in": 0.100, "out": 0.400, "cached_in": 0.025, "in_batch": 0.050, "out_batch": 0.200},
    # DeepSeek: keine Batch-API (in_batch/out_batch == in/out). Cache-Hit-Rabatt automatisch (kein Opt-in).
    # Preise prueffen unter https://api-docs.deepseek.com/quick_start/pricing — Stand 2026-04.
    "deepseek-chat":     {"in": 0.270, "out": 1.100, "cached_in": 0.070, "in_batch": 0.270, "out_batch": 1.100},
    "deepseek-reasoner": {"in": 0.550, "out": 2.190, "cached_in": 0.140, "in_batch": 0.550, "out_batch": 2.190},
    # DeepSeek V4 (Apr 2026): 1M-Kontext, MoE, optional Thinking-Mode.
    # Cache-Hit-Rabatt ~50% (Schaetzung, exakter Wert in DS-Docs pruefen).
    "deepseek-v4-flash": {"in": 0.140, "out": 0.280, "cached_in": 0.035, "in_batch": 0.140, "out_batch": 0.280},
    "deepseek-v4-pro":   {"in": 1.740, "out": 3.480, "cached_in": 0.435, "in_batch": 1.740, "out_batch": 3.480},
}

# Notbremse: Wenn ein Analyse-Lauf diese Schwelle ueberschreitet, sauber abbrechen.
# Schuetzt vor Runaway-Szenarien (Bug, versehentlich falscher Worker-Count, etc.).
LLM_COST_CAP_USD = float(os.environ.get("LLM_COST_CAP_USD", "5.00"))

# Pfad fuer JSONL-Telemetrie (eine Zeile pro Analyse-Lauf).
import pathlib as _pathlib
COST_TELEMETRY_PATH = _pathlib.Path(os.environ.get(
    "COST_TELEMETRY_PATH",
    str(_pathlib.Path(__file__).parent / "data" / "cost_telemetry.jsonl"),
))


def atomic_write_json(path, data, indent=2, ensure_ascii=False):
    """Schreibt JSON atomar via temp-file + os.replace().
    Verhindert Corruption wenn ein paralleler Reader waehrend des Writes liest.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Async-Write-Queue fuer grosse JSON-Dateien (z.B. wetterdaten.json, 196 MB).
# Entkoppelt den 3-5s File-IO vom Aufrufer. Caveat: Der Daten-Dict darf NACH
# queue_atomic_write_json() nicht mehr mutiert werden (keine Defensivkopie
# wegen Speicherdruck bei 196 MB). Nutzer ist fuer Immutability verantwortlich.
# ---------------------------------------------------------------------------
_write_queue = None
_write_worker = None
_write_worker_lock = threading.Lock()
_write_logger = logging.getLogger(__name__ + ".async_write")


def _writer_loop():
    while True:
        job = _write_queue.get()
        try:
            if job is None:
                return
            path, data, indent, ensure_ascii = job
            try:
                atomic_write_json(path, data, indent=indent, ensure_ascii=ensure_ascii)
            except Exception as e:
                _write_logger.error("Async-Write fehlgeschlagen (%s): %s", path, e)
        finally:
            _write_queue.task_done()


def _ensure_async_writer():
    global _write_queue, _write_worker
    with _write_worker_lock:
        if _write_worker is not None:
            return
        _write_queue = queue.Queue()
        _write_worker = threading.Thread(
            target=_writer_loop, daemon=True, name="atomic-writer"
        )
        _write_worker.start()
        atexit.register(_flush_async_writer)


def _flush_async_writer(timeout: float = 30.0):
    """Wartet bis zu timeout Sekunden auf Abschluss aller pending Writes."""
    if _write_queue is None:
        return
    # queue.join() hat kein Timeout → Workaround ueber Polling
    import time as _time
    deadline = _time.time() + timeout
    while _time.time() < deadline:
        if _write_queue.unfinished_tasks == 0:
            return
        _time.sleep(0.1)
    _write_logger.warning(
        "Async-Write Flush-Timeout nach %ss — %d Jobs ausstehend",
        timeout, _write_queue.unfinished_tasks,
    )


def queue_atomic_write_json(path, data, indent=2, ensure_ascii=False):
    """Non-blocking: Reiht einen atomaren JSON-Write in die Hintergrund-Queue ein.

    WICHTIG: `data` darf nach diesem Aufruf NICHT mehr mutiert werden (keine Kopie).
    Bei Crash zwischen Enqueue und Flush geht der Write verloren — OK fuer
    re-fetchbare Daten wie wetterdaten.json, NICHT fuer LLM-Analysen.
    """
    _ensure_async_writer()
    _write_queue.put((path, data, indent, ensure_ascii))