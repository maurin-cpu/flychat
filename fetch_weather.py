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

from thermik_calculator import calculate_thermal_profile, calculate_dewpoint, compute_daily_thermals
from source_area import get_reference_points, get_all_regions, get_precip_reference_points
import statistics

# Schwelle: ab welcher Spot-Anzahl je Region wird der Spot-Median Thermik-Override
# aktiv? Darunter bleibt der Refpoint-Pfad. Mai 2026: 3 ist Mindest-Median-Robustheit,
# 7 Regionen heute haben n<3 (Mittelland West/Ost, Bodenseeraum, Jura Ost, Seeland,
# Zentrales Mittelland, Waadtländer Alpen).
SPOT_MEDIAN_MIN_SPOTS = 3

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


def _best_thermal_rp_index(data_list: list) -> int:
    """Gibt den Index des thermisch repraesentativsten Referenzpunkts zurueck.

    Kriterium: hoechste mittlere shortwave_radiation waehrend Flugstunden.
    Damit wird sichergestellt, dass nicht blind RP0 als thermischer Anker
    genutzt wird, sondern der Punkt mit der besten solaren Einstrahlung.
    Wind- und Wolken-Aggregation sind reihenfolge-unabhaengig (Median/Perzentil),
    daher hat die Umordnung dort keinen Effekt.
    """
    if len(data_list) <= 1:
        return 0
    best_idx, best_rad = 0, -1.0
    for i, d in enumerate(data_list):
        h = d.get("hourly", {})
        times = h.get("time", [])
        rads = h.get("shortwave_radiation", [])
        vals = [
            rads[j] for j, t in enumerate(times)
            if j < len(rads)
            and rads[j] is not None
            and config.FLIGHT_HOURS_START <= int(t[11:13]) < config.FLIGHT_HOURS_END
        ]
        mean_rad = sum(vals) / len(vals) if vals else 0.0
        if mean_rad > best_rad:
            best_rad, best_idx = mean_rad, i
    return best_idx


def _override_precip_with_dense_rps(target: dict, dense_data_list: list) -> dict:
    """Ueberschreibt die Niederschlags-Felder eines aggregierten Region-Results
    mit einer dichteren RP-Aggregation (typisch 16 statt 7 Punkten).

    Begruendung: Wind/Wolken/Thermik brauchen physikalische Anker an den
    7 Haupt-RPs (Talwind, Höhenprofile). Niederschlag dagegen ist klein-
    raeumig konvektiv — bei 7 RPs fallen einzelne Schauerzellen oft
    zwischen die Punkte durch. 16 dichte CVT-Punkte liefern eine ehrliche
    Coverage-Statistik (widespread/scattered/isolated) ohne den Rest des
    Caches zu beruehren.

    Args:
        target: aggregiertes Region-Dict (Ergebnis von _aggregate_regional_data).
                Wird IN PLACE modifiziert.
        dense_data_list: Liste der 16 RP-Antworten (jede mit "hourly").

    Ueberschriebene Felder pro Stunde:
        precipitation, precipitation_probability, precipitation_coverage,
        precipitation_class, precipitation_n_rps.

    Returns: target (gleiche Referenz, fuer Chaining).
    """
    if not target or "hourly" not in target or not dense_data_list:
        return target

    th = target["hourly"]
    num_hours = len(th.get("time", []))
    if num_hours == 0:
        return target

    # Spuren initialisieren falls noch nicht vorhanden. precipitation/
    # precipitation_probability koennen fehlen, wenn `target` der D2-Thermal-
    # Cache ist — der bezieht seit Mai 2026 keine Precip-Variablen mehr
    # (CH1/CH2 liefern Precip ueber den Surface-Batch).
    th.setdefault("precipitation", [0.0] * num_hours)
    th.setdefault("precipitation_probability", [0] * num_hours)
    th.setdefault("precipitation_coverage", [0.0] * num_hours)
    th.setdefault("precipitation_class", ["dry"] * num_hours)
    th.setdefault("precipitation_n_rps", [0] * num_hours)

    from engine.synoptic_context import classify_precip_pattern

    for i in range(num_hours):
        # precipitation: Hybrid-Filter ueber dichte RPs.
        precip_vals = [
            d["hourly"].get("precipitation", [None])[i]
            for d in dense_data_list
            if i < len(d.get("hourly", {}).get("precipitation", []))
        ]
        valid_precip = [v for v in precip_vals if v is not None]

        if valid_precip:
            peak = max(valid_precip)
            n_wet = sum(1 for v in valid_precip if v > config.PRECIP_NOISE_MM)
            coverage = n_wet / len(valid_precip)

            if peak >= config.PRECIP_SIGNIFICANT_MM:
                final_precip = peak
            elif peak > config.PRECIP_NOISE_MM and coverage >= config.PRECIP_COVERAGE_QUORUM:
                final_precip = peak
            else:
                final_precip = 0.0

            th["precipitation"][i] = final_precip
            th["precipitation_coverage"][i] = round(coverage, 2)
            th["precipitation_n_rps"][i] = len(valid_precip)
            th["precipitation_class"][i] = classify_precip_pattern(coverage, peak)

        # precipitation_probability: konservatives max() ueber dichte RPs.
        prob_vals = [
            d["hourly"].get("precipitation_probability", [None])[i]
            for d in dense_data_list
            if i < len(d.get("hourly", {}).get("precipitation_probability", []))
        ]
        valid_prob = [v for v in prob_vals if v is not None]
        if valid_prob and "precipitation_probability" in th:
            th["precipitation_probability"][i] = max(valid_prob)

    return target


def _aggregate_regional_data(data_list):
    """
    Generalisierte Source-Area Aggregation:
    - Wolken: 30%-Perzentil -> findet regionale Sonnenfenster (Blue Holes)
    - Niederschlag (precipitation/rain): Hybrid-Filter (DWD operational seit
      2012, Ebert 2008 Neighborhood Method):
        * Peak >= SIGNIFICANT_MM        → durchlassen (echte Zelle)
        * NOISE_MM <= Peak < SIGNIFICANT → 30%-Quorum (Stratiform-Schutz)
        * Peak < NOISE_MM               → 0.0 (Modell-Rauschen)
      Zusaetzlich wird `precipitation_coverage` (0.0-1.0) als Anteil
      Referenzpunkte mit Regen > NOISE_MM durchgereicht — Decision-Engine
      kann daraus spaeter RAIN-SCATTERED vs RAIN-WIDESPREAD ableiten.
    - precipitation_probability: max() ueber alle RPs (konservativ).
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

    # Coverage-Array initialisieren (parallel zu precipitation):
    # Anteil der RPs mit Regen > NOISE_MM, 0.0-1.0. Wird auch bei trockenen
    # Stunden auf 0.0 gesetzt, damit das Feld luecklos im Cache liegt.
    primary["hourly"].setdefault("precipitation_coverage", [0.0] * num_hours)
    # Klassen-Spur (widespread/scattered/isolated/dry) — abgeleitet aus
    # coverage + peak via synoptic_context.classify_precip_pattern.
    # Defaults auf "dry", damit das Feld luecklos im Cache liegt.
    primary["hourly"].setdefault("precipitation_class", ["dry"] * num_hours)
    # Anzahl Referenzpunkte (fuer Transparenz im LLM-Datenblock).
    primary["hourly"].setdefault("precipitation_n_rps", [0] * num_hours)

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
            # 30%-Perzentil: findet regionale Sonnenfenster (Blue Holes).
            # Skaliert mit der Punktzahl — bei 4 RPs Index 1 (=25%), bei 7 RPs
            # Index 2 (=29%), bei 10 RPs Index 3 (=30%). Konsistente Statistik
            # unabhaengig davon, wie viele Referenzpunkte pro Region existieren.
            n = len(point_cloud_values)
            target_idx = max(0, min(n - 1, int(0.3 * n)))
            rep = point_cloud_values[target_idx]
            primary["hourly"]["cloud_cover_low"][i] = int(rep["low"])
            primary["hourly"]["cloud_cover_mid"][i] = int(rep["mid"])
            primary["hourly"]["cloud_cover_high"][i] = int(rep["high"])
            primary["hourly"]["cloud_cover"][i] = int(rep["total"])

        # Nur Wolken + Niederschlag aggregieren; Rest = Spot-Punkt (primary bleibt)
        for k in all_params:
            if k in CLOUD_PARAMS:
                continue
            if k not in PRECIP_USE_MIN:
                continue

            vals = [d["hourly"].get(k, [None])[i] for d in data_list if i < len(d.get("hourly", {}).get(k, []))]
            valid_vals = [v for v in vals if v is not None]
            if not valid_vals:
                continue

            if k == "precipitation_probability":
                # POP ist bereits eine Wahrscheinlichkeit (0-100). max() ist
                # konservativ — gibt die hoechste regionale Schauer-Chance an.
                primary["hourly"][k][i] = max(valid_vals)
                continue

            # precipitation / rain in mm/h: Hybrid-Filter
            peak = max(valid_vals)
            n_wet = sum(1 for v in valid_vals if v > config.PRECIP_NOISE_MM)
            coverage = n_wet / len(valid_vals)

            if peak >= config.PRECIP_SIGNIFICANT_MM:
                # Echte Schauerzelle — durchlassen, auch wenn nur 1 RP.
                primary["hourly"][k][i] = peak
            elif peak > config.PRECIP_NOISE_MM and coverage >= config.PRECIP_COVERAGE_QUORUM:
                # Stratiform leichter Regen — Quorum verlangen, Rauschen filtern.
                primary["hourly"][k][i] = peak
            else:
                # Reines Modell-Rauschen oder isolierter Trace-Wert.
                primary["hourly"][k][i] = 0.0

            # Coverage + Klasse + RP-Anzahl pro Stunde speichern
            # (nur an precipitation gekoppelt, nicht an rain).
            if k == "precipitation":
                primary["hourly"]["precipitation_coverage"][i] = round(coverage, 2)
                primary["hourly"]["precipitation_n_rps"][i] = len(valid_vals)
                # Klasse aus FINALEM precipitation-Wert + Coverage ableiten.
                # Wichtig: peak (vor Hybrid-Filter) nicht den durch Filter
                # gesetzten Wert verwenden — sonst wuerde "isolated" bei
                # Stratiform-Cut falsch werden.
                from engine.synoptic_context import classify_precip_pattern
                primary["hourly"]["precipitation_class"][i] = classify_precip_pattern(
                    coverage, peak
                )
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
    # CH2 (MeteoSwiss, 2.1km, 5d) als Mid-Tier zwischen CH1 (33h) und EU (13km).
    # Sowohl Spot- als auch Region-Pfad reichen CH1+CH2 durch (Region seit Mai 2026).
    hourly_ch2_surface = data_ch2.get("hourly", {}) if data_ch2 else {}

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
    # Surface ist 4-Tier: CH1 (1.1km, 33h) → CH2 (2.1km, 5d) → D2 (2.2km, 48h)
    # → EU (13km, Notfall). D2 als Tier-3 faengt Spots ausserhalb der CH-
    # Coverage auf (Tessin Sued, Walliser Suedtaeler, suedl. Engadin) — Pan-
    # Europa-2.2km schlaegt EU-13km im Grenzgebiet deutlich. EU greift nur
    # noch Tag 3+ wenn weder CH2 noch D2 valide Werte liefern.
    dates = sorted(list(set([t[:10] for t in times_base])))
    thermal_model_by_day = {}
    wind_model_by_day = {}
    # Quellen-Tracking: Kurzcode pro Tag, exposed via api_weather → Frontend.
    # Codes: ch1 / ch2 / d2 / eu (siehe docs/WETTERMODELLE.md Tier-Layout).
    surface_source_by_day = {}
    for d in dates:
        thermal_model_by_day[d] = hourly_thermal if is_model_valid_for_day(hourly_thermal, d, "temperature_2m") else hourly_fallback
        # 4-Tier Surface-Voting (variable bleibt aus historischen Gruenden
        # 'wind_model_by_day' — sie steuert aber ALLE CH_SURFACE_PARAMS).
        if is_model_valid_for_day(hourly_wind, d, "wind_speed_10m"):
            wind_model_by_day[d] = hourly_wind            # Tier 1: CH1
            surface_source_by_day[d] = "ch1"
        elif is_model_valid_for_day(hourly_ch2_surface, d, "wind_speed_10m"):
            wind_model_by_day[d] = hourly_ch2_surface     # Tier 2: CH2
            surface_source_by_day[d] = "ch2"
        elif is_model_valid_for_day(hourly_thermal, d, "wind_speed_10m"):
            wind_model_by_day[d] = hourly_thermal         # Tier 3: D2 (Grenzgebiet)
            surface_source_by_day[d] = "d2"
        else:
            wind_model_by_day[d] = hourly_fallback        # Tier 4: EU (Notfall)
            surface_source_by_day[d] = "eu"

    hourly_data = {}
    pressure_level_data = {}

    # CH_SURFACE_PARAMS: Variablen, fuer die Tag-Voting CH1->CH2->EU gilt.
    # Mai 2026 erweitert von 3 Wind-Vars auf alle CH-faehigen Surface-Variablen
    # (siehe config.CH_SURFACE_PARAMS). Andere Surface-Vars (soil, updraft)
    # kommen weiterhin aus thermal_model_by_day (D2 -> EU).
    surface_ch_override_params = list(config.CH_SURFACE_PARAMS)
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

        # Surface-Override: alle CH-faehigen Surface-Variablen aus CH1/CH2/EU
        # (Tag-Voting w_src). Liegt der Wert vor (nicht None), uebersteuert er
        # den D2/EU-Wert aus thermal_model_by_day. So bekommen Spots eine
        # einheitliche CH-Kalibrierung fuer Wind+Wolken+Temp+Strahlung+Precip
        # statt der frueheren Mischung CH-fuer-Wind / D2-fuer-Rest.
        if i_wind >= 0:
            for param in surface_ch_override_params:
                val_w = w_src.get(param, [None])[i_wind] if i_wind < len(w_src.get(param, [])) else None
                if val_w is not None:
                    entry[param] = val_w

        # precipitation_coverage / _class / _n_rps sind KEIN API-Param sondern
        # abgeleitet aus _aggregate_regional_data + _override_precip_with_dense_rps.
        # Nur bei Region-Aggregation vorhanden. Bei Spots: coverage=1.0, class="dry",
        # n_rps=1.
        if i_therm >= 0:
            for derived_key in ("precipitation_coverage",
                                "precipitation_class",
                                "precipitation_n_rps"):
                arr = t_src.get(derived_key, [])
                if i_therm < len(arr) and arr[i_therm] is not None:
                    entry[derived_key] = arr[i_therm]

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
    return hourly_data, pressure_level_data, surface_source_by_day


def _build_param_lists():
    """Baut die Parameter-Listen für jeden Modell-Call.

    Modell-Rollen (siehe config.py Wettermodell-Sektion, docs/WETTERMODELLE.md):
      - wind_params (CH1/CH2): alle Surface-Variablen die MeteoSwiss-Modelle
        ueber Open-Meteo exponieren. Kein PL (CH1/CH2 liefern keine).
      - thermal_params (D2): D2-spezifische Surface (soil, updraft) +
        CH_SURFACE_PARAMS (Tier-3 fuer CH-rand-Spots) + alle PL-Daten.
        Tag 1-2 hochaufgeloest, ab Tag 3 leer → faellt auf EU.
      - fallback_params (EU): vollstaendiges Backup (Surface + PL) fuer
        Tag 3-5 ausserhalb der CH-Coverage.
      - gfs_params: BLH + lifted_index + convective_inhibition.
    """
    # Surface: alle Variablen die CH1/CH2 ueber Open-Meteo liefern (Mai 2026
    # verifiziert). PL wird NICHT angefragt — CH-Modelle geben dort null zurueck.
    wind_params = list(config.CH_SURFACE_PARAMS)

    # Thermal-Batch (D2):
    # - D2-spezifische Surface (soil, updraft) — CH-Modelle haben sie nicht.
    # - CH_SURFACE_PARAMS — als Tier-3-Fallback fuer Spots ausserhalb der
    #   CH1/CH2-Coverage. D2 ist Pan-Europa-2.2km, deutlich besser als EU-13km
    #   im Grenzgebiet (Tessin Sued, Walliser Suedtaeler, suedl. Engadin).
    #   Liefert auch Region-Niederschlag-Aggregation auf 2.2 km.
    # - Alle PL-Variablen (Hoehenwind, T_*hPa, Geopotenzial).
    thermal_extra_surface = [
        "soil_moisture_0_to_1cm",
        "soil_temperature_0cm",
        "updraft",
    ]
    thermal_params = (
        thermal_extra_surface
        + list(config.CH_SURFACE_PARAMS)
        + list(config.PRESSURE_LEVEL_PARAMS)
    )

    # Fallback (EU): vollstaendig — Notfall fuer Tag 3-5 ausserhalb CH-Coverage.
    fallback_params = list(config.HOURLY_PARAMS) + list(config.PRESSURE_LEVEL_PARAMS)

    # GFS: BLH + supplementary only.
    gfs_params = list(config.GFS_SUPPLEMENTARY_PARAMS) + list(config.GFS_CROSSCHECK_PARAMS)

    return wind_params, thermal_params, fallback_params, gfs_params


def _compute_region_spotmedian_thermals(all_data, spots, all_regions):
    """Berechnet pro Region den Spot-Median fuer Thermik-Output (max_h/climb/lcl).

    Hintergrund: Refpoint-aggregierte Region-Thermik traf Pilot-Realitaet schlecht
    (median |Bias| 794m gegen Spot-Median, 16/23 Regionen >100m zu tief). Mai 2026
    Live-Test gegen Wallis 3500-4000m Pilot-Realitaet: nur Spot-Median trifft.
    Refpoint-Median (B) und Sheridan-Lapse (D) liessen Wallis 0/4 in der Treffer-
    zone. Spot-Median verschiebt 16 von 23 Regionen >100m, davon 14 um >200m,
    16/23 Wallis-aehnliche Regionen werden ins richtige Niveau gehoben.

    Wind / Wolken / Niederschlag bleiben Refpoint-aggregiert (funktionieren gut).
    Nur max_height / climb_rate / lcl werden pro Stunde mit Spot-Median ueber-
    schrieben — via compute_daily_thermals(..., spotmedian_override=...).

    Schwelle: n_spots >= SPOT_MEDIAN_MIN_SPOTS (3). Darunter Refpoint-Pfad.

    Returns: {rid: {ts: {"max_height": int, "climb_rate": float, "lcl": int}}}
    """
    # Map analyse_region (display) -> rid
    region_display_to_rid = {r["region"]: r["id"] for r in all_regions}

    # Gruppiere Spot-Thermals nach Region
    thermals_by_region: dict = {}  # {rid: [thermals_dict, ...]}
    for spot in spots:
        name = spot["name"]
        analyse_region = spot.get("analyse_region")
        if not analyse_region:
            continue
        rid = region_display_to_rid.get(analyse_region)
        if not rid or name not in all_data:
            continue
        sdata = all_data[name]
        hourly = sdata.get("hourly_data") or {}
        pld = sdata.get("pressure_level_data") or {}
        elev = sdata.get("elevation_m") or 850
        try:
            therm = compute_daily_thermals(
                hourly, pld, elev, config.PRESSURE_LEVELS,
                slope_azimuth=spot.get("slope_azimuth"),
                slope_angle=spot.get("slope_angle"),
                region_id=analyse_region,
            )
        except Exception as exc:
            print(f"  [WARN] Spot-Thermik {name}: {exc}")
            continue
        thermals_by_region.setdefault(rid, []).append(therm)

    # Spot-Median pro Stunde
    overrides: dict = {}
    for rid, spot_therms in thermals_by_region.items():
        if len(spot_therms) < SPOT_MEDIAN_MIN_SPOTS:
            continue
        all_ts: set = set()
        for s in spot_therms:
            all_ts.update(s.keys())
        ov_per_ts: dict = {}
        for ts in all_ts:
            mh_vals = [s.get(ts, {}).get("max_height") for s in spot_therms]
            mh_vals = [v for v in mh_vals if isinstance(v, (int, float))]
            cr_vals = [s.get(ts, {}).get("climb_rate") for s in spot_therms]
            cr_vals = [v for v in cr_vals if isinstance(v, (int, float))]
            lcl_vals = [s.get(ts, {}).get("lcl") for s in spot_therms]
            lcl_vals = [v for v in lcl_vals if isinstance(v, (int, float))]
            if len(mh_vals) < SPOT_MEDIAN_MIN_SPOTS:
                continue
            ov = {"max_height": int(statistics.median(mh_vals))}
            if cr_vals:
                ov["climb_rate"] = round(statistics.median(cr_vals), 2)
            if lcl_vals:
                ov["lcl"] = int(statistics.median(lcl_vals))
            ov_per_ts[ts] = ov
        if ov_per_ts:
            overrides[rid] = {
                "override": ov_per_ts,
                "n_spots": len(spot_therms),
            }
    return overrides


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
    region_refs = {}  # {region_id: [[lat,lon], ...]} — 7 Haupt-RPs pro Region
    region_only_points = []  # Punkte die NUR von Regionen gebraucht werden
    region_only_index = {}   # {(lat_r, lon_r): index_in_region_only_points}
    # Vollstaendige Dedup ALLER Region-RPs (shared + only) fuer den CH1/CH2-
    # Region-Batch. Wird gebraucht, weil die Spot-Batches batch_wind/batch_ch2
    # spot_lats-keyed sind (1 Punkt pro Spot) und damit shared Region-Refs
    # NICHT abdecken. Eigener Index, damit der Batch direkt indizierbar bleibt.
    region_all_ref_points = []
    region_all_ref_index = {}  # {(lat_r, lon_r): index_in_region_all_ref_points}
    for region in all_regions:
        rid = region["id"]
        region_refs[rid] = region["reference_points"]
        for pt in region["reference_points"]:
            key = (round(pt[0], 4), round(pt[1], 4))
            if key not in point_index and key not in region_only_index:
                region_only_index[key] = len(region_only_points)
                region_only_points.append([round(pt[0], 4), round(pt[1], 4)])
            if key not in region_all_ref_index:
                region_all_ref_index[key] = len(region_all_ref_points)
                region_all_ref_points.append([round(pt[0], 4), round(pt[1], 4)])

    # Niederschlags-spezifische 16 dichte RPs pro Region (CVT).
    # Eigener Batch — eigene Indizes, keine Dedup mit Spot-/Region-Haupt-RPs.
    # Wenn Datei fehlt, bleibt precip_refs leer und der Override wird uebersprungen
    # (Fallback auf 7-RP-Aggregation).
    precip_refs = get_precip_reference_points()  # {rid: [[lat,lon], ...]}
    precip_points_flat: list[list[float]] = []
    precip_point_index: dict[tuple[float, float], int] = {}
    for rid, pts in precip_refs.items():
        for pt in pts:
            key = (round(pt[0], 4), round(pt[1], 4))
            if key not in precip_point_index:
                precip_point_index[key] = len(precip_points_flat)
                precip_points_flat.append([round(pt[0], 4), round(pt[1], 4)])

    spot_lats = [str(s["latitude"]) for s in spots]
    spot_lons = [str(s["longitude"]) for s in spots]
    unique_lats = [str(p[0]) for p in unique_points]
    unique_lons = [str(p[1]) for p in unique_points]

    shared_region_pts = sum(1 for r in all_regions for pt in r["reference_points"]
                           if (round(pt[0], 4), round(pt[1], 4)) in point_index)
    print(f"[INFO] {len(spots)} Spots, {len(unique_points)} Spot-Punkte (dedup), "
          f"{len(all_regions)} Regionen ({shared_region_pts} geteilte + {len(region_only_points)} eigene Punkte)")
    if precip_points_flat:
        print(f"[INFO] +{len(precip_points_flat)} dichte Niederschlags-RPs "
              f"({len(precip_refs)} Regionen × {len(next(iter(precip_refs.values()), []))})")

    wind_params, thermal_params, fallback_params, gfs_params = _build_param_lists()

    # === Phase 2: 6+1 Batch-API-Calls ===
    # +1 = optionaler Precip-Dense-Batch (16 RPs pro Region, nur Niederschlag)
    batch_wind = None
    batch_thermal = None
    batch_fallback = None
    batch_gfs = None
    batch_ch1 = None
    batch_ch2 = None
    batch_precip_dense = None

    try:
        # 1. CH1-Surface (Spot-Punkte, alle CH-Surface-Vars, 33h Horizont)
        # Primaerquelle fuer Tag 1: MeteoSwiss ICON-CH1 (1.1 km, CH-kalibriert).
        # Liefert wind/wolken/temp/strahlung/precip/cape. Kein PL (CH1 hat keine).
        print(f"[API] Batch CH1-Surface: {len(spots)} Punkte, {len(wind_params)} Vars, "
              f"Modell {config.SURFACE_PRIMARY_MODEL}")
        batch_wind = _chunked_api_get(spot_lats, spot_lons, {
            "models": config.SURFACE_PRIMARY_MODEL,
            "hourly": ",".join(wind_params),
            "forecast_days": config.FORECAST_DAYS_CH1,
            "timezone": config.TIMEZONE,
        }, API_BATCH_TIMEOUT, label="Batch-CH1-Surface")
        print(f"  [OK] {len(batch_wind)} CH1-Surface-Antworten")
        # batch_ch1 ist mit batch_wind identisch (gleiches Modell, gleiche Lats,
        # gleiche Params). Kein zweiter API-Call mehr fuer Multi-Gust-Merge.
        batch_ch1 = batch_wind

        time.sleep(API_DELAY_BETWEEN_CALLS)

        # 2. Thermal (deduplizierte Punkte, D2-spezifische Surface + PL-Daten)
        # D2 (DWD, 2.2 km, 48h) deckt soil_moisture/soil_temperature/updraft +
        # Pressure-Level. Surface-Standard-Variablen kommen jetzt aus CH1/CH2.
        print(f"[API] Batch Thermal/PL: {len(unique_points)} Punkte, "
              f"{len(thermal_params)} Vars, Modell {config.PRESSURE_LEVEL_PRIMARY_MODEL}")
        batch_thermal = _chunked_api_get(unique_lats, unique_lons, {
            "models": config.PRESSURE_LEVEL_PRIMARY_MODEL,
            "hourly": ",".join(thermal_params),
            "forecast_days": config.FORECAST_DAYS_D2,
            "timezone": config.TIMEZONE,
        }, API_BATCH_TIMEOUT, label="Batch-Thermal")
        print(f"  [OK] {len(batch_thermal)} Thermal-Antworten")

        time.sleep(API_DELAY_BETWEEN_CALLS)

        # 3. Fallback (deduplizierte Punkte, ALLE Vars — Backup für Tag 3-5 + Ausfälle)
        # EU (DWD, 13 km, 5d) als Notfallquelle fuer Surface (CH-Coverage-Rand)
        # und als Tier-2 fuer PL-Daten ab Tag 3.
        print(f"[API] Batch Fallback: {len(unique_points)} Punkte, {len(fallback_params)} Vars, "
              f"Modell {config.SURFACE_FALLBACK_MODEL}")
        batch_fallback = _chunked_api_get(unique_lats, unique_lons, {
            "models": config.SURFACE_FALLBACK_MODEL,
            "hourly": ",".join(fallback_params),
            "forecast_days": config.FORECAST_DAYS_EU,
            "timezone": config.TIMEZONE,
        }, API_BATCH_TIMEOUT, label="Batch-Fallback")
        print(f"  [OK] {len(batch_fallback)} Fallback-Antworten")

        time.sleep(API_DELAY_BETWEEN_CALLS)

        # 4. GFS (Spot-Punkte, BLH + Supplement-Vars)
        # GFS ist seit Mai 2026 die EINZIGE BLH-Quelle (ICON-BLH-Felder
        # kommen leer zurueck). Plus lifted_index, convective_inhibition.
        print(f"[API] Batch GFS (BLH+Supplement): {len(spots)} Punkte, "
              f"{len(gfs_params)} Vars, Modell {config.BLH_MODEL}")
        batch_gfs = _chunked_api_get(spot_lats, spot_lons, {
            "models": config.BLH_MODEL,
            "hourly": ",".join(gfs_params),
            "forecast_days": config.FORECAST_DAYS_GFS,
            "timezone": config.TIMEZONE,
        }, API_BATCH_TIMEOUT, label="Batch-GFS")
        print(f"  [OK] {len(batch_gfs)} GFS-Antworten")

        time.sleep(API_DELAY_BETWEEN_CALLS)

        # 5. CH2-Surface (Spot-Punkte, alle CH-Surface-Vars, 5d Horizont)
        # Tier-2 fuer Tag 2-5: MeteoSwiss ICON-CH2 (2.1 km, CH-kalibriert).
        # Identische Params wie CH1, deckt aber die kompletten 5 Tage ab.
        # Wird zusaetzlich fuer Multi-Gust-Merge auf wind_gusts_10m genutzt.
        print(f"[API] Batch CH2-Surface: {len(spots)} Punkte, {len(wind_params)} Vars, "
              f"Modell {config.SURFACE_SECONDARY_MODEL}")
        try:
            batch_ch2 = _chunked_api_get(spot_lats, spot_lons, {
                "models": config.SURFACE_SECONDARY_MODEL,
                "hourly": ",".join(wind_params),
                "forecast_days": config.FORECAST_DAYS_CH2,
                "timezone": config.TIMEZONE,
            }, API_BATCH_TIMEOUT, label="Batch-CH2-Surface")
            print(f"  [OK] {len(batch_ch2)} CH2-Surface-Antworten")
        except Exception as e:
            print(f"  [WARN] CH2-Surface-Batch fehlgeschlagen (Fallback auf EU fuer Tag 2-5): {e}")
            batch_ch2 = None

        # 7. Precip-Dense (16 RPs pro Region, NUR Niederschlag) — optional.
        # Schlanker Batch (~16 weighted bei 464 Punkten, 2 Vars), Failure
        # nicht kritisch: Region-Aggregation fällt automatisch auf 7 RPs zurück.
        if precip_points_flat:
            try:
                time.sleep(API_DELAY_BETWEEN_CALLS)
                precip_lats = [str(p[0]) for p in precip_points_flat]
                precip_lons = [str(p[1]) for p in precip_points_flat]
                precip_params = ["precipitation", "precipitation_probability"]
                print(f"[API] Batch Precip-Dense: {len(precip_points_flat)} Punkte, "
                      f"{len(precip_params)} Vars, Modell {config.PRECIP_MODEL}")
                batch_precip_dense = _chunked_api_get(precip_lats, precip_lons, {
                    "models": config.PRECIP_MODEL,
                    "hourly": ",".join(precip_params),
                    "forecast_days": config.FORECAST_DAYS,
                    "timezone": config.TIMEZONE,
                }, API_BATCH_TIMEOUT, label="Batch-Precip-Dense")
                print(f"  [OK] {len(batch_precip_dense)} Precip-Dense-Antworten")
            except Exception as e:
                print(f"  [WARN] Precip-Dense-Batch fehlgeschlagen (nicht kritisch, Fallback 7-RP): {e}")
                batch_precip_dense = None

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

        hourly_data, pressure_level_data, data_sources = result

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
            "data_sources": data_sources,
        }

    # === Phase 4: Region-Wetter aggregieren ===
    # Eigene Batch-Calls fuer Region-only Punkte (nicht im Spot-Batch enthalten)
    batch_region_thermal = None
    batch_region_fallback = None
    # CH1/CH2-Region-Batches: keyed auf ALLE Region-RPs (region_all_ref_points),
    # nicht nur region_only — die Spot-Surface-Batches (batch_wind=CH1, batch_ch2)
    # sind spot_lats-keyed und liefern KEINE Daten fuer einzelne Region-Refs.
    # Damit profitieren Regionen ab Tag 2-5 von CH2 (2.1 km, CH-kalibriert) statt
    # nur EU (13 km).
    batch_region_ch1 = None
    batch_region_ch2 = None

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

    # CH1/CH2 fuer ALLE Region-Refs (shared + only). Eigene Batches mit eigenem
    # Index. Failure jeweils nicht kritisch — Tier-Voting faellt automatisch
    # auf D2/EU zurueck.
    if region_all_ref_points:
        ref_lats = [str(p[0]) for p in region_all_ref_points]
        ref_lons = [str(p[1]) for p in region_all_ref_points]

        try:
            time.sleep(API_DELAY_BETWEEN_CALLS)
            print(f"[API] Batch Region-CH1: {len(region_all_ref_points)} Punkte, "
                  f"Modell {config.SURFACE_PRIMARY_MODEL}")
            batch_region_ch1 = _chunked_api_get(ref_lats, ref_lons, {
                "models": config.SURFACE_PRIMARY_MODEL,
                "hourly": ",".join(wind_params),
                "forecast_days": config.FORECAST_DAYS_CH1,
                "timezone": config.TIMEZONE,
            }, API_BATCH_TIMEOUT, label="Batch-Region-CH1")
            print(f"  [OK] {len(batch_region_ch1)} Region-CH1-Antworten")
        except Exception as e:
            print(f"  [WARN] Region-CH1-Batch fehlgeschlagen (Fallback auf D2/EU): {e}")
            batch_region_ch1 = None

        try:
            time.sleep(API_DELAY_BETWEEN_CALLS)
            print(f"[API] Batch Region-CH2: {len(region_all_ref_points)} Punkte, "
                  f"Modell {config.SURFACE_SECONDARY_MODEL}")
            batch_region_ch2 = _chunked_api_get(ref_lats, ref_lons, {
                "models": config.SURFACE_SECONDARY_MODEL,
                "hourly": ",".join(wind_params),
                "forecast_days": config.FORECAST_DAYS_CH2,
                "timezone": config.TIMEZONE,
            }, API_BATCH_TIMEOUT, label="Batch-Region-CH2")
            print(f"  [OK] {len(batch_region_ch2)} Region-CH2-Antworten")
        except Exception as e:
            print(f"  [WARN] Region-CH2-Batch fehlgeschlagen (Fallback auf D2/EU): {e}")
            batch_region_ch2 = None

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
            # Thermischen Referenzpunkt bestimmen: RP mit hoechster mittlerer
            # Strahlung waehrend Flugstunden (repraesentativster Punkt der Region).
            # Wind+Wolken-Aggregation sind reihenfolge-unabhaengig (Median/Perzentil).
            best_idx = _best_thermal_rp_index(thermal_data_list)
            if best_idx != 0:
                thermal_data_list[0], thermal_data_list[best_idx] = (
                    thermal_data_list[best_idx], thermal_data_list[0]
                )
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
            best_idx_fb = _best_thermal_rp_index(fallback_data_list)
            if best_idx_fb != 0:
                fallback_data_list[0], fallback_data_list[best_idx_fb] = (
                    fallback_data_list[best_idx_fb], fallback_data_list[0]
                )
            data_fallback_r = _aggregate_regional_data(fallback_data_list)
            data_fallback_r = _aggregate_wind_across_points(fallback_data_list)

        # Niederschlag mit dichten 16 RPs ueberschreiben (falls verfuegbar).
        # Wirkt auf data_thermal_r UND data_fallback_r — beide werden im
        # Spot-Merge gelesen. Wenn batch_precip_dense fehlt oder die Region
        # keine 16 RPs hat, bleibt die 7-RP-Aggregation aktiv (Fallback).
        if batch_precip_dense and rid in precip_refs:
            dense_list = []
            for pt in precip_refs[rid]:
                key = (round(pt[0], 4), round(pt[1], 4))
                idx = precip_point_index.get(key)
                if idx is not None and idx < len(batch_precip_dense):
                    dense_list.append(batch_precip_dense[idx])
            if dense_list:
                if data_thermal_r is not None:
                    _override_precip_with_dense_rps(data_thermal_r, dense_list)
                if data_fallback_r is not None:
                    _override_precip_with_dense_rps(data_fallback_r, dense_list)

        # CH1/CH2 fuer Region — ueber ALLE Refs aggregieren (analog Thermal).
        # Tier-Voting in _process_spot_weather waehlt dann pro Tag CH1->CH2->D2->EU.
        data_ch1_r = None
        if batch_region_ch1:
            ch1_data_list = []
            for pt in refs:
                key = (round(pt[0], 4), round(pt[1], 4))
                idx = region_all_ref_index.get(key)
                if idx is not None and idx < len(batch_region_ch1):
                    ch1_data_list.append(copy.deepcopy(batch_region_ch1[idx]))
            if ch1_data_list:
                data_ch1_r = _aggregate_regional_data(ch1_data_list)
                data_ch1_r = _aggregate_wind_across_points(ch1_data_list)

        data_ch2_r = None
        if batch_region_ch2:
            ch2_data_list = []
            for pt in refs:
                key = (round(pt[0], 4), round(pt[1], 4))
                idx = region_all_ref_index.get(key)
                if idx is not None and idx < len(batch_region_ch2):
                    ch2_data_list.append(copy.deepcopy(batch_region_ch2[idx]))
            if ch2_data_list:
                data_ch2_r = _aggregate_regional_data(ch2_data_list)
                data_ch2_r = _aggregate_wind_across_points(ch2_data_list)

        # Tier-1-Wind-Quelle (= 'data_wind' fuer _process_spot_weather):
        # NUR CH1 (region-aggregiert). Wenn CH1 fehlt, bleibt Tier-1 leer und das
        # Voting faellt sauber durch: Tier-2 CH2 (via data_ch2), Tier-3 D2 (via
        # data_thermal), Tier-4 EU (via data_fallback). Wichtig: nicht auf D2
        # zurueckfallen, sonst wuerde data_wind=D2 als "ch1" mislabeled werden
        # (Bug vor Mai 2026: Region-data_sources zeigte "ch1" obwohl D2 lief).
        data_wind_r = data_ch1_r

        try:
            result = _process_spot_weather(
                f"Region:{rname}", data_wind_r, data_thermal_r, data_fallback_r,
                None, elev_ref,
                data_ch1=data_ch1_r, data_ch2=data_ch2_r,
            )
        except Exception as e:
            print(f"  [FEHLER] Region {rname}: {e}")
            continue

        if result is None:
            continue

        hourly_data, pressure_level_data, data_sources = result
        region_data[rid] = {
            "region_id": rid,
            "region_name": rname,
            "elevation_ref": elev_ref,
            "hourly_data": hourly_data,
            "pressure_level_data": pressure_level_data,
            "reference_points": refs,
            "data_sources": data_sources,
        }

    print(f"[INFO] {len(region_data)} Regionen verarbeitet")

    # === Phase 4b: Spot-Median-Override fuer Region-Thermik ===
    # Mai 2026: Refpoint-Aggregation traf Pilot-Realitaet schlecht
    # (median |Bias| 794m, 16/23 Regionen >100m zu tief). Spot-Median ueberschreibt
    # max_height/climb_rate/lcl pro Stunde. Wind/Wolken/Niederschlag bleiben
    # Refpoint-aggregiert.
    print(f"[INFO] Phase 4b: Spot-Median-Override fuer Region-Thermik")
    try:
        overrides = _compute_region_spotmedian_thermals(all_data, spots, all_regions)
        n_applied = 0
        for rid, info in overrides.items():
            if rid in region_data:
                region_data[rid]["thermals_spotmedian"] = info["override"]
                region_data[rid]["thermals_spotmedian_n_spots"] = info["n_spots"]
                n_applied += 1
        n_fallback = len(region_data) - n_applied
        print(f"  [OK] Spot-Median aktiv: {n_applied}/{len(region_data)} Regionen "
              f"(Refpoint-Fallback: {n_fallback} Regionen mit <{SPOT_MEDIAN_MIN_SPOTS} Spots)")
    except Exception as exc:
        import traceback
        print(f"  [WARN] Spot-Median-Override fehlgeschlagen: {exc}")
        traceback.print_exc()

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

        # data_sources verworfen — Legacy-Einzelabruf wird nur fuer Retries
        # genutzt; das Tracking laeuft im Hauptpfad fetch_all_spots.
        hourly_data, pressure_level_data, _ = result
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
