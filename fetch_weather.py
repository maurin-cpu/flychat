"""
Wetterdaten-Aggregation für Flychat.
Adaptiert von uetliberg_ticker/fetch_weather.py - Multi-Spot Support.

Generalisierte Source-Area Aggregation:
- Wolken: 30%-Perzentil (Regtherm-Gewichtung) -> findet regionale Sonnenfenster
- Alle anderen Parameter: Flächenmittel (Spatial Mean)
- Referenzpunkte kommen aus source_area.py (GeoJSON / SPOT_CONFIG)
"""

import requests
import json
import os
import time
from datetime import datetime

import config

# Verzögerung zwischen API-Aufrufen (Open-Meteo Rate-Limit: Multi-Location-Requests zählen stärker)
API_DELAY_BETWEEN_CALLS = 1.5  # Sekunden
API_DELAY_BETWEEN_SPOTS = 2.5  # Sekunden
from thermik_calculator import calculate_thermal_profile, calculate_dewpoint
from source_area import get_reference_points


def get_weather_for_location(location_name, latitude, longitude):
    """
    Ruft stündliche Wettervorhersage ab (Hybrid-Modell: WIND_MODEL + THERMAL_MODEL + GFS).
    Nutzt 5-Punkt Source-Area-Raster mit regionaler Wolken-Aggregation (30%-Perzentil).
    Gibt (hourly_data, pressure_level_data, reference_points) zurück.
    """
    pl_params = ",".join(config.PRESSURE_LEVEL_PARAMS)
    
    ref_points = get_reference_points(location_name, latitude, longitude)
    
    lat_str = ",".join(str(round(p[0], 4)) for p in ref_points)
    lon_str = ",".join(str(round(p[1], 4)) for p in ref_points)

    params_wind = {
        "latitude": lat_str,
        "longitude": lon_str,
        "models": config.WIND_MODEL,
        "hourly": ",".join(config.HOURLY_PARAMS) + "," + pl_params,
        "forecast_days": config.FORECAST_DAYS,
        "timezone": config.TIMEZONE,
    }

    params_thermal = {
        "latitude": lat_str,
        "longitude": lon_str,
        "models": config.THERMAL_MODEL,
        "hourly": ",".join(config.HOURLY_PARAMS) + "," + pl_params,
        "forecast_days": config.FORECAST_DAYS,
        "timezone": config.TIMEZONE,
    }
    
    CLOUD_PARAMS = {"cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high"}
    PRECIP_USE_MIN = {"precipitation", "rain", "precipitation_probability"}

    def _aggregate_regional_data(data_list):
        """
        Generalisierte Source-Area Aggregation:
        - Wolken: 30%-Perzentil -> findet regionale Sonnenfenster (Blue Holes)
        - Niederschlag: Regionale Signifikanz (mind. 2 von N Punkten > 0.1, sonst 0.0)
        - Temperatur, Strahlung, Druckniveaus: SPOT-Punkt (data_list[0]) behalten!
          Thermik haengt von den Bedingungen AM Startplatz ab, nicht vom Regionalmittel.
          Burnair/XC Therm nutzen ebenfalls den Spot-Punkt fuer die Thermik-Berechnung.
        """
        if not data_list or not isinstance(data_list, list): return data_list
        primary = data_list[0]  # Spot-Punkt = erste Koordinate
        if "hourly" not in primary: return primary

        PRECIP_THRESHOLD = 0.1   # mm oder %
        PRECIP_MIN_POINTS = 2    # mind. 2 von N Punkten muessen > Schwellenwert sein

        all_params = [k for k in primary["hourly"].keys() if k != "time"]
        num_hours = len(primary["hourly"].get("time", []))
        
        for i in range(num_hours):
            # Wolken: 30%-Perzentil (NWP ueberschaetzt Wolken in Bergen systematisch)
            point_cloud_values = []
            for d in data_list:
                h = d.get("hourly", {})
                raw_low = h.get("cloud_cover_low", [None])[i] if i < len(h.get("cloud_cover_low", [])) else None
                raw_mid = h.get("cloud_cover_mid", [None])[i] if i < len(h.get("cloud_cover_mid", [])) else None
                raw_high = h.get("cloud_cover_high", [None])[i] if i < len(h.get("cloud_cover_high", [])) else None
                raw_total = h.get("cloud_cover", [None])[i] if i < len(h.get("cloud_cover", [])) else None
                if raw_low is None or raw_mid is None or raw_high is None or raw_total is None:
                    continue
                score = (raw_low * 1.0) + (raw_mid * 0.7) + (raw_high * 0.25)
                point_cloud_values.append({
                    "score": score, "low": raw_low, "mid": raw_mid, "high": raw_high,
                    "total": raw_total
                })

            if point_cloud_values:
                point_cloud_values.sort(key=lambda x: x["score"])
                target_idx = 1 if len(point_cloud_values) >= 4 else 0
                rep = point_cloud_values[target_idx]
                primary["hourly"]["cloud_cover_low"][i] = int(rep["low"])
                primary["hourly"]["cloud_cover_mid"][i] = int(rep["mid"])
                primary["hourly"]["cloud_cover_high"][i] = int(rep["high"])
                primary["hourly"]["cloud_cover"][i] = int(rep["total"])
            
            # Nur Wolken + Niederschlag aggregieren; Rest = Spot-Punkt (primary bleibt)
            for k in all_params:
                if k in CLOUD_PARAMS:
                    continue
                if k in PRECIP_USE_MIN:
                    vals = [d["hourly"].get(k, [None])[i] for d in data_list if i < len(d.get("hourly", {}).get(k, []))]
                    valid_vals = [v for v in vals if v is not None]
                    if valid_vals:
                        points_above = sum(1 for v in valid_vals if v > PRECIP_THRESHOLD)
                        if points_above >= PRECIP_MIN_POINTS:
                            primary["hourly"][k][i] = sum(valid_vals) / len(valid_vals)
                        else:
                            primary["hourly"][k][i] = 0.0
        return primary

    try:
        data_wind = None
        try:
            print(f"  [INFO] Wind-Modell {config.WIND_MODEL} ({len(ref_points)}-Punkte) für {location_name}...")
            resp_wind = requests.get(config.API_URL, params=params_wind, timeout=config.API_TIMEOUT)
            resp_wind.raise_for_status()
            res_json = resp_wind.json()
            data_wind_list = res_json if isinstance(res_json, list) else [res_json]
            data_wind = _aggregate_regional_data(data_wind_list)
        except requests.exceptions.RequestException as e:
            print(f"  [WARN] Wind-Modell {config.WIND_MODEL} fehlgeschlagen: {e}")

        data_thermal = None
        time.sleep(API_DELAY_BETWEEN_CALLS)
        try:
            print(f"  [INFO] Thermik-Modell {config.THERMAL_MODEL} ({len(ref_points)}-Punkte) für {location_name}...")
            resp_thermal = requests.get(config.API_URL, params=params_thermal, timeout=config.API_TIMEOUT)
            resp_thermal.raise_for_status()
            res_json = resp_thermal.json()
            data_thermal_list = res_json if isinstance(res_json, list) else [res_json]
            data_thermal = _aggregate_regional_data(data_thermal_list)
        except requests.exceptions.RequestException as e:
            print(f"  [WARN] Thermik-Modell {config.THERMAL_MODEL} fehlgeschlagen: {e}")

        hourly_wind = data_wind.get("hourly", {}) if data_wind else {}
        hourly_thermal = data_thermal.get("hourly", {}) if data_thermal else {}

        # Basis für Thermik/Wolken: THERMAL_MODEL; Fallback: WIND_MODEL
        hourly_base = hourly_thermal or hourly_wind
        times_base = hourly_base.get("time", [])
        if not times_base:
            print(f"  [WARN] Keine Basisdaten für {location_name}")
            return None, None, ref_points

        hourly_data = {}
        pressure_level_data = {}

        for i, time_str in enumerate(times_base):
            entry = {}
            for param in config.HOURLY_PARAMS:
                val = hourly_base.get(param, [None])[i] if i < len(hourly_base.get(param, [])) else None
                entry[param] = val
            hourly_data[time_str] = entry

            pl_entry = {}
            for param in config.PRESSURE_LEVEL_PARAMS:
                val = hourly_base.get(param, [None])[i] if i < len(hourly_base.get(param, [])) else None
                pl_entry[param] = val
            pressure_level_data[time_str] = pl_entry

        # Wind aus WIND_MODEL überlagern (Boden + Höhenwind) für bessere lokale Windtreue
        wind_surface_params = ["wind_speed_10m", "wind_direction_10m", "wind_gusts_10m"]
        wind_pl_params = [
            p for p in config.PRESSURE_LEVEL_PARAMS
            if p.startswith("wind_speed_") or p.startswith("wind_direction_") or p.startswith("geopotential_height_")
        ]

        times_wind = hourly_wind.get("time", []) if hourly_wind else []
        for i, time_str in enumerate(times_wind):
            if time_str not in hourly_data: continue
            for param in wind_surface_params:
                val_w = hourly_wind.get(param, [None])[i] if i < len(hourly_wind.get(param, [])) else None
                if val_w is not None:
                    hourly_data[time_str][param] = val_w
            if time_str in pressure_level_data:
                for param in wind_pl_params:
                    val_w = hourly_wind.get(param, [None])[i] if i < len(hourly_wind.get(param, [])) else None
                    if val_w is not None:
                        pressure_level_data[time_str][param] = val_w

        for time_str in hourly_data:
            cb = hourly_data[time_str].get("cloud_base")
            if cb is not None and cb > 6000:
                hourly_data[time_str]["cloud_base"] = None

        time.sleep(API_DELAY_BETWEEN_CALLS)
        try:
            params_gfs = {
                "latitude": latitude,
                "longitude": longitude,
                "hourly": ",".join(config.GFS_SUPPLEMENTARY_PARAMS),
                "models": "gfs_seamless",
                "forecast_days": config.FORECAST_DAYS,
                "timezone": config.TIMEZONE,
            }
            resp_gfs = requests.get(config.API_URL, params=params_gfs, timeout=10)
            resp_gfs.raise_for_status()
            hourly_gfs = resp_gfs.json().get("hourly", {})
            gfs_times = hourly_gfs.get("time", [])
            filled = 0
            for i, ts in enumerate(gfs_times):
                if ts in hourly_data:
                    for p in config.GFS_SUPPLEMENTARY_PARAMS:
                        if hourly_data[ts].get(p) is None:
                            val = hourly_gfs.get(p, [None])[i] if i < len(hourly_gfs.get(p, [])) else None
                            if val is not None:
                                hourly_data[ts][p] = val
                                filled += 1
            print(f"  [INFO] GFS-Supplement: {filled} Werte aufgefüllt")
        except Exception as e:
            print(f"  [WARN] GFS-Supplement fehlgeschlagen: {e}")

        elevation = 0
        if data_thermal:
            elevation = data_thermal.get("elevation", 0)
        elif data_wind:
            elevation = data_wind.get("elevation", 0)
        for ts, data in hourly_data.items():
            temp = data.get("temperature_2m")
            rh = data.get("relative_humidity_2m", 50)
            radiation = data.get("direct_radiation")
            bl_height = data.get("boundary_layer_height", 0)
            
            if temp is not None and radiation is not None and radiation > 50:
                dewpoint = calculate_dewpoint(temp, rh)
                
                p_level_list = []
                pl_data = pressure_level_data.get(ts, {})
                for level in config.PRESSURE_LEVELS:
                    h_val = pl_data.get(f"geopotential_height_{level}hPa")
                    t_val = pl_data.get(f"temperature_{level}hPa")
                    if h_val is not None and t_val is not None:
                        p_level_list.append({"pressure": level, "height": h_val, "temp": t_val})

                profile = calculate_thermal_profile(
                    surface_temp=temp,
                    surface_dewpoint=dewpoint,
                    elevation_m=elevation,
                    pressure_levels_data=p_level_list,
                    boundary_layer_height_agl=bl_height,
                    direct_radiation=radiation,
                    timestamp=ts,
                    low_cloud=data.get("cloud_cover_low", 0),
                    mid_cloud=data.get("cloud_cover_mid", 0),
                    high_cloud=data.get("cloud_cover_high", 0)
                )
                climb_rate = profile.get("climb_rate", 0) if profile else 0
                
                # THERMIK PROXY CALCULATION
                # (Hier bleibt die Logik für climb_rate erhalten, aber der künstliche Burn-Off entfällt)
                # Die Bewölkung wird nun spatial über das Minimum-Prinzip geregelt.
                        
        print(f"  [INFO] {len(hourly_data)} Zeitstempel für {location_name} (Source-Area: {len(ref_points)} Punkte)")
        return hourly_data, pressure_level_data, ref_points

    except requests.exceptions.RequestException as e:
        print(f"  [FEHLER] API-Fehler für {location_name}: {e}")
        return None, None, ref_points
    except Exception as e:
        import traceback
        print(f"  [FEHLER] Unerwarteter Fehler für {location_name}: {e}")
        traceback.print_exc()
        return None, None, ref_points


def fetch_all_spots(spots, save_to_file=True):
    """
    Holt Wetterdaten für ALLE Spots und speichert sie in einer JSON-Datei.
    Returns: Dict mit allen Spot-Daten.
    """
    all_data = {
        "_meta": {
            "last_updated": datetime.now().isoformat(),
            "spots_count": len(spots),
        }
    }

    for i, spot in enumerate(spots):
        if i > 0:
            time.sleep(API_DELAY_BETWEEN_SPOTS)
        name = spot["name"]
        print(f"[INFO] Lade Wetterdaten für {name} ({spot['fluggebiet']})...")

        result = get_weather_for_location(name, spot["latitude"], spot["longitude"])

        if result is None or result[0] is None:
            print(f"[WARN] Keine Daten für {name}")
            continue

        hourly_data, pressure_level_data, ref_points = result
        all_data[name] = {
            "latitude": spot["latitude"],
            "longitude": spot["longitude"],
            "elevation_m": spot["elevation_m"],
            "hourly_data": hourly_data,
            "pressure_level_data": pressure_level_data,
            "reference_points": ref_points,
        }

    if save_to_file:
        config.WEATHER_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(config.WEATHER_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(all_data, f, indent=2, ensure_ascii=False)
        print(f"[INFO] Wetterdaten gespeichert: {config.WEATHER_JSON_PATH}")

    return all_data


def load_cached_weather():
    """Lade gecachte Wetterdaten aus JSON."""
    if not config.WEATHER_JSON_PATH.exists():
        return None
    with open(config.WEATHER_JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def is_cache_fresh(max_age_hours=12):
    """Prüft ob der Cache noch frisch genug ist."""
    if not config.WEATHER_JSON_PATH.exists():
        return False
    data = load_cached_weather()
    if not data or "_meta" not in data:
        return False
    # Mindestens ein Spot mit hourly_data muss vorhanden sein
    spot_keys = [k for k in data.keys() if k != "_meta"]
    if not spot_keys:
        return False
    has_valid_spot = any(
        data.get(k, {}).get("hourly_data")
        for k in spot_keys
    )
    if not has_valid_spot:
        return False
    try:
        last_updated = datetime.fromisoformat(data["_meta"]["last_updated"])
        age = (datetime.now() - last_updated).total_seconds() / 3600
        return age < max_age_hours
    except (ValueError, KeyError):
        return False
