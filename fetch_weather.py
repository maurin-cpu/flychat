"""
Wetterdaten-Aggregation für Gleitcast.
Adaptiert von uetliberg_ticker/fetch_weather.py - Multi-Spot Support.

Batch-Modus: Alle Spots in 6 API-Calls (D2+Thermal+Fallback+GFS+CH1+CH2).
Referenzpunkt-Dedup: Regionale Punkte nur einmal abfragen (140 → ~48 Punkte).

Generalisierte Source-Area Aggregation:
- Wolken: 30%-Perzentil (Regtherm-Gewichtung) -> findet regionale Sonnenfenster
- Alle anderen Parameter: Flächenmittel (Spatial Mean)
- Referenzpunkte kommen aus source_area.py (GeoJSON / SPOT_CONFIG)
"""

import requests
import json
import math
import os
import time
import copy
from datetime import datetime, timedelta

import config

# Verzögerung zwischen Batch-Calls (Open-Meteo Rate-Limit)
API_DELAY_BETWEEN_CALLS = 3.5  # Sekunden zwischen den 4 Batch-Calls
# Fix D: Retries reduziert von 4 → 2. Vorher: 15+30+60+120 = 225s Wartezeit
# bei sustainted Rate-Limits (User-getriggerter Refresh wird unzumutbar lang).
# Jetzt: 15+30 = max 45s, dann sauberer Stale-Cache-Fallback.
API_RETRY_MAX = 2              # Max Retries bei 429 (war 4)
API_RETRY_BASE_WAIT = 15       # Basis-Wartezeit bei 429 (Sekunden), verdoppelt sich pro Retry
API_BATCH_TIMEOUT = 90         # Timeout für Batch-Requests (mehr Punkte = mehr Verarbeitungszeit)
API_CHUNK_SIZE = 80            # Max Locations pro API-Call (URL-Länge + Timeout-Schutz)

from thermik_calculator import calculate_thermal_profile, calculate_dewpoint
from source_area import get_reference_points, get_all_regions

# --- Aggregation Constants (Modul-Level) ---
CLOUD_PARAMS = {"cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high"}
PRECIP_USE_MIN = {"precipitation", "rain", "precipitation_probability"}


class DailyLimitExceeded(Exception):
    """Raised when the Open-Meteo daily API limit is hit."""
    pass


def _mark_stale_cache(cached, reason):
    """
    Fix A: Markiert einen Cache-Fallback als stale, damit Aufrufer (refresh_weather,
    api_refresh_weather) erkennen können, dass kein echter Refresh stattgefunden hat.
    Setzt _meta.fetch_status = "stale_cache" + Grund.
    """
    if cached:
        meta = cached.setdefault("_meta", {})
        meta["fetch_status"] = "stale_cache"
        meta["fetch_status_reason"] = reason
    return cached if cached else {}


def _api_get_with_retry(url, params, timeout, label=""):
    """
    requests.get() mit automatischem Retry bei 429 Too Many Requests.
    Nutzt Retry-After Header falls vorhanden, sonst exponentiellen Backoff.
    Erkennt Tageslimit und bricht sofort ab (kein sinnloses Retrying).
    Injiziert automatisch den Open-Meteo API-Key wenn konfiguriert.
    """
    config.with_api_key(params)
    for attempt in range(API_RETRY_MAX + 1):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            if resp.status_code == 429:
                # Tageslimit erkennen → sofort abbrechen
                try:
                    body = resp.json()
                    if "daily" in body.get("reason", "").lower():
                        raise DailyLimitExceeded(body["reason"])
                except (ValueError, KeyError):
                    pass
                if attempt < API_RETRY_MAX:
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after:
                        wait = int(retry_after) + 2
                    else:
                        wait = API_RETRY_BASE_WAIT * (2 ** attempt)
                    print(f"  [RATE-LIMIT] 429 bei {label} — warte {wait}s (Versuch {attempt + 1}/{API_RETRY_MAX})...")
                    time.sleep(wait)
                    continue
            resp.raise_for_status()
            return resp
        except DailyLimitExceeded:
            raise
        except requests.exceptions.HTTPError as e:
            if "429" in str(e) and attempt < API_RETRY_MAX:
                wait = API_RETRY_BASE_WAIT * (2 ** attempt)
                print(f"  [RATE-LIMIT] 429 bei {label} — warte {wait}s (Versuch {attempt + 1}/{API_RETRY_MAX})...")
                time.sleep(wait)
                continue
            raise
    return None


def _wait_for_api_ready():
    """
    Pre-Check: Prüft ob die Open-Meteo API erreichbar ist (simpler 1-Punkt-Request).
    Wartet bei 429 bis das Rate-Limit abgelaufen ist, bevor der Batch startet.
    Erkennt Tageslimit und bricht sofort ab.
    """
    test_params = config.with_api_key({
        "latitude": 47.37,
        "longitude": 8.55,
        "hourly": "temperature_2m",
        "forecast_days": 1,
        "timezone": "Europe/Zurich",
    })
    for attempt in range(6):  # Max ~10 Minuten warten
        try:
            resp = requests.get(config.API_URL, params=test_params, timeout=10)
            if resp.status_code == 429:
                # Tageslimit → sofort abbrechen, kein Warten hilft
                try:
                    body = resp.json()
                    if "daily" in body.get("reason", "").lower():
                        print(f"[FEHLER] Open-Meteo Tageslimit erreicht: {body['reason']}")
                        print("[INFO] Nutze vorhandenen Cache. Nächster Versuch morgen.")
                        return False
                except (ValueError, KeyError):
                    pass
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    wait = int(retry_after) + 2
                else:
                    wait = 60 * (attempt + 1)
                print(f"[RATE-LIMIT] API noch blockiert — warte {wait}s (Pre-Check {attempt + 1}/6)...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            print("[INFO] API-Pre-Check OK — starte Wetter-Download...")
            return True
        except requests.exceptions.RequestException as e:
            print(f"[WARN] API-Pre-Check fehlgeschlagen: {e}")
            time.sleep(30)
    print("[FEHLER] API nach 6 Versuchen nicht erreichbar — breche ab.")
    return False


def _chunked_api_get(lats, lons, base_params, timeout, label="", chunk_size=None):
    """
    Batch-API-Call mit automatischem Chunking bei vielen Locations.
    Verhindert URL-Überlauf (>8000 Zeichen) und Timeouts bei grossen Batches.
    Gibt immer eine Liste von Ergebnissen zurück (ein Eintrag pro Location).
    """
    if chunk_size is None:
        chunk_size = API_CHUNK_SIZE

    if len(lats) <= chunk_size:
        params = {**base_params, "latitude": ",".join(lats), "longitude": ",".join(lons)}
        resp = _api_get_with_retry(config.API_URL, params, timeout, label=label)
        if resp is None:
            raise requests.exceptions.RequestException(
                f"API nach {API_RETRY_MAX + 1} Versuchen nicht verfügbar: {label}"
            )
        result = resp.json()
        return result if isinstance(result, list) else [result]

    all_results = []
    n_chunks = math.ceil(len(lats) / chunk_size)
    for ci in range(n_chunks):
        i = ci * chunk_size
        chunk_lats = lats[i:i + chunk_size]
        chunk_lons = lons[i:i + chunk_size]
        chunk_label = f"{label} [{i + 1}-{min(i + chunk_size, len(lats))}/{len(lats)}]"

        params = {**base_params, "latitude": ",".join(chunk_lats), "longitude": ",".join(chunk_lons)}
        resp = _api_get_with_retry(config.API_URL, params, timeout, label=chunk_label)
        if resp is None:
            raise requests.exceptions.RequestException(
                f"API nach {API_RETRY_MAX + 1} Versuchen nicht verfügbar: {chunk_label}"
            )
        result = resp.json()
        if isinstance(result, list):
            all_results.extend(result)
        else:
            all_results.append(result)

        if ci < n_chunks - 1:
            time.sleep(API_DELAY_BETWEEN_CALLS)

    print(f"  [OK] {label}: {len(all_results)} Antworten aus {n_chunks} Chunks")
    return all_results


def _aggregate_wind_across_points(data_list):
    """
    Aggregiert Wind/Gust/Richtung über mehrere Referenzpunkte (für Regionen).

    Für Regionen gibt es keinen dedizierten Spot-Punkt — der Regionalwind soll
    repräsentativ für das gesamte Polygon sein, nicht nur für refs[0]. Ein
    einzelner alpiner Referenzpunkt würde sonst die gesamte Region dominieren
    (z.B. "Mittelland Zentral" mit einem 1662m-Punkt).

    Verfahren:
    - wind_speed_10m: Median über alle RPs (robust gegen Ausreißer)
    - wind_direction_10m: Vektoriell gemittelt (zirkulär korrekt)

    Böen (wind_gusts_10m) werden auf Region-Ebene NICHT aggregiert (Apr 2026):
    Böen sind lokale Spitzenwerte und gehören auf Spot-Ebene.

    Mutiert primary (data_list[0]) in-place und returniert es. NUR für Regionen,
    NICHT für Spots aufrufen — Spots nutzen ihren eigenen Punkt.
    """
    if not data_list or len(data_list) < 2:
        return data_list[0] if data_list else None
    primary = data_list[0]
    if "hourly" not in primary:
        return primary

    h_primary = primary["hourly"]
    n_hours = len(h_primary.get("time", []))

    # Median-Aggregation nur für wind_speed_10m (Böen sind Spot-lokal).
    for k in ("wind_speed_10m",):
        if k not in h_primary:
            continue
        for i in range(n_hours):
            vals = []
            for d in data_list:
                arr = d.get("hourly", {}).get(k, [])
                if i < len(arr) and arr[i] is not None:
                    vals.append(arr[i])
            if vals:
                vals.sort()
                m = len(vals)
                median = vals[m // 2] if m % 2 else (vals[m // 2 - 1] + vals[m // 2]) / 2
                h_primary[k][i] = round(median, 2)

    # Vektorielle Mittelung der Windrichtung (zirkulär, gewichtet mit wind_speed)
    if "wind_direction_10m" in h_primary and "wind_speed_10m" in h_primary:
        for i in range(n_hours):
            us, vs = [], []
            for d in data_list:
                h = d.get("hourly", {})
                sp_arr = h.get("wind_speed_10m", [])
                dr_arr = h.get("wind_direction_10m", [])
                if (i < len(sp_arr) and i < len(dr_arr)
                        and sp_arr[i] is not None and dr_arr[i] is not None):
                    rad = math.radians(dr_arr[i])
                    us.append(sp_arr[i] * math.sin(rad))
                    vs.append(sp_arr[i] * math.cos(rad))
            if us:
                u_avg = sum(us) / len(us)
                v_avg = sum(vs) / len(vs)
                dir_avg = (math.degrees(math.atan2(u_avg, v_avg)) + 360) % 360
                if i < len(h_primary["wind_direction_10m"]):
                    h_primary["wind_direction_10m"][i] = round(dir_avg, 1)

    return primary


def _aggregate_regional_data(data_list):
    """
    Generalisierte Source-Area Aggregation:
    - Wolken: 30%-Perzentil -> findet regionale Sonnenfenster (Blue Holes)
    - Niederschlag: Regionale Signifikanz (mind. 2 von N Punkten > 0.0, sonst 0.0)
    - Temperatur, Strahlung, Druckniveaus: SPOT-Punkt (data_list[0]) behalten!
      Thermik haengt von den Bedingungen AM Startplatz ab, nicht vom Regionalmittel.
    - Wind: hier NICHT aggregiert. Fuer Regionen separat via
      _aggregate_wind_across_points() aufrufen.
    """
    if not data_list or not isinstance(data_list, list):
        return data_list
    primary = data_list[0]  # Spot-Punkt = erste Koordinate
    if "hourly" not in primary:
        return primary

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
                    points_with_rain = sum(1 for v in valid_vals if v > 0.0)
                    if points_with_rain >= 2:
                        primary["hourly"][k][i] = max(valid_vals)
                    else:
                        primary["hourly"][k][i] = 0.0
    return primary


def _process_spot_weather(location_name, data_wind, data_thermal, data_fallback, hourly_gfs, elevation,
                          data_ch1=None, data_ch2=None):
    """
    Verarbeitet vorgeladene Wetterdaten für einen einzelnen Spot.
    Merged Wind/Thermal/Fallback-Modelle, füllt GFS-Supplement, berechnet Thermik.
    Optional: CH1/CH2 Bodenböen für Multi-Modell-Vergleich.

    Args:
        data_wind: Wind-Daten (dict mit hourly, Einzelpunkt)
        data_thermal: Aggregierte Thermal-Daten (dict mit hourly)
        data_fallback: Aggregierte Fallback-Daten (dict mit hourly)
        hourly_gfs: GFS hourly dict (oder None)
        elevation: Höhe des Spots in Metern (aus CSV)
        data_ch1: ICON-CH1 Bodendaten (dict mit hourly, optional)
        data_ch2: ICON-CH2 Bodendaten (dict mit hourly, optional)

    Returns: (hourly_data, pressure_level_data) oder None bei Fehler
    """
    hourly_wind = data_wind.get("hourly", {}) if data_wind else {}
    hourly_thermal = data_thermal.get("hourly", {}) if data_thermal else {}
    hourly_fallback = data_fallback.get("hourly", {}) if data_fallback else {}

    # Basis-Zeitachse: Fallback-Modell (ICON-EU, 120h) hat die längste Reichweite
    times_base = hourly_fallback.get("time", [])
    if not times_base:
        times_wind = hourly_wind.get("time", []) if hourly_wind else []
        times_thermal = hourly_thermal.get("time", []) if hourly_thermal else []
        all_times_set = set(times_wind + times_thermal)
        times_base = sorted(list(all_times_set))

    if not times_base:
        print(f"  [WARN] Keine Basisdaten für {location_name}")
        return None

    def is_model_valid_for_day(hourly_data_dict, date_str, param):
        if not hourly_data_dict:
            return False
        times = hourly_data_dict.get("time", [])
        vals = hourly_data_dict.get(param, [])
        if not times or not vals:
            return False
        found_any = False
        for idx, t in enumerate(times):
            if t.startswith(date_str):
                hour = int(t[11:13])
                if config.FLIGHT_HOURS_START <= hour < config.FLIGHT_HOURS_END:
                    val = vals[idx] if idx < len(vals) else None
                    if val is None:
                        return False
                    found_any = True
        return found_any

    # Pro Tag entscheiden: Welches Modell liefert die Daten? Kein Mischen am selben Tag!
    dates = sorted(list(set([t[:10] for t in times_base])))
    thermal_model_by_day = {}
    wind_model_by_day = {}
    for d in dates:
        thermal_model_by_day[d] = hourly_thermal if is_model_valid_for_day(hourly_thermal, d, "temperature_2m") else hourly_fallback
        wind_model_by_day[d] = hourly_wind if is_model_valid_for_day(hourly_wind, d, "wind_speed_10m") else hourly_fallback

    hourly_data = {}
    pressure_level_data = {}

    wind_surface_params = ["wind_speed_10m", "wind_direction_10m", "wind_gusts_10m"]
    wind_pl_params = [
        p for p in config.PRESSURE_LEVEL_PARAMS
        if p.startswith("wind_speed_") or p.startswith("wind_direction_") or p.startswith("geopotential_height_")
    ]

    # Pre-build time→index dicts for O(1) lookup (statt O(n) .index() pro Timestamp)
    _time_idx_cache = {}
    def _get_time_index(src):
        src_id = id(src)
        if src_id not in _time_idx_cache:
            _time_idx_cache[src_id] = {t: i for i, t in enumerate(src.get("time", []))}
        return _time_idx_cache[src_id]

    for time_str in times_base:
        d = time_str[:10]
        t_src = thermal_model_by_day.get(d, hourly_fallback)
        w_src = wind_model_by_day.get(d, hourly_fallback)

        i_therm = _get_time_index(t_src).get(time_str, -1)
        i_wind = _get_time_index(w_src).get(time_str, -1)

        entry = {}
        for param in config.HOURLY_PARAMS:
            val = None
            if i_therm >= 0:
                val = t_src.get(param, [None])[i_therm] if i_therm < len(t_src.get(param, [])) else None
            entry[param] = val

        if i_wind >= 0:
            for param in wind_surface_params:
                val_w = w_src.get(param, [None])[i_wind] if i_wind < len(w_src.get(param, [])) else None
                if val_w is not None:
                    entry[param] = val_w

        hourly_data[time_str] = entry

        # Fallback-Index für PL-Lücken (Regionen haben keinen eigenen Wind-Batch,
        # daher fehlen geopotential_height/wind_speed/wind_direction auf Druckniveaus
        # in den ersten 2 Tagen wo ICON-D2 Thermal gewählt wird).
        i_fb = -1
        if hourly_fallback and (t_src is not hourly_fallback or w_src is not hourly_fallback):
            i_fb = _get_time_index(hourly_fallback).get(time_str, -1)

        pl_entry = {}
        for param in config.PRESSURE_LEVEL_PARAMS:
            val = None
            if i_therm >= 0:
                val = t_src.get(param, [None])[i_therm] if i_therm < len(t_src.get(param, [])) else None

            # Prioritize wind source for wind-specific profile parameters
            if i_wind >= 0 and param in wind_pl_params:
                val_w = w_src.get(param, [None])[i_wind] if i_wind < len(w_src.get(param, [])) else None
                if val_w is not None:
                    val = val_w

            # Fallback auf ICON-EU wenn Thermal/Wind-Modell den PL-Param nicht hat
            if val is None and i_fb >= 0:
                val_fb = hourly_fallback.get(param, [None])[i_fb] if i_fb < len(hourly_fallback.get(param, [])) else None
                if val_fb is not None:
                    val = val_fb

            pl_entry[param] = val

        pressure_level_data[time_str] = pl_entry

    # Cloud base filter
    for time_str in hourly_data:
        cb = hourly_data[time_str].get("cloud_base")
        if cb is not None and cb > 6000:
            hourly_data[time_str]["cloud_base"] = None

    # Multi-Modell Böen-Merge: CH1/CH2 Bodenböen mit ICON-D2 vergleichen
    hourly_ch1 = data_ch1.get("hourly", {}) if data_ch1 else {}
    hourly_ch2 = data_ch2.get("hourly", {}) if data_ch2 else {}
    ch1_times = hourly_ch1.get("time", [])
    ch2_times = hourly_ch2.get("time", [])
    ch1_gusts = hourly_ch1.get("wind_gusts_10m", [])
    ch2_gusts = hourly_ch2.get("wind_gusts_10m", [])
    ch1_speed = hourly_ch1.get("wind_speed_10m", [])
    ch2_speed = hourly_ch2.get("wind_speed_10m", [])
    ch1_dir = hourly_ch1.get("wind_direction_10m", [])
    ch2_dir = hourly_ch2.get("wind_direction_10m", [])

    # Index-Maps für schnellen Zugriff
    ch1_idx = {t: i for i, t in enumerate(ch1_times)} if ch1_times else {}
    ch2_idx = {t: i for i, t in enumerate(ch2_times)} if ch2_times else {}

    multi_model_count = 0
    for time_str in hourly_data:
        entry = hourly_data[time_str]
        d2_gust = entry.get("wind_gusts_10m")

        # CH1 Werte extrahieren
        ch1_g = None
        i1 = ch1_idx.get(time_str)
        if i1 is not None and i1 < len(ch1_gusts):
            ch1_g = ch1_gusts[i1]

        # CH2 Werte extrahieren
        ch2_g = None
        i2 = ch2_idx.get(time_str)
        if i2 is not None and i2 < len(ch2_gusts):
            ch2_g = ch2_gusts[i2]

        # Einzelmodell-Werte speichern (Transparenz)
        if ch1_g is not None:
            entry["wind_gusts_10m_ch1"] = ch1_g
            if i1 is not None and i1 < len(ch1_speed):
                entry["wind_speed_10m_ch1"] = ch1_speed[i1]
            if i1 is not None and i1 < len(ch1_dir):
                entry["wind_direction_10m_ch1"] = ch1_dir[i1]

        if ch2_g is not None:
            entry["wind_gusts_10m_ch2"] = ch2_g
            if i2 is not None and i2 < len(ch2_speed):
                entry["wind_speed_10m_ch2"] = ch2_speed[i2]
            if i2 is not None and i2 < len(ch2_dir):
                entry["wind_direction_10m_ch2"] = ch2_dir[i2]

        # Merge: Maximum aller verfügbaren Modelle (konservativ/sicher)
        if config.MULTI_MODEL_GUST_MERGE:
            gust_values = [v for v in [d2_gust, ch1_g, ch2_g] if v is not None]
            if len(gust_values) > 1:
                max_gust = max(gust_values)
                if d2_gust is not None and max_gust > d2_gust:
                    entry["wind_gusts_10m_d2"] = d2_gust  # Original D2 aufbewahren
                    entry["wind_gusts_10m"] = max_gust
                    multi_model_count += 1

    if multi_model_count > 0:
        print(f"  [MULTI] {location_name}: {multi_model_count} Stunden mit höheren CH1/CH2 Böen übernommen")

    # GFS Supplement
    if hourly_gfs:
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
                for p in config.GFS_CROSSCHECK_PARAMS:
                    val = hourly_gfs.get(p, [None])[i] if i < len(hourly_gfs.get(p, [])) else None
                    if val is not None:
                        hourly_data[ts][f"{p}_gfs"] = val

    # Thermik-Berechnung
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

            calculate_thermal_profile(
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

    print(f"  [OK] {location_name}: {len(hourly_data)} Zeitstempel")
    return hourly_data, pressure_level_data


def _build_param_lists():
    """Baut die Parameter-Listen für jeden Modell-Call."""
    # Wind: surface wind + pressure level wind/geopotential
    wind_params = ["wind_speed_10m", "wind_direction_10m", "wind_gusts_10m"]
    for level in config.PRESSURE_LEVELS:
        wind_params.extend([
            f"wind_speed_{level}hPa",
            f"wind_direction_{level}hPa",
            f"geopotential_height_{level}hPa",
        ])

    # Thermal: Surface + nur Temperatur auf Druckniveaus.
    # Wind-PL kommt bereits vom Wind-Batch, Geopotential vom Wind-Batch.
    thermal_pl_params = [f"temperature_{level}hPa" for level in config.PRESSURE_LEVELS]
    thermal_params = list(config.HOURLY_PARAMS) + thermal_pl_params

    # Fallback: Surface + alle PL-Params (vollständiges Backup für Tag 3-5 / ICON-D2-Ausfall)
    fallback_params = list(config.HOURLY_PARAMS) + list(config.PRESSURE_LEVEL_PARAMS)

    # GFS: supplementary only
    gfs_params = list(config.GFS_SUPPLEMENTARY_PARAMS) + list(config.GFS_CROSSCHECK_PARAMS)

    return wind_params, thermal_params, fallback_params, gfs_params


def fetch_all_spots(spots, save_to_file=True):
    """
    Holt Wetterdaten für ALLE Spots in 4 Batch-Requests (statt 112 Einzel-Calls).
    Dedupliziert regionale Referenzpunkte für minimalen API-Verbrauch.
    Bei Tageslimit: Nutzt vorhandenen Cache.
    Returns: Dict mit allen Spot-Daten.
    """
    # Pre-Check: Warte bis API verfügbar
    if not _wait_for_api_ready():
        cached = load_cached_weather()
        return _mark_stale_cache(cached, "api_pre_check_failed")

    cached = load_cached_weather()

    # === Phase 1: Referenzpunkte sammeln und deduplizieren ===
    spot_refs = {}      # {name: [[lat,lon], ...]}
    unique_points = []  # list of [lat, lon]
    point_index = {}    # {(lat_r, lon_r): index_in_unique}

    for spot in spots:
        refs = get_reference_points(spot["name"], spot["latitude"], spot["longitude"], quiet=True)
        spot_refs[spot["name"]] = refs
        for pt in refs:
            key = (round(pt[0], 4), round(pt[1], 4))
            if key not in point_index:
                point_index[key] = len(unique_points)
                unique_points.append([round(pt[0], 4), round(pt[1], 4)])

    # Region-Referenzpunkte: nur in point_index registrieren (NICHT in unique_points!).
    # Regionen nutzen den gleichen Batch wie Spots — aber nur fuer Punkte die
    # ohnehin schon von Spots abgefragt werden. Nicht-ueberlappende Region-Punkte
    # werden in Phase 4 per eigenem Batch geholt.
    all_regions = get_all_regions()
    region_refs = {}  # {region_id: [[lat,lon], ...]}
    region_only_points = []  # Punkte die NUR von Regionen gebraucht werden
    region_only_index = {}   # {(lat_r, lon_r): index_in_region_only_points}
    for region in all_regions:
        rid = region["id"]
        region_refs[rid] = region["reference_points"]
        for pt in region["reference_points"]:
            key = (round(pt[0], 4), round(pt[1], 4))
            if key not in point_index and key not in region_only_index:
                region_only_index[key] = len(region_only_points)
                region_only_points.append([round(pt[0], 4), round(pt[1], 4)])

    spot_lats = [str(s["latitude"]) for s in spots]
    spot_lons = [str(s["longitude"]) for s in spots]
    unique_lats = [str(p[0]) for p in unique_points]
    unique_lons = [str(p[1]) for p in unique_points]

    shared_region_pts = sum(1 for r in all_regions for pt in r["reference_points"]
                           if (round(pt[0], 4), round(pt[1], 4)) in point_index)
    print(f"[INFO] {len(spots)} Spots, {len(unique_points)} Spot-Punkte (dedup), "
          f"{len(all_regions)} Regionen ({shared_region_pts} geteilte + {len(region_only_points)} eigene Punkte)")

    wind_params, thermal_params, fallback_params, gfs_params = _build_param_lists()

    # === Phase 2: 6 Batch-API-Calls ===
    batch_wind = None
    batch_thermal = None
    batch_fallback = None
    batch_gfs = None
    batch_ch1 = None
    batch_ch2 = None

    try:
        # 1. Wind (Spot-Punkte, nur Wind-Vars) — chunked bei >80 Spots
        print(f"[API] Batch Wind: {len(spots)} Punkte, {len(wind_params)} Vars, Modell {config.WIND_MODEL}")
        batch_wind = _chunked_api_get(spot_lats, spot_lons, {
            "models": config.WIND_MODEL,
            "hourly": ",".join(wind_params),
            "forecast_days": config.FORECAST_DAYS,
            "timezone": config.TIMEZONE,
        }, API_BATCH_TIMEOUT, label="Batch-Wind")
        print(f"  [OK] {len(batch_wind)} Wind-Antworten")

        time.sleep(API_DELAY_BETWEEN_CALLS)

        # 2. Thermal (deduplizierte Punkte, Thermik-Vars)
        print(f"[API] Batch Thermal: {len(unique_points)} Punkte, {len(thermal_params)} Vars, Modell {config.THERMAL_MODEL}")
        batch_thermal = _chunked_api_get(unique_lats, unique_lons, {
            "models": config.THERMAL_MODEL,
            "hourly": ",".join(thermal_params),
            "forecast_days": config.FORECAST_DAYS,
            "timezone": config.TIMEZONE,
        }, API_BATCH_TIMEOUT, label="Batch-Thermal")
        print(f"  [OK] {len(batch_thermal)} Thermal-Antworten")

        time.sleep(API_DELAY_BETWEEN_CALLS)

        # 3. Fallback (deduplizierte Punkte, ALLE Vars — Backup für Tag 3-5 + Ausfälle)
        print(f"[API] Batch Fallback: {len(unique_points)} Punkte, {len(fallback_params)} Vars, Modell {config.FALLBACK_MODEL}")
        batch_fallback = _chunked_api_get(unique_lats, unique_lons, {
            "models": config.FALLBACK_MODEL,
            "hourly": ",".join(fallback_params),
            "forecast_days": config.FORECAST_DAYS,
            "timezone": config.TIMEZONE,
        }, API_BATCH_TIMEOUT, label="Batch-Fallback")
        print(f"  [OK] {len(batch_fallback)} Fallback-Antworten")

        time.sleep(API_DELAY_BETWEEN_CALLS)

        # 4. GFS (Spot-Punkte, Supplement-Vars)
        print(f"[API] Batch GFS: {len(spots)} Punkte, {len(gfs_params)} Vars")
        batch_gfs = _chunked_api_get(spot_lats, spot_lons, {
            "models": "gfs_seamless",
            "hourly": ",".join(gfs_params),
            "forecast_days": config.FORECAST_DAYS,
            "timezone": config.TIMEZONE,
        }, API_BATCH_TIMEOUT, label="Batch-GFS")
        print(f"  [OK] {len(batch_gfs)} GFS-Antworten")

        time.sleep(API_DELAY_BETWEEN_CALLS)

        # 5. CH1 — MeteoSwiss ICON-CH1 (1km, ~33h Horizont, nur Bodenwind)
        ch_params = config.CH_SURFACE_PARAMS
        print(f"[API] Batch CH1: {len(spots)} Punkte, {len(ch_params)} Vars, Modell {config.CH1_MODEL}")
        try:
            batch_ch1 = _chunked_api_get(spot_lats, spot_lons, {
                "models": config.CH1_MODEL,
                "hourly": ",".join(ch_params),
                "forecast_days": config.CH1_FORECAST_DAYS,
                "timezone": config.TIMEZONE,
            }, API_BATCH_TIMEOUT, label="Batch-CH1")
            print(f"  [OK] {len(batch_ch1)} CH1-Antworten")
        except Exception as e:
            print(f"  [WARN] CH1-Batch fehlgeschlagen (nicht kritisch): {e}")
            batch_ch1 = None

        time.sleep(API_DELAY_BETWEEN_CALLS)

        # 6. CH2 — MeteoSwiss ICON-CH2 (2km, 5 Tage Horizont, nur Bodenwind)
        print(f"[API] Batch CH2: {len(spots)} Punkte, {len(ch_params)} Vars, Modell {config.CH2_MODEL}")
        try:
            batch_ch2 = _chunked_api_get(spot_lats, spot_lons, {
                "models": config.CH2_MODEL,
                "hourly": ",".join(ch_params),
                "forecast_days": config.CH2_FORECAST_DAYS,
                "timezone": config.TIMEZONE,
            }, API_BATCH_TIMEOUT, label="Batch-CH2")
            print(f"  [OK] {len(batch_ch2)} CH2-Antworten")
        except Exception as e:
            print(f"  [WARN] CH2-Batch fehlgeschlagen (nicht kritisch): {e}")
            batch_ch2 = None

    except DailyLimitExceeded:
        print("[FEHLER] Tageslimit erreicht während Batch-Calls")
        return _mark_stale_cache(cached, "daily_limit_exceeded")
    except Exception as e:
        print(f"[FEHLER] Batch-API fehlgeschlagen: {e}")
        if not batch_thermal and not batch_fallback:
            return _mark_stale_cache(cached, f"batch_failed: {type(e).__name__}: {e}")

    # === Phase 3: Per-Spot Verarbeitung ===
    all_data = {
        "_meta": {
            "last_updated": datetime.now().isoformat(),
            "spots_count": len(spots),
        }
    }

    for i, spot in enumerate(spots):
        name = spot["name"]
        refs = spot_refs[name]

        # Wind: direkt per Index (1:1 Spot-Zuordnung)
        data_wind = batch_wind[i] if batch_wind and i < len(batch_wind) else None

        # Thermal: Referenzpunkte aus Batch extrahieren, dann aggregieren
        data_thermal = None
        if batch_thermal:
            thermal_data_list = []
            for j, pt in enumerate(refs):
                key = (round(pt[0], 4), round(pt[1], 4))
                idx = point_index.get(key)
                if idx is not None and idx < len(batch_thermal):
                    # Deepcopy nur für Spot-Punkt (wird von Aggregation modifiziert)
                    data = copy.deepcopy(batch_thermal[idx]) if j == 0 else batch_thermal[idx]
                    thermal_data_list.append(data)
            if thermal_data_list:
                data_thermal = _aggregate_regional_data(thermal_data_list)

        # Fallback: gleiche Referenzpunkt-Zuordnung
        data_fallback = None
        if batch_fallback:
            fallback_data_list = []
            for j, pt in enumerate(refs):
                key = (round(pt[0], 4), round(pt[1], 4))
                idx = point_index.get(key)
                if idx is not None and idx < len(batch_fallback):
                    data = copy.deepcopy(batch_fallback[idx]) if j == 0 else batch_fallback[idx]
                    fallback_data_list.append(data)
            if fallback_data_list:
                data_fallback = _aggregate_regional_data(fallback_data_list)

        # GFS
        hourly_gfs = None
        if batch_gfs and i < len(batch_gfs):
            hourly_gfs = batch_gfs[i].get("hourly", {})

        # CH1/CH2: direkt per Index (1:1 Spot-Zuordnung, wie Wind)
        data_ch1 = batch_ch1[i] if batch_ch1 and i < len(batch_ch1) else None
        data_ch2 = batch_ch2[i] if batch_ch2 and i < len(batch_ch2) else None

        # Spot verarbeiten (merge + thermik)
        try:
            result = _process_spot_weather(
                name, data_wind, data_thermal, data_fallback,
                hourly_gfs, spot["elevation_m"],
                data_ch1=data_ch1, data_ch2=data_ch2,
            )
        except Exception as e:
            import traceback
            print(f"  [FEHLER] Verarbeitung {name}: {e}")
            traceback.print_exc()
            if cached and name in cached:
                all_data[name] = cached[name]
            continue

        if result is None:
            if cached and name in cached:
                all_data[name] = cached[name]
                print(f"  [CACHE] {name}: Nutze Cache-Daten")
            else:
                print(f"  [WARN] Keine Daten für {name}")
            continue

        hourly_data, pressure_level_data = result

        missing = validate_spot_data(name, hourly_data, config.FORECAST_DAYS)
        if missing:
            print(f"  [WARN] {name}: Tage {', '.join(missing)} unvollständig")

        all_data[name] = {
            "latitude": spot["latitude"],
            "longitude": spot["longitude"],
            "elevation_m": spot["elevation_m"],
            "hourly_data": hourly_data,
            "pressure_level_data": pressure_level_data,
            "reference_points": refs,
        }

    # === Phase 4: Region-Wetter aggregieren ===
    # Eigene Batch-Calls fuer Region-only Punkte (nicht im Spot-Batch enthalten)
    batch_region_thermal = None
    batch_region_fallback = None

    if region_only_points:
        region_lats = [str(p[0]) for p in region_only_points]
        region_lons = [str(p[1]) for p in region_only_points]

        try:
            time.sleep(API_DELAY_BETWEEN_CALLS)
            print(f"[API] Batch Region-Thermal: {len(region_only_points)} Punkte, Modell {config.THERMAL_MODEL}")
            batch_region_thermal = _chunked_api_get(region_lats, region_lons, {
                "models": config.THERMAL_MODEL,
                "hourly": ",".join(thermal_params),
                "forecast_days": config.FORECAST_DAYS,
                "timezone": config.TIMEZONE,
            }, API_BATCH_TIMEOUT, label="Batch-Region-Thermal")
            print(f"  [OK] {len(batch_region_thermal)} Region-Thermal-Antworten")

            time.sleep(API_DELAY_BETWEEN_CALLS)
            print(f"[API] Batch Region-Fallback: {len(region_only_points)} Punkte, Modell {config.FALLBACK_MODEL}")
            batch_region_fallback = _chunked_api_get(region_lats, region_lons, {
                "models": config.FALLBACK_MODEL,
                "hourly": ",".join(fallback_params),
                "forecast_days": config.FORECAST_DAYS,
                "timezone": config.TIMEZONE,
            }, API_BATCH_TIMEOUT, label="Batch-Region-Fallback")
            print(f"  [OK] {len(batch_region_fallback)} Region-Fallback-Antworten")
        except DailyLimitExceeded:
            print("[WARN] Tageslimit bei Region-Batch — Regionen werden übersprungen")
        except Exception as e:
            print(f"[WARN] Region-Batch fehlgeschlagen: {e}")

    def _get_batch_entry_for_point(pt, batch_spot, batch_region):
        """Holt Batch-Eintrag: zuerst Spot-Batch, dann Region-Batch."""
        key = (round(pt[0], 4), round(pt[1], 4))
        # Punkt im Spot-Batch?
        idx = point_index.get(key)
        if idx is not None and batch_spot and idx < len(batch_spot):
            return batch_spot[idx]
        # Punkt im Region-Batch?
        ridx = region_only_index.get(key)
        if ridx is not None and batch_region and ridx < len(batch_region):
            return batch_region[ridx]
        return None

    region_data = {}
    for region in all_regions:
        rid = region["id"]
        rname = region["region"]
        refs = region_refs.get(rid, [])
        elev_ref = region.get("elevation_ref", 1200)

        if not refs:
            continue

        # Thermal: Referenzpunkte aus Spot- und Region-Batch extrahieren
        # Fuer Regionen: ALLE Referenzpunkte deepcopien, damit wir sie fuer
        # Wind-Aggregation separat mutieren koennen ohne den Batch zu veraendern.
        data_thermal_r = None
        thermal_data_list = []
        for pt in refs:
            entry = _get_batch_entry_for_point(pt, batch_thermal, batch_region_thermal)
            if entry is not None:
                thermal_data_list.append(copy.deepcopy(entry))
        if thermal_data_list:
            data_thermal_r = _aggregate_regional_data(thermal_data_list)
            # NEU: Wind/Gust/Richtung ueber ALLE RPs aggregieren (Median),
            # sodass kein einzelner alpiner RP die ganze Region dominiert.
            data_thermal_r = _aggregate_wind_across_points(thermal_data_list)

        # Fallback — ebenfalls mit Wind-Aggregation ueber alle RPs
        data_fallback_r = None
        fallback_data_list = []
        for pt in refs:
            entry = _get_batch_entry_for_point(pt, batch_fallback, batch_region_fallback)
            if entry is not None:
                fallback_data_list.append(copy.deepcopy(entry))
        if fallback_data_list:
            data_fallback_r = _aggregate_regional_data(fallback_data_list)
            data_fallback_r = _aggregate_wind_across_points(fallback_data_list)

        # Wind: Nutze das thermal-aggregierte Ergebnis (Wind ist Teil der Thermal-Params
        # via HOURLY_PARAMS). Dadurch hat data_wind_r jetzt Median-Wind ueber alle RPs
        # statt nur refs[0]. Falls Thermal nicht verfuegbar, Fallback auf Fallback-Batch.
        data_wind_r = data_thermal_r or data_fallback_r

        try:
            result = _process_spot_weather(
                f"Region:{rname}", data_wind_r, data_thermal_r, data_fallback_r,
                None, elev_ref
            )
        except Exception as e:
            print(f"  [FEHLER] Region {rname}: {e}")
            continue

        if result is None:
            continue

        hourly_data, pressure_level_data = result
        region_data[rid] = {
            "region_id": rid,
            "region_name": rname,
            "elevation_ref": elev_ref,
            "hourly_data": hourly_data,
            "pressure_level_data": pressure_level_data,
            "reference_points": refs,
        }

    print(f"[INFO] {len(region_data)} Regionen verarbeitet")

    spot_keys = [k for k in all_data if k != "_meta"]
    print(f"[INFO] Fertig: {len(spot_keys)} Spots + {len(region_data)} Regionen verarbeitet")

    if save_to_file:
        # Speichere Regions-Daten unter _regions Key
        all_data["_regions"] = region_data
        # JSON-Write — async, blockiert Aufrufer nicht.
        # `all_data` wird nach diesem Punkt nicht mehr mutiert → safe fuer pass-by-reference.
        config.queue_atomic_write_json(config.WEATHER_JSON_PATH, all_data)
        print(f"[INFO] Wetterdaten-Write eingereiht: {config.WEATHER_JSON_PATH}")

    return all_data, region_data


def get_weather_for_location(location_name, latitude, longitude):
    """
    Einzelspot-Modus: Holt Wetterdaten für einen einzelnen Spot (4 API-Calls).
    Wird nur noch für Einzel-Retries verwendet — Hauptpfad ist fetch_all_spots() mit Batching.
    """
    ref_points = get_reference_points(location_name, latitude, longitude)

    wind_params, thermal_params, fallback_params, gfs_params = _build_param_lists()

    lat_str = ",".join(str(round(p[0], 4)) for p in ref_points)
    lon_str = ",".join(str(round(p[1], 4)) for p in ref_points)

    try:
        # Wind (Einzelpunkt)
        data_wind = None
        try:
            resp = _api_get_with_retry(config.API_URL, {
                "latitude": latitude, "longitude": longitude,
                "models": config.WIND_MODEL,
                "hourly": ",".join(wind_params),
                "forecast_days": config.FORECAST_DAYS,
                "timezone": config.TIMEZONE,
            }, config.API_TIMEOUT, label=f"Wind/{location_name}")
            data_wind = resp.json()
        except requests.exceptions.RequestException as e:
            print(f"  [WARN] Wind fehlgeschlagen: {e}")

        time.sleep(API_DELAY_BETWEEN_CALLS)

        # Thermal (5 Punkte)
        data_thermal = None
        try:
            resp = _api_get_with_retry(config.API_URL, {
                "latitude": lat_str, "longitude": lon_str,
                "models": config.THERMAL_MODEL,
                "hourly": ",".join(thermal_params),
                "forecast_days": config.FORECAST_DAYS,
                "timezone": config.TIMEZONE,
            }, config.API_TIMEOUT, label=f"Thermal/{location_name}")
            res_json = resp.json()
            data_list = res_json if isinstance(res_json, list) else [res_json]
            data_thermal = _aggregate_regional_data(data_list)
        except requests.exceptions.RequestException as e:
            print(f"  [WARN] Thermal fehlgeschlagen: {e}")

        time.sleep(API_DELAY_BETWEEN_CALLS)

        # Fallback (5 Punkte, alle Params)
        data_fallback = None
        try:
            resp = _api_get_with_retry(config.API_URL, {
                "latitude": lat_str, "longitude": lon_str,
                "models": config.FALLBACK_MODEL,
                "hourly": ",".join(fallback_params),
                "forecast_days": config.FORECAST_DAYS,
                "timezone": config.TIMEZONE,
            }, config.API_TIMEOUT, label=f"Fallback/{location_name}")
            res_json = resp.json()
            data_list = res_json if isinstance(res_json, list) else [res_json]
            data_fallback = _aggregate_regional_data(data_list)
        except requests.exceptions.RequestException as e:
            print(f"  [WARN] Fallback fehlgeschlagen: {e}")

        time.sleep(API_DELAY_BETWEEN_CALLS)

        # GFS
        hourly_gfs = None
        try:
            resp = _api_get_with_retry(config.API_URL, {
                "latitude": latitude, "longitude": longitude,
                "hourly": ",".join(gfs_params),
                "models": "gfs_seamless",
                "forecast_days": config.FORECAST_DAYS,
                "timezone": config.TIMEZONE,
            }, 10, label=f"GFS/{location_name}")
            hourly_gfs = resp.json().get("hourly", {})
        except Exception as e:
            print(f"  [WARN] GFS fehlgeschlagen: {e}")

        elevation = 0
        if data_thermal:
            elevation = data_thermal.get("elevation", 0)
        elif data_wind:
            elevation = data_wind.get("elevation", 0)

        result = _process_spot_weather(location_name, data_wind, data_thermal, data_fallback, hourly_gfs, elevation)
        if result is None:
            return None, None, ref_points

        hourly_data, pressure_level_data = result
        return hourly_data, pressure_level_data, ref_points

    except DailyLimitExceeded:
        raise
    except Exception as e:
        import traceback
        print(f"  [FEHLER] {location_name}: {e}")
        traceback.print_exc()
        return None, None, ref_points


def load_cached_weather():
    """Lade gecachte Wetterdaten aus wetterdaten.json.

    Format: {_meta, _regions, {spot_name: data}}.
    """
    if not config.WEATHER_JSON_PATH.exists():
        return None
    with open(config.WEATHER_JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_cached_weather_timestamp(_cached=None):
    """Gibt den Zeitpunkt des letzten Cache-Updates zurück (oder None).

    Optional: `_cached` weiterreichen, um doppeltes JSON-Lesen zu vermeiden.
    """
    data = _cached if _cached is not None else load_cached_weather()
    if not data or "_meta" not in data:
        return None
    try:
        return datetime.fromisoformat(data["_meta"]["last_updated"])
    except (ValueError, KeyError):
        return None


def is_cache_fresh(max_age_hours=12, _cached=None):
    """Prüft ob der Cache noch frisch genug ist.

    Optional: `_cached` weiterreichen, um doppeltes JSON-Lesen zu vermeiden.
    """
    if not config.WEATHER_JSON_PATH.exists():
        return False
    data = _cached if _cached is not None else load_cached_weather()
    if not data or "_meta" not in data:
        return False
    spot_keys = [k for k in data.keys() if k not in ("_meta", "_regions")]
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


def validate_spot_data(spot_name, hourly_data, forecast_days):
    """Prüft ob Kernparameter (temp, wind) für alle Forecast-Tage vorhanden sind.
    Returns: Liste fehlender Tage (leer = ok)."""
    if not hourly_data:
        today = datetime.now().date()
        return [(today + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(forecast_days)]

    today = datetime.now().date()
    expected_days = [(today + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(forecast_days)]

    missing = []
    for day_str in expected_days:
        has_valid_hour = False
        for ts, entry in hourly_data.items():
            if not ts.startswith(day_str):
                continue
            try:
                hour = int(ts[11:13])
            except (ValueError, IndexError):
                continue
            if not (config.FLIGHT_HOURS_START <= hour < config.FLIGHT_HOURS_END):
                continue
            temp = entry.get("temperature_2m")
            wind = entry.get("wind_speed_10m")
            if temp is not None and wind is not None:
                has_valid_hour = True
                break
        if not has_valid_hour:
            missing.append(day_str)
    return missing


def is_cache_complete(_cached=None):
    """Prüft ob ALLE Spots im Cache vollständige Daten für alle Forecast-Tage haben.

    Optional: `_cached` weiterreichen, um doppeltes JSON-Lesen zu vermeiden.
    """
    data = _cached if _cached is not None else load_cached_weather()
    if not data:
        return False
    spot_keys = [k for k in data.keys() if k not in ("_meta", "_regions")]
    if not spot_keys:
        return False
    for spot_name in spot_keys:
        hourly_data = data.get(spot_name, {}).get("hourly_data", {})
        missing = validate_spot_data(spot_name, hourly_data, config.FORECAST_DAYS)
        if missing:
            print(f"[CACHE] {spot_name}: Tage unvollständig: {', '.join(missing)}")
            return False
    return True
