"""
Konfigurationsdatei für Flychat
Adaptiert von uetliberg_ticker/config.py - Multi-Spot, Chat-basiert.
"""

import os
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
REGIONEN_GEOJSON_PATH = DATA_DIR / "regionen_referenzpunkte.geojson"

# Vercel: Nur /tmp ist schreibbar. Readonly-Daten (CSV, GeoJSON) bleiben in data/
if os.environ.get("VERCEL"):
    _WRITABLE_DIR = Path("/tmp/flychat")
    _WRITABLE_DIR.mkdir(parents=True, exist_ok=True)
    WEATHER_JSON_PATH = _WRITABLE_DIR / "wetterdaten.json"
    HISTORY_DIR = _WRITABLE_DIR / "history"
    STATION_DB_PATH = _WRITABLE_DIR / "station_observations.db"
else:
    WEATHER_JSON_PATH = DATA_DIR / "wetterdaten.json"
    HISTORY_DIR = DATA_DIR / "history"
    STATION_DB_PATH = DATA_DIR / "station_observations.db"

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
BIAS_LOOKBACK_DAYS = 14
BIAS_ALPHA = 0.85         # Exponentieller Gewichtungsfaktor (jüngere Paare stärker)
BIAS_MIN_PAIRS = 5        # Mindestanzahl Paare bevor Bias angewendet wird
BIAS_MAX_CORRECTION = 15  # Max ±15 km/h Korrektur (Sicherheitslimit)
BIAS_ELEV_DECAY_HG = 400  # H_g für Höhenkorrektur Station→Spot (m)

# ============================================================================
# INSTANTDB-KONFIGURATION
# ============================================================================

INSTANTDB_APP_ID = "325047cb-0c83-4630-8573-3e59e6dafe54"
INSTANTDB_ADMIN_TOKEN = os.environ.get("INSTANTDB_ADMIN_TOKEN")
INSTANTDB_API_URL = "https://api.instantdb.com"

# ============================================================================
# ROUTING / GEOCODING (Phase 1)
# ============================================================================
# Public Valhalla (FOSSGIS-gehostet) für Isochronen + Routing.
# Public Nominatim für Geocoding. Bei Ausfall: kein Fallback — siehe routing.py.
VALHALLA_URL = os.environ.get("VALHALLA_URL", "https://valhalla1.openstreetmap.de")
NOMINATIM_URL = os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org")
ROUTING_TIMEOUT = 15  # seconds (Valhalla + Nominatim HTTP)
ROUTING_USER_AGENT = "Flychat/1.0 (paragliding weather app)"
GEOCODE_CACHE_TTL = 24 * 3600  # 24h in-memory cache für Nominatim

# ============================================================================
# LLM-ANALYSE-KONFIGURATION
# ============================================================================

# Modus: "parallel" = schnell (viele gleichzeitige Calls), "batch" = guenstig
# (OpenAI Batch API, 50% billiger, dauert 5-30 Min).
LLM_ANALYSIS_MODE = os.environ.get("LLM_ANALYSIS_MODE", "parallel")

# Anzahl paralleler LLM-Calls im "parallel"-Modus.
# OpenAI gpt-4o-mini erlaubt bis 500 RPM (Tier 1). Default 10 ist konservativ.
# Hoeher = schneller, aber mehr Quota-Verbrauch pro Sekunde.
LLM_MAX_WORKERS = int(os.environ.get("LLM_MAX_WORKERS", "20"))

# Poll-Intervall (Sekunden) im "batch"-Modus, wie oft der Batch-Status geprüft wird.
LLM_BATCH_POLL_INTERVAL = int(os.environ.get("LLM_BATCH_POLL_INTERVAL", "30"))