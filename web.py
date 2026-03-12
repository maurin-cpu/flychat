"""
Flask Web-Server für Flychat.
Routes: Chat-API, Spots-API, Wetter-API, Meteogramm-API.
"""

import os
from flask import Flask, render_template, request, jsonify, redirect, url_for
from datetime import datetime

import config
from thermik_calculator import calculate_thermal_profile, calculate_dewpoint
from source_area import get_all_regions_geojson
from fetch_weather import get_weather_for_location

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "flychat-dev-key")

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
    return render_template("index.html")


@app.route("/chat")
def chat_page():
    return render_template("index.html")


@app.route("/map")
def map_page():
    return render_template("index.html")


@app.route("/analyses")
def analyses_page():
    return render_template("analyses.html", instantdb_app_id=config.INSTANTDB_APP_ID)


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
        return jsonify({"success": True, "message": "Wetterdaten und Thermik neu berechnet."})
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

    # Gruppiere nach Tagen
    dates = set()
    for entry in chart_data.get("wind", []):
        try:
            dt = datetime.fromisoformat(entry["time"])
            dates.add(dt.strftime("%Y-%m-%d"))
        except Exception:
            pass

    sorted_dates = sorted(dates)

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
    alt_data = format_altitude_wind_for_charts(pressure_level_data)

    # Gruppiere nach Tagen
    by_day = {}
    for profile in alt_data.get("profiles", []):
        try:
            dt = datetime.fromisoformat(profile["time"])
            date_str = dt.strftime("%Y-%m-%d")
            if date_str not in by_day:
                by_day[date_str] = []
            by_day[date_str].append({
                "hour": dt.hour,
                "profiles": profile["levels"],
            })
        except Exception:
            pass

    sorted_dates = sorted(by_day.keys())
    return jsonify({
        "spot_name": spot_name,
        "dates": sorted_dates,
        "data": by_day,
    })


# ============================================================================
# DATA FORMATTING (adaptiert von uetliberg_ticker/web.py)
# ============================================================================

def format_data_for_charts(hourly_data, pressure_level_data=None, elevation_ref=None,
                           slope_azimuth=None, slope_angle=None):
    """Formatiert Daten für D3.js Charts inkl. Thermik-Physik."""
    chart_data = {"wind": [], "precipitation": [], "thermik": [], "cloudbase": []}
    sorted_times = sorted(hourly_data.keys())

    for timestamp in sorted_times:
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
                )
                if "error" not in therm:
                    therm_climb = therm["climb_rate"]
                    therm_rating = therm["rating"]
                    therm_max_h = therm["max_height"]
                    therm_diagnostics = therm.get("diagnostics", {})
                    therm_warnings = therm.get("data_warnings", [])

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


def format_altitude_wind_for_charts(pressure_level_data):
    """Formatiert Höhenwind-Daten für D3.js Altitude Profile Chart."""
    chart_data = {"profiles": []}
    sorted_times = sorted(pressure_level_data.keys())

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

                if height is not None and wind_speed is not None:
                    profile["levels"].append({
                        "pressure": level,
                        "altitude": height,
                        "wind_speed": wind_speed,
                        "wind_direction": wind_direction if wind_direction is not None else 0,
                        "temperature": temperature if temperature is not None else 0,
                    })

            if len(profile["levels"]) >= 3:
                chart_data["profiles"].append(profile)
        except Exception:
            continue

    return chart_data
