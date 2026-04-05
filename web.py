"""
Flask Web-Server für Flychat.
Routes: Chat-API, Spots-API, Wetter-API, Meteogramm-API.
"""

import os
import logging
from flask import Flask, render_template, request, jsonify, redirect, url_for
from datetime import datetime, timedelta

import config

logger = logging.getLogger(__name__)
from thermik_calculator import calculate_thermal_profile, calculate_dewpoint
from source_area import get_all_regions_geojson
from fetch_weather import get_weather_for_location
from foehn_indicators import fetch_foehn_data, evaluate_foehn, FOEHN_STATIONS, \
    THRESHOLD_DELTA_P_CAUTION, THRESHOLD_DELTA_P_DANGER, THRESHOLD_HUMIDITY_LOW
from gust_calculator import (
    estimate_altitude_gusts,
    collect_gust_anchors,
    estimate_altitude_gusts_multi_anchor,
    get_scale_height,
    get_oi_scale_lengths,
)
from source_area import find_region_for_point

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "flychat-dev-key")

# Ensure JSON responses send raw UTF-8 characters (ä, ö, ü instead of \uXXXX)
app.config['JSON_AS_ASCII'] = False 
app.json.ensure_ascii = False

# Global engine instance (set in main.py)
engine = None


def init_app(flychat_engine):
    """Setzt die globale Engine-Instanz."""
    global engine
    engine = flychat_engine


# ============================================================================
# PAGE ROUTES
# ============================================================================

@app.route("/")
def index():
    return render_template(
        "index.html",
        instantdb_app_id=config.INSTANTDB_APP_ID,
        forecast_days=config.FORECAST_DAYS,
    )


@app.route("/chat")
def chat_page():
    return render_template(
        "index.html",
        instantdb_app_id=config.INSTANTDB_APP_ID,
        forecast_days=config.FORECAST_DAYS,
    )


@app.route("/map")
def map_page():
    return render_template(
        "index.html",
        instantdb_app_id=config.INSTANTDB_APP_ID,
        forecast_days=config.FORECAST_DAYS,
    )


@app.route("/analyses")
def analyses_page():
    return render_template(
        "analyses.html",
        instantdb_app_id=config.INSTANTDB_APP_ID,
        forecast_days=config.FORECAST_DAYS,
    )


@app.route("/regionen")
def regionen_page():
    return render_template(
        "regionen.html",
        instantdb_app_id=config.INSTANTDB_APP_ID,
        forecast_days=config.FORECAST_DAYS,
    )


# ============================================================================
# CHAT API
# ============================================================================

@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Keine Nachricht"}), 400

    message = data["message"].strip()
    session_id = data.get("session_id", "default")

    if not message:
        return jsonify({"error": "Leere Nachricht"}), 400

    reply = engine.answer(session_id, message)
    return jsonify({"reply": reply, "session_id": session_id})


@app.route("/api/reset-chat", methods=["POST"])
def api_reset_chat():
    """Setzt die aktuelle Konversation zurück."""
    session_id = request.json.get("session_id")
    if session_id:
        engine.reset_conversation(session_id)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Keine Session-ID"}), 400




@app.route("/api/run-analyses", methods=["POST"])
def api_run_analyses():
    """Startet die LLM Spot-Analyse für alle Spots."""
    try:
        result = engine.run_spot_analyses()
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/analyses")
def api_analyses():
    """Debug-Endpoint: Zeigt aktuelle Voranalysen als JSON."""
    return jsonify({
        "analyses_count": len(engine.spot_analyses),
        "analyses_loaded_at": engine.analyses_loaded_at.isoformat() if engine.analyses_loaded_at else None,
        "analyses": engine.spot_analyses,
    })


@app.route("/api/run-region-analyses", methods=["POST"])
def api_run_region_analyses():
    """Startet die LLM Region-Analyse fuer alle Regionen."""
    try:
        result = engine.run_region_analyses()
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/region-analyses")
def api_region_analyses():
    """Debug-Endpoint: Zeigt aktuelle Region-Analysen als JSON."""
    return jsonify({
        "analyses_count": len(engine.region_analyses),
        "analyses_loaded_at": engine.region_analyses_loaded_at.isoformat() if engine.region_analyses_loaded_at else None,
        "analyses": engine.region_analyses,
    })


@app.route("/api/regionen-polygone")
def api_regionen_polygone():
    """Region-GeoJSON angereichert mit Analyse-Daten fuer Karten-Faerbung."""
    geojson = get_all_regions_geojson()
    # Analyse-Status an Features anhaengen
    for feature in geojson.get("features", []):
        rid = feature.get("properties", {}).get("id")
        if rid and rid in engine.region_analyses:
            feature["properties"]["analyses"] = engine.region_analyses[rid]
    return jsonify(geojson)


@app.route("/api/refresh-spots", methods=["POST"])
def api_refresh_spots():
    """Laedt Spots neu aus CSV und synchronisiert nach InstantDB."""
    try:
        count = engine.reload_spots()
        return jsonify({"success": True, "spots_count": count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/refresh-weather", methods=["POST"])
def api_refresh_weather():
    """Erzwingt einen Neustart des Wetter-Downloads und baut den Kontext neu."""
    try:
        engine.refresh_weather(force=True)
        spot_names = [k for k in engine.weather_data.keys() if not k.startswith("_")]

        if len(spot_names) == 0:
            return jsonify({
                "success": False,
                "error": "API-Tageslimit erreicht. Keine Wetterdaten verfügbar. Alle alten Analysen wurden zur Sicherheit gelöscht. Bitte morgen erneut versuchen."
            }), 503

        return jsonify({"success": True, "message": "Wetterdaten und Thermik neu berechnet.", "spots_count": len(spot_names)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# STATUS API (Debug)
# ============================================================================

@app.route("/api/status")
def api_status():
    spot_names = [k for k in engine.weather_data.keys() if k != "_meta"]
    return jsonify({
        "weather_loaded": bool(engine.weather_data),
        "spots_count": len(engine.spots),
        "weather_spots": spot_names,
        "weather_loaded_at": engine.weather_loaded_at.isoformat() if engine.weather_loaded_at else None,
        "analyses_count": len(engine.spot_analyses),
        "analyses_loaded_at": engine.analyses_loaded_at.isoformat() if engine.analyses_loaded_at else None,
    })


# ============================================================================
# SPOTS API
# ============================================================================

@app.route("/api/spots")
def api_spots():
    return jsonify(engine.get_spots_geojson())


@app.route("/api/regionen")
def api_regionen():
    """Gibt alle Regionen als GeoJSON FeatureCollection zurück (für Karten-Overlay)."""
    return jsonify(get_all_regions_geojson())


@app.route("/api/region-weather/<region_id>")
def api_region_weather(region_id):
    """Wetterdaten fuer eine Region, formatiert fuer Meteogramm."""
    region_data = engine.region_weather_data.get(region_id)
    if not region_data:
        return jsonify({"error": f"Region '{region_id}' nicht gefunden"}), 404

    hourly_data = region_data.get("hourly_data", {})
    pressure_level_data = region_data.get("pressure_level_data", {})
    elevation_ref = region_data.get("elevation_ref", 1200)

    chart_data = format_data_for_charts(hourly_data, pressure_level_data, elevation_ref=elevation_ref)

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    dates = set()
    for entry in chart_data.get("wind", []):
        try:
            dt = datetime.fromisoformat(entry["time"])
            date_str = dt.strftime("%Y-%m-%d")
            if date_str >= today_str:
                dates.add(date_str)
        except Exception:
            pass

    max_date_str = (now.date() + timedelta(days=config.FORECAST_DAYS - 1)).strftime("%Y-%m-%d")
    sorted_dates = [d for d in sorted(dates) if d <= max_date_str]

    by_day = {}
    for date_str in sorted_dates:
        by_day[date_str] = {"wind": [], "precipitation": [], "thermik": [], "cloudbase": []}
    for key in ["wind", "precipitation", "thermik", "cloudbase"]:
        for entry in chart_data.get(key, []):
            try:
                dt = datetime.fromisoformat(entry["time"])
                date_str = dt.strftime("%Y-%m-%d")
                if date_str in by_day:
                    by_day[date_str][key].append(entry)
            except Exception:
                pass

    return jsonify({
        "region_id": region_id,
        "region_name": region_data.get("region_name", region_id),
        "elevation_ref": elevation_ref,
        "dates": sorted_dates,
        "data": by_day,
    })


@app.route("/api/region-altitude-wind/<region_id>")
def api_region_altitude_wind(region_id):
    """Hoehenwind-Profile fuer eine Region, formatiert fuer Meteogramm."""
    region_data = engine.region_weather_data.get(region_id)
    if not region_data:
        return jsonify({"error": f"Region '{region_id}' nicht gefunden"}), 404

    pressure_level_data = region_data.get("pressure_level_data", {})
    hourly_data = region_data.get("hourly_data", {})
    elevation_ref = region_data.get("elevation_ref", 1200)

    # Multi-Anchor: Spots in Region finden und Anker pro Timestamp sammeln
    gust_anchors_by_time = None
    region_info = find_region_for_point(
        region_data.get("latitude", 0), region_data.get("longitude", 0)
    )
    if region_info is None:
        # Fallback: Region aus source_area per ID suchen
        from source_area import get_all_regions
        for r in get_all_regions():
            if r["id"] == region_id:
                region_info = r
                break

    if region_info and region_info.get("polygon"):
        from shapely.geometry import Point as ShapelyPoint
        region_polygon = region_info["polygon"]
        region_spots = [
            s for s in engine.spots
            if region_polygon.contains(ShapelyPoint(s["longitude"], s["latitude"]))
        ]
        if region_spots:
            gust_anchors_by_time = {}
            for timestamp in pressure_level_data.keys():
                # Nur Spot-Anker für Höhenprofil (keine Referenzpunkt-Bodenböen —
                # Bodenturbulenzen gehören nicht ins atmosphärische Höhenprofil)
                anchors = collect_gust_anchors(
                    region_polygon, region_spots, engine.weather_data, timestamp,
                )
                if anchors:
                    gust_anchors_by_time[timestamp] = anchors

    # Surface anchor: Referenzpunkt-Bodenböen als Ankerpunkt pro Timestamp
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

    alt_data = format_altitude_wind_for_charts(
        pressure_level_data, hourly_data, elevation_ref, region_id,
        gust_anchors_by_time=gust_anchors_by_time,
        surface_anchor_by_time=surface_anchor_by_time,
    )

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    by_day = {}
    for profile in alt_data.get("profiles", []):
        try:
            dt = datetime.fromisoformat(profile["time"])
            date_str = dt.strftime("%Y-%m-%d")
            if date_str >= today_str:
                if date_str not in by_day:
                    by_day[date_str] = []
                by_day[date_str].append({
                    "hour": dt.hour,
                    "profiles": profile["levels"],
                })
        except Exception:
            pass

    max_date_str = (now.date() + timedelta(days=config.FORECAST_DAYS - 1)).strftime("%Y-%m-%d")
    sorted_dates = [d for d in sorted(by_day.keys()) if d <= max_date_str]
    by_day = {d: by_day[d] for d in sorted_dates if d in by_day}

    return jsonify({
        "region_id": region_id,
        "dates": sorted_dates,
        "data": by_day,
    })


# ============================================================================
# WEATHER API (für Meteogramm)
# ============================================================================

def _ensure_spot_weather(spot_name):
    """
    Stellt sicher, dass Wetterdaten für den Spot vorhanden sind.
    Falls nicht (z.B. vorheriger Fetch fehlgeschlagen): On-Demand-Fetch.
    """
    if spot_name in engine.weather_data:
        return engine.weather_data[spot_name]
    spot = next((s for s in engine.spots if s["name"] == spot_name), None)
    if not spot:
        return None
    result = get_weather_for_location(spot_name, spot["latitude"], spot["longitude"])
    if result is None or result[0] is None:
        return None
    hourly_data, pressure_level_data, ref_points = result
    engine.weather_data[spot_name] = {
        "latitude": spot["latitude"],
        "longitude": spot["longitude"],
        "elevation_m": spot["elevation_m"],
        "hourly_data": hourly_data,
        "pressure_level_data": pressure_level_data,
        "reference_points": ref_points,
    }
    return engine.weather_data[spot_name]


@app.route("/api/weather/<spot_name>")
def api_weather(spot_name):
    """Wetterdaten für einen Spot, formatiert für D3.js Meteogramm."""
    spot_data = _ensure_spot_weather(spot_name)
    if not spot_data:
        return jsonify({"error": f"Spot '{spot_name}' nicht gefunden"}), 404

    hourly_data = spot_data.get("hourly_data", {})
    pressure_level_data = spot_data.get("pressure_level_data", {})
    elevation_m = spot_data.get("elevation_m", 850)

    # Finde den Spot für slope_azimuth/angle
    spot_info = None
    for s in engine.spots:
        if s["name"] == spot_name:
            spot_info = s
            break

    chart_data = format_data_for_charts(
        hourly_data, pressure_level_data,
        elevation_ref=elevation_m,
        slope_azimuth=spot_info.get("slope_azimuth") if spot_info else None,
        slope_angle=spot_info.get("slope_angle") if spot_info else None,
    )

    # Gruppiere nach Tagen (nur Heute + Zukunft)
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    
    dates = set()
    for entry in chart_data.get("wind", []):
        try:
            dt = datetime.fromisoformat(entry["time"])
            date_str = dt.strftime("%Y-%m-%d")
            if date_str >= today_str:
                dates.add(date_str)
        except Exception:
            pass

    max_date_str = (now.date() + timedelta(days=config.FORECAST_DAYS - 1)).strftime("%Y-%m-%d")
    sorted_dates = [d for d in sorted(dates) if d <= max_date_str]

    # Gruppiere chart_data nach Tagen
    by_day = {}
    for date_str in sorted_dates:
        by_day[date_str] = {"wind": [], "precipitation": [], "thermik": [], "cloudbase": []}

    for key in ["wind", "precipitation", "thermik", "cloudbase"]:
        for entry in chart_data.get(key, []):
            try:
                dt = datetime.fromisoformat(entry["time"])
                date_str = dt.strftime("%Y-%m-%d")
                if date_str in by_day:
                    by_day[date_str][key].append(entry)
            except Exception:
                pass

    return jsonify({
        "spot_name": spot_name,
        "elevation_m": elevation_m,
        "dates": sorted_dates,
        "data": by_day,
    })


@app.route("/api/altitude-wind/<spot_name>")
def api_altitude_wind(spot_name):
    """Höhenwind-Profile für einen Spot, formatiert für Meteogramm."""
    spot_data = _ensure_spot_weather(spot_name)
    if not spot_data:
        return jsonify({"error": f"Spot '{spot_name}' nicht gefunden"}), 404

    pressure_level_data = spot_data.get("pressure_level_data", {})
    hourly_data = spot_data.get("hourly_data", {})
    elevation_m = spot_data.get("elevation_m")

    # Region-ID für Terrain-Typ Lookup
    region_id = None
    region = find_region_for_point(spot_data.get("latitude", 0), spot_data.get("longitude", 0))
    if region:
        region_id = region["id"]

    alt_data = format_altitude_wind_for_charts(pressure_level_data, hourly_data, elevation_m, region_id)

    # Gruppiere nach Tagen (nur Heute + Zukunft)
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    by_day = {}
    for profile in alt_data.get("profiles", []):
        try:
            dt = datetime.fromisoformat(profile["time"])
            date_str = dt.strftime("%Y-%m-%d")
            if date_str >= today_str:
                if date_str not in by_day:
                    by_day[date_str] = []
                by_day[date_str].append({
                    "hour": dt.hour,
                    "profiles": profile["levels"],
                })
        except Exception:
            pass

    max_date_str = (now.date() + timedelta(days=config.FORECAST_DAYS - 1)).strftime("%Y-%m-%d")
    sorted_dates = [d for d in sorted(by_day.keys()) if d <= max_date_str]
    # Nur Daten für die im Zeitraum liegenden Tage
    by_day = {d: by_day[d] for d in sorted_dates if d in by_day}
    return jsonify({
        "spot_name": spot_name,
        "dates": sorted_dates,
        "data": by_day,
    })


# ============================================================================
# FÖHN API
# ============================================================================

@app.route("/api/foehn")
def api_foehn():
    """Föhn-Zeitreihe: stündliche Delta-P, Kammwind, Feuchte für Diagramm."""
    raw = None
    if engine and engine.foehn_data:
        raw = engine.foehn_data
    else:
        raw = fetch_foehn_data(forecast_days=config.FORECAST_DAYS)

    if not raw:
        return jsonify({"error": "Föhn-Daten nicht verfügbar"}), 503

    nord = raw["nord"]
    sued = raw["sued"]
    h_nord = nord.get("hourly", {})
    h_sued = sued.get("hourly", {})
    times = h_nord.get("time", [])

    if not times:
        return jsonify({"error": "Keine Zeitreihe"}), 503

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    by_day = {}
    for i, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
        except Exception:
            continue

        date_str = dt.strftime("%Y-%m-%d")
        if date_str < today_str:
            continue

        p_nord = _safe_get(h_nord.get("pressure_msl"), i)
        p_sued = _safe_get(h_sued.get("pressure_msl"), i)
        delta_p = round(p_sued - p_nord, 1) if p_nord is not None and p_sued is not None else None

        wind_700 = _safe_get(h_nord.get("wind_speed_700hPa"), i)
        dir_700 = _safe_get(h_nord.get("wind_direction_700hPa"), i)
        rh_nord = _safe_get(h_nord.get("relative_humidity_2m"), i)

        # Determine level via evaluate_foehn
        ev = evaluate_foehn(nord, sued, time_index=i)

        entry = {
            "time": t,
            "hour": dt.hour,
            "delta_p": delta_p,
            "level": ev["level"],
            "crest_wind_kmh": round(wind_700, 0) if wind_700 is not None else None,
            "crest_dir_deg": round(dir_700, 0) if dir_700 is not None else None,
            "humidity_nord": round(rh_nord, 0) if rh_nord is not None else None,
        }

        if date_str not in by_day:
            by_day[date_str] = []
        by_day[date_str].append(entry)

    sorted_dates = sorted(by_day.keys())

    return jsonify({
        "dates": sorted_dates,
        "data": by_day,
        "thresholds": {
            "delta_p_caution": THRESHOLD_DELTA_P_CAUTION,
            "delta_p_danger": THRESHOLD_DELTA_P_DANGER,
            "humidity_low": THRESHOLD_HUMIDITY_LOW,
        },
        "stations": FOEHN_STATIONS,
    })


def _safe_get(arr, i):
    """Sicher einen Wert aus einer Liste holen."""
    if arr is None or not isinstance(arr, list) or i >= len(arr):
        return None
    return arr[i]


# ============================================================================
# DATA FORMATTING (adaptiert von uetliberg_ticker/web.py)
# ============================================================================

def format_data_for_charts(hourly_data, pressure_level_data=None, elevation_ref=None,
                           slope_azimuth=None, slope_angle=None):
    """Formatiert Daten für D3.js Charts inkl. Thermik-Physik."""
    chart_data = {"wind": [], "precipitation": [], "thermik": [], "cloudbase": []}
    sorted_times = sorted(hourly_data.keys())

    prev_max_h = None
    prev_day = None
    cumulative_bf = 0.0       # Kumulierter Buoyancy-Flux (Encroachment-Modell)
    peak_H = 0.0              # Tages-Maximum des sensiblen Wärmeflusses
    peak_sw = 0.0             # Tages-Maximum der Globalstrahlung (W/m²)

    for timestamp in sorted_times:
        current_day = timestamp[:10]
        if current_day != prev_day:
            prev_max_h = None
            cumulative_bf = 0.0       # Reset pro Tag
            peak_H = 0.0             # Reset pro Tag
            peak_sw = 0.0            # Reset pro Tag
            prev_day = current_day
            
        data = hourly_data[timestamp]
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            time_str = dt.strftime("%Y-%m-%dT%H:%M:%S")

            # Wind
            wind_speed = data.get("wind_speed_10m")
            wind_gusts = data.get("wind_gusts_10m")
            wind_direction = data.get("wind_direction_10m")
            if wind_speed is not None and wind_direction is not None:
                chart_data["wind"].append({
                    "time": time_str,
                    "speed": wind_speed,
                    "gusts": wind_gusts if wind_gusts is not None else wind_speed,
                    "direction": wind_direction,
                })

            # Niederschlag
            precipitation = data.get("precipitation", 0)
            precip_prob = data.get("precipitation_probability", 0)
            if precipitation is not None:
                chart_data["precipitation"].append({
                    "time": time_str,
                    "amount": precipitation,
                    "probability": precip_prob if precip_prob is not None else 0,
                    "weather_code": data.get("weather_code"),
                })

            # Thermik
            cape = data.get("cape", 0)
            p_levels = []
            if pressure_level_data and timestamp in pressure_level_data:
                for level in config.PRESSURE_LEVELS:
                    h_val = pressure_level_data[timestamp].get(f"geopotential_height_{level}hPa")
                    t_val = pressure_level_data[timestamp].get(f"temperature_{level}hPa")
                    if h_val is not None and t_val is not None:
                        p_levels.append({"pressure": level, "height": h_val, "temp": t_val})

            surf_temp = data.get("temperature_2m")
            surf_dew = calculate_dewpoint(surf_temp, data.get("relative_humidity_2m", 50))
            elev_ref = elevation_ref if elevation_ref is not None else 850

            therm_climb = 0
            therm_rating = 0
            therm_max_h = None
            therm_diagnostics = {}
            therm_warnings = []

            if surf_temp is not None and p_levels:
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
                    timestamp=timestamp,
                    slope_azimuth=slope_azimuth,
                    slope_angle=slope_angle,
                    low_cloud=data.get("cloud_cover_low", 0),
                    mid_cloud=data.get("cloud_cover_mid", 0),
                    high_cloud=data.get("cloud_cover_high", 0),
                    boundary_layer_height_gfs=data.get("boundary_layer_height_gfs"),
                    previous_max_height=prev_max_h,
                    cumulative_buoyancy=cumulative_bf,
                    peak_H=peak_H,
                    peak_shortwave=peak_sw,
                )
                if "error" not in therm:
                    therm_climb = therm["climb_rate"]
                    therm_rating = therm["rating"]
                    therm_max_h = therm["max_height"]
                    prev_max_h = therm_max_h
                    therm_diagnostics = therm.get("diagnostics", {})
                    therm_warnings = therm.get("data_warnings", [])
                    # Buoyancy akkumulieren (Encroachment-Modell)
                    cumulative_bf += therm_diagnostics.get("buoyancy_contribution", 0)
                    # Peak-H für H-skalierte Inertia tracken
                    current_H = therm_diagnostics.get("sensible_heat_flux", 0)
                    peak_H = max(peak_H, current_H)
                    sw = data.get("shortwave_radiation")
                    if sw is not None:
                        peak_sw = max(peak_sw, sw)

            # Wolkenbasis + Schichten
            cloud_base = data.get("cloud_base")
            cloud_cover = data.get("cloud_cover")
            cloud_cover_low = data.get("cloud_cover_low")
            cloud_cover_mid = data.get("cloud_cover_mid")
            cloud_cover_high = data.get("cloud_cover_high")

            # Nutzbare Thermikhoehe an Wolkenbasis kappen
            if (therm_max_h and cloud_base and cloud_base > elev_ref
                    and therm_max_h > cloud_base):
                therm_max_h = cloud_base

            if cape is not None:
                chart_data["thermik"].append({
                    "time": time_str,
                    "cape": cape,
                    "climb_rate": therm_climb,
                    "rating": therm_rating,
                    "max_height": therm_max_h,
                    "diagnostics": therm_diagnostics,
                    "data_warnings": therm_warnings,
                })

            if cloud_base is not None or cloud_cover is not None:
                chart_data["cloudbase"].append({
                    "time": time_str,
                    "height": cloud_base,
                    "cover": cloud_cover,
                    "cover_low": cloud_cover_low,
                    "cover_mid": cloud_cover_mid,
                    "cover_high": cloud_cover_high,
                    "weather_code": data.get("weather_code"),
                })
        except Exception:
            continue

    return chart_data


def _interp_scalar(pts, x):
    """Linear interpolation of a scalar value from sorted (x, y) pairs."""
    if not pts:
        return 0
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for i in range(len(pts) - 1):
        if pts[i][0] <= x <= pts[i + 1][0]:
            dh = pts[i + 1][0] - pts[i][0]
            frac = (x - pts[i][0]) / dh if dh > 0 else 0
            return pts[i][1] + frac * (pts[i + 1][1] - pts[i][1])
    return pts[-1][1]


def _interp_ws(pts, x):
    """Linear interpolation of (wind_speed, direction, temperature) from sorted tuples."""
    if not pts:
        return 0, 0, 0
    if x <= pts[0][0]:
        return pts[0][1], pts[0][2], pts[0][3]
    if x >= pts[-1][0]:
        return pts[-1][1], pts[-1][2], pts[-1][3]
    for i in range(len(pts) - 1):
        if pts[i][0] <= x <= pts[i + 1][0]:
            lo, hi = pts[i], pts[i + 1]
            dh = hi[0] - lo[0]
            frac = (x - lo[0]) / dh if dh > 0 else 0
            return (
                lo[1] + frac * (hi[1] - lo[1]),
                lo[2] + frac * (hi[2] - lo[2]),
                lo[3] + frac * (hi[3] - lo[3]),
            )
    return pts[-1][1], pts[-1][2], pts[-1][3]


def _oi_gust_correction(grid_alts, grid_gusts, grid_ws, anchors, L_up, L_down):
    """Optimal Interpolation des Böen-Exzesses aus Anker-Beobachtungen.

    Der beobachtete Böen-Exzess (gust - wind) an Ankerpunkten wird per
    asymmetrischem Gauss-Kernel auf das Höhenprofil verteilt:
    - Aufwärts: terrain-abhängiger Kernel (L_up aus TERRAIN_OI_L_UP)
      Flach (mittelland): 3×H_g ≈ 1050m (Oberflächenrauigkeit)
      Bergig (voralpen+): 5×H_g ≈ 2100-2500m (orographische Schwerewellen,
      Dörnbrack & Nappo 1997, Sharman et al. 2012)
    - Abwärts: enger Kernel (L_down = H_g, Turbulenz zerfällt schnell)

    Args:
        grid_alts: Liste der Grid-Höhen (m MSL)
        grid_gusts: Liste der Modell-Böen (km/h) auf dem Grid
        grid_ws: Liste der Wind-Geschwindigkeiten (km/h) auf dem Grid
        anchors: Liste [{elevation_m, gust_kmh, wind_speed_kmh}, ...]
        L_up: Korrelationslänge aufwärts (m), aus get_oi_scale_lengths()
        L_down: Korrelationslänge abwärts (m), typisch = H_g

    Returns:
        Liste der korrigierten Böen (km/h), gleiche Länge wie grid_alts
    """
    import math

    if not anchors or L_up <= 0:
        return list(grid_gusts)

    # Beobachteter Böen-Exzess an jedem Anker
    obs_excess = []
    for a in anchors:
        excess = max(0, a["gust_kmh"] - a.get("wind_speed_kmh", 0))
        obs_excess.append((a["elevation_m"], excess))

    corrected = []
    for z, gust_bg, ws in zip(grid_alts, grid_gusts, grid_ws):
        w_sum = 0.0
        excess_sum = 0.0
        for z_a, exc in obs_excess:
            dz = z - z_a
            # Asymmetrischer Kernel: breit aufwärts (BLH), eng abwärts (H_g)
            L = L_up if dz >= 0 else L_down
            w = math.exp(-(dz * dz) / (2 * L * L))
            w_sum += w
            excess_sum += w * exc
        excess_weighted = excess_sum / max(1.0, w_sum)
        gust_from_obs = ws + excess_weighted
        corrected.append(max(gust_bg, gust_from_obs))

    return corrected


def format_altitude_wind_for_charts(pressure_level_data, hourly_data=None, elevation_m=None,
                                    region_id=None, gust_anchors_by_time=None,
                                    surface_anchor_by_time=None):
    """Formatiert Höhenwind-Daten für D3.js Altitude Profile Chart.

    Args:
        pressure_level_data: Druckniveau-Daten pro Timestamp
        hourly_data: Stündliche Bodendaten (für wind_speed_10m, wind_gusts_10m, boundary_layer_height)
        elevation_m: Spot-Elevation in m MSL (für Höhenböen-Berechnung)
        region_id: Regions-ID für terrain_type Lookup (optional)
        gust_anchors_by_time: Dict {timestamp: [anchor, ...]} für Multi-Anchor-Modell (optional)
        surface_anchor_by_time: Dict {timestamp: {elevation_m, gust_kmh, wind_speed_kmh}}
            Referenzpunkt-Bodenböen als Ankerpunkt ins Höhenprofil (optional, für Regionen)
    """
    chart_data = {"profiles": []}
    sorted_times = sorted(pressure_level_data.keys())

    # Grid: 0-4000m in 250m steps
    GRID_STEP = 250
    GRID_MAX = 4000

    for timestamp in sorted_times:
        data = pressure_level_data[timestamp]
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            profile = {"time": dt.isoformat(), "levels": []}

            for level in config.PRESSURE_LEVELS:
                height = data.get(f"geopotential_height_{level}hPa")
                wind_speed = data.get(f"wind_speed_{level}hPa")
                wind_direction = data.get(f"wind_direction_{level}hPa")
                temperature = data.get(f"temperature_{level}hPa")

                if height is not None:
                    profile["levels"].append({
                        "pressure": level,
                        "altitude": height,
                        "wind_speed": wind_speed if wind_speed is not None else 0.0,
                        "wind_direction": wind_direction if wind_direction is not None else 0,
                        "temperature": temperature if temperature is not None else 0,
                    })

            # Compute altitude gusts
            if hourly_data and elevation_m is not None and profile["levels"]:
                surface = hourly_data.get(timestamp, {})
                anchors = gust_anchors_by_time.get(timestamp, []) if gust_anchors_by_time else []

                if anchors:
                    # Multi-Anchor-Modell: Spots als Böen-Ankerpunkte
                    profile["levels"] = estimate_altitude_gusts_multi_anchor(
                        anchors=anchors,
                        pressure_levels_data=profile["levels"],
                        elevation_ref=elevation_m,
                        boundary_layer_height=surface.get("boundary_layer_height"),
                        region_id=region_id,
                    )
                else:
                    # Fallback: Einzel-Referenzpunkt-Modell
                    profile["levels"] = estimate_altitude_gusts(
                        wind_speed_10m=surface.get("wind_speed_10m"),
                        wind_gusts_10m=surface.get("wind_gusts_10m"),
                        pressure_levels_data=profile["levels"],
                        elevation_m=elevation_m,
                        boundary_layer_height=surface.get("boundary_layer_height"),
                        region_id=region_id,
                    )

            # Surface anchor: re-grid onto 0-4000m and apply OI gust correction.
            #
            # Method (simplified Optimal Interpolation):
            # 1. Interpolate pressure-level model data onto regular grid
            # 2. Collect all anchor points (surface + spot anchors)
            # 3. Compute residuals: observed_gust - model_gust at each anchor
            # 4. Distribute corrections smoothly via Gaussian kernel (L = max(H_g, BLH))
            # 5. Result: model is pulled toward observations, no V-shape artifacts
            anchor = surface_anchor_by_time.get(timestamp) if surface_anchor_by_time else None
            if anchor and profile["levels"]:
                elev_anchor = anchor["elevation_m"]

                levels = sorted(profile["levels"], key=lambda l: l["altitude"])

                # Wind/dir/temp: rein aus Drucklevel-Daten (freie Atmosphäre).
                # Der Anker-Bodenwind wird NICHT eingefügt — er ist terrain-
                # geschützt (10m AGL) und würde einen künstlichen Dip erzeugen.
                ws_pts = []
                for lv in levels:
                    ws_pts.append((
                        lv["altitude"],
                        lv.get("wind_speed", 0),
                        lv.get("wind_direction", 0),
                        lv.get("temperature", 0),
                    ))

                # Gust support points from gust_calculator (model background)
                gust_pts = sorted(
                    [(lv["altitude"], lv.get("wind_gusts", lv.get("wind_speed", 0)))
                     for lv in levels],
                    key=lambda x: x[0],
                )

                # Build grid: wind_speed/dir/temp + model gusts
                grid_alts = []
                grid_gusts_bg = []
                grid_ws = []
                grid_dir = []
                grid_temp = []
                for grid_alt in range(0, GRID_MAX + 1, GRID_STEP):
                    ws_val, dir_val, temp_val = _interp_ws(ws_pts, grid_alt)
                    gust_val = _interp_scalar(gust_pts, grid_alt)
                    grid_alts.append(grid_alt)
                    grid_gusts_bg.append(gust_val)
                    grid_ws.append(ws_val)
                    grid_dir.append(dir_val)
                    grid_temp.append(temp_val)

                # OI-Anker: Böen-Exzess relativ zum freiatmosphärischen Wind
                # (nicht zum Boden-Wind). So wird der Exzess korrekt auf das
                # Drucklevel-Windprofil addiert ohne Doppelzählung.
                ws_free_atm = _interp_scalar(
                    [(p[0], p[1]) for p in ws_pts], elev_anchor
                )
                oi_anchors = [{
                    "elevation_m": elev_anchor,
                    "gust_kmh": anchor["gust_kmh"],
                    "wind_speed_kmh": ws_free_atm,
                }]
                spot_anchors = gust_anchors_by_time.get(timestamp, []) if gust_anchors_by_time else []
                for sa in spot_anchors:
                    sa_ws_free = _interp_scalar(
                        [(p[0], p[1]) for p in ws_pts], sa["elevation_m"]
                    )
                    oi_anchors.append({
                        "elevation_m": sa["elevation_m"],
                        "gust_kmh": sa["gust_kmh"],
                        "wind_speed_kmh": sa_ws_free,
                    })

                # OI correlation lengths (terrain-abhängig):
                # L_up: orographische Schwerewellen-Skala (voralpen/alpen: 5×H_g)
                #   oder BLH wenn grösser (konvektive Durchmischung Nachmittag)
                # L_down = H_g: Turbulenz-Zerfall abwärts
                L_up_terrain, L_down = get_oi_scale_lengths(elev_anchor, region_id)
                sfc = hourly_data.get(timestamp, {}) if hourly_data else {}
                blh = sfc.get("boundary_layer_height") or sfc.get("boundary_layer_height_gfs") or 0
                L_up = max(L_up_terrain, blh)
                grid_gusts_oi = _oi_gust_correction(
                    grid_alts, grid_gusts_bg, grid_ws, oi_anchors, L_up, L_down,
                )

                # Assemble grid levels
                grid_levels = []
                for i, grid_alt in enumerate(grid_alts):
                    gust_final = max(grid_gusts_oi[i], grid_ws[i])
                    grid_levels.append({
                        "altitude": grid_alt,
                        "wind_speed": round(grid_ws[i], 1),
                        "wind_gusts": round(gust_final, 1),
                        "wind_direction": round(grid_dir[i]),
                        "temperature": round(grid_temp[i], 1),
                    })

                # Monoton steigende Böen: Jede Höhe hat mindestens so
                # starke Böen wie die darunter (mehr Exposition, weniger
                # Abschirmung). Physik: Stull 1988, mixed-layer Turbulenz.
                running_max = 0.0
                for lv in grid_levels:
                    running_max = max(running_max, lv["wind_gusts"])
                    lv["wind_gusts"] = running_max

                profile["levels"] = grid_levels

            if len(profile["levels"]) >= 2:
                chart_data["profiles"].append(profile)
        except Exception:
            continue

    return chart_data
