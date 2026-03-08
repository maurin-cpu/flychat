"""
Wetterdaten-Aggregation für Flychat.
Adaptiert von uetliberg_ticker/fetch_weather.py - Multi-Spot Support.
"""

import requests
import json
import os
from datetime import datetime

import config


def get_weather_for_location(location_name, latitude, longitude):
    """
    Ruft stündliche Wettervorhersage ab (Hybrid-Modell: ICON-CH1 + Seamless + GFS).
    Gibt (hourly_data, pressure_level_data) als dict-of-dicts zurück.
    """
    pl_params = ",".join(config.PRESSURE_LEVEL_PARAMS)

    params_ch1 = {
        "latitude": latitude,
        "longitude": longitude,
        "models": "meteoswiss_icon_ch1",
        "hourly": ",".join(config.HOURLY_PARAMS) + "," + pl_params,
        "forecast_days": config.FORECAST_DAYS,
        "timezone": config.TIMEZONE,
    }

    params_seamless = {
        "latitude": latitude,
        "longitude": longitude,
        "models": "icon_seamless",
        "hourly": ",".join(config.HOURLY_PARAMS) + "," + pl_params,
        "forecast_days": config.FORECAST_DAYS,
        "timezone": config.TIMEZONE,
    }

    try:
        # ICON-CH1 (optional, hochauflösend)
        data_ch1 = None
        try:
            print(f"  [INFO] ICON-CH1 für {location_name}...")
            resp_ch1 = requests.get(config.API_URL, params=params_ch1, timeout=config.API_TIMEOUT)
            resp_ch1.raise_for_status()
            data_ch1 = resp_ch1.json()
        except requests.exceptions.RequestException as e:
            print(f"  [WARN] ICON-CH1 fehlgeschlagen: {e}")

        # Seamless (Pflicht)
        print(f"  [INFO] Seamless für {location_name}...")
        resp_sl = requests.get(config.API_URL, params=params_seamless, timeout=config.API_TIMEOUT)
        resp_sl.raise_for_status()
        data_sl = resp_sl.json()

        hourly_ch1 = data_ch1.get("hourly", {}) if data_ch1 else {}
        hourly_sl = data_sl.get("hourly", {})

        times_sl = hourly_sl.get("time", [])
        if not times_sl:
            print(f"  [WARN] Keine Seamless Daten für {location_name}")
            return None, None

        # Merge: Start mit Seamless, überschreibe mit CH1
        hourly_data = {}
        pressure_level_data = {}

        for i, time_str in enumerate(times_sl):
            entry = {}
            for param in config.HOURLY_PARAMS:
                val = hourly_sl.get(param, [None])[i] if i < len(hourly_sl.get(param, [])) else None
                entry[param] = val
            hourly_data[time_str] = entry

            pl_entry = {}
            for param in config.PRESSURE_LEVEL_PARAMS:
                val = hourly_sl.get(param, [None])[i] if i < len(hourly_sl.get(param, [])) else None
                pl_entry[param] = val
            pressure_level_data[time_str] = pl_entry

        # Überschreibe mit ICON-CH1 (wo verfügbar)
        times_ch1 = hourly_ch1.get("time", []) if hourly_ch1 else []
        for i, time_str in enumerate(times_ch1):
            if time_str not in hourly_data:
                continue
            for param in config.HOURLY_PARAMS:
                val_ch1 = hourly_ch1.get(param, [None])[i] if i < len(hourly_ch1.get(param, [])) else None
                if val_ch1 is not None:
                    hourly_data[time_str][param] = val_ch1
            if time_str in pressure_level_data:
                for param in config.PRESSURE_LEVEL_PARAMS:
                    val_ch1 = hourly_ch1.get(param, [None])[i] if i < len(hourly_ch1.get(param, [])) else None
                    if val_ch1 is not None:
                        pressure_level_data[time_str][param] = val_ch1

        # Cloud-Base-Sentinel: >6000m = wolkenfrei
        for time_str in hourly_data:
            cb = hourly_data[time_str].get("cloud_base")
            if cb is not None and cb > 6000:
                hourly_data[time_str]["cloud_base"] = None

        # GFS Supplement (BLH, LI, CIN)
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

        print(f"  [INFO] {len(hourly_data)} Zeitstempel für {location_name}")
        return hourly_data, pressure_level_data

    except requests.exceptions.RequestException as e:
        print(f"  [FEHLER] API-Fehler für {location_name}: {e}")
        return None, None
    except Exception as e:
        print(f"  [FEHLER] Unerwarteter Fehler für {location_name}: {e}")
        return None, None


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

    for spot in spots:
        name = spot["name"]
        print(f"[INFO] Lade Wetterdaten für {name} ({spot['fluggebiet']})...")

        result = get_weather_for_location(name, spot["latitude"], spot["longitude"])

        if result is None or result[0] is None:
            print(f"[WARN] Keine Daten für {name}")
            continue

        hourly_data, pressure_level_data = result
        all_data[name] = {
            "latitude": spot["latitude"],
            "longitude": spot["longitude"],
            "elevation_m": spot["elevation_m"],
            "hourly_data": hourly_data,
            "pressure_level_data": pressure_level_data,
        }

    if save_to_file:
        config.DATA_DIR.mkdir(exist_ok=True)
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
    try:
        last_updated = datetime.fromisoformat(data["_meta"]["last_updated"])
        age = (datetime.now() - last_updated).total_seconds() / 3600
        return age < max_age_hours
    except (ValueError, KeyError):
        return False
