"""Synoptik-Kontext fuer den Wetterlage-Block im Wingcast und in der E-Mail.

Erzeugt deterministisch eine 5-Tages-Einordnung der Grosswetterlage:
- CH-Druckeinfluss (Hoch/Tief/neutral) aus pressure_msl-Mittel + Trend
- Druckzentren Europa via Mini-Druckraster (15 Punkte) und lokale Extrema
- Uebergeordnete Stroemung aus 700 hPa-Wind (Richtung, Staerke, Wochentrend)
- T850-Trend (Luftmassen-Charakter, waermer/kuehler)
- Niederschlagsmuster Nord vs. Sued der Alpen (Charakter + Tageszeit)
- Phaenomene: Foehn (aus foehn_indicators.py), Bise (deterministisch),
  Vb-/Genua-Tief (aus Druckraster)
- Schneefallgrenze (saisonal Maerz-Mai + Okt-Nov)
- Lage-Label in Pilotensprache ("Westlage", "Bisenlage", ...)
- Konfidenz je Tag (high/medium/low) — abnehmend mit Forecast-Distanz

Architektur (Stage-Inversion-Pattern, analog engine/decision_engine.py):
  Alle Klassifikatoren sind deterministische `decide_*`-Funktionen. Der LLM
  bekommt nur das fertige Strukturfeld, keine Rohzahlen. Jedes Feld traegt
  Provenance (`decided_by`, `inputs`, `thresholds`) fuer Audit-Logs.

Halluzinations-Schutz:
  - Whitelist im LLM-Skill (synoptic_overview.md): nur detektierte Phaenomene
    und Region-Labels duerfen genannt werden
  - Verbot synoptischer Etiketten ohne Daten-Backing (Kaltfront, Trog,
    Geopotential, hPa-Werte)
  - Post-Filter prueft Output auf Verbotsbegriffe und Source-Konsistenz
  - Bei API-Fehler oder leerer Detektion: Block wird weggelassen, kein Fallback-Text

Konventionen:
  - Jede Decision liefert `{value, decided_by, inputs, thresholds}` zurueck
  - Top-Level-Builder schreibt alle gefeuerten Decisions in
    `result["_synoptic_decisions_applied"]`
  - Audit-Log pro Tag in `data/synoptic_audit/<date>.json`
"""

import json
import logging
import math
import os
import statistics
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

import config

logger = logging.getLogger(__name__)


# Physik-Konstanten fuer Barometrische Reduktion
_GAS_CONSTANT_AIR_J_PER_KG_K = 287.058
_GRAVITY_M_PER_S2 = 9.80665


# ============================================================================
# OEFFENTLICHE API (Skeleton — wird in Phase 4 zusammengesetzt)
# ============================================================================

def build_synoptic_context(weather_cache: dict,
                           write_audit: bool = True) -> Optional[dict]:
    """Top-Level-Builder fuer den Wetterlage-Block.

    Reihenfolge der Detektion:
      1. Forecast-Dates aus Cache ableiten (max 5 Tage)
      2. CH-Tages-Snapshots (MSL, T850, gh850, 700hPa-Wind)
      3. Europa-Druckraster via API-Call (kann fehlen → graceful)
      4. Basis-Decisions: pressure_influence, flow_overhead, t850_trend
      5. Druckzentren pro Tag
      6. Bise + Vb-Lage (falls Grid vorhanden)
      7. Foehn-Summary (eigener API-Call, kann fehlen)
      8. Niederschlag Nord/Sued + Schneefallgrenze (saisonal)
      9. Konfidenz pro Tag
     10. Lage-Label (kombiniert)
     11. Audit-Log schreiben (optional)

    Args:
        weather_cache: Inhalt von data/wetterdaten.json (bereits geladen).
        write_audit: Schreibt Audit-JSON nach data/synoptic_audit/<date>.json.

    Returns:
        Strukturfeld mit allen Wetterlage-Daten und Provenance, oder None
        wenn die Basis-Detektion komplett fehlschlaegt.
    """
    decisions_applied: list[str] = []

    # 1. Forecast-Dates aus Cache extrahieren
    forecast_dates = _extract_forecast_dates(weather_cache, max_days=config.FORECAST_DAYS)
    if not forecast_dates:
        logger.warning("build_synoptic_context: keine Forecast-Dates im Cache")
        return None

    # 2. CH-Snapshots
    snapshots = aggregate_ch_daily_snapshot(weather_cache, forecast_dates)
    if snapshots is None:
        logger.warning("build_synoptic_context: aggregate_ch_daily_snapshot=None")
        return None
    decisions_applied.append("aggregate_ch_daily_snapshot")

    # 3. Europa-Druckraster (optional, graceful)
    grid = fetch_europe_pressure_grid(forecast_dates)
    if grid:
        decisions_applied.append("fetch_europe_pressure_grid")
    else:
        logger.info("build_synoptic_context: Druckraster nicht verfuegbar — "
                    "Druckzentren/Bise/Vb werden uebersprungen")

    # 4. Basis-Decisions
    pressure_influence = decide_pressure_influence(snapshots)
    decisions_applied.append("decide_pressure_influence")
    flow_overhead = decide_flow_overhead(snapshots)
    decisions_applied.append("decide_flow_overhead")
    t850_trend = decide_t850_trend(snapshots)
    decisions_applied.append("decide_t850_trend")

    # 5. Druckzentren pro Tag
    pressure_centers_per_day = []
    if grid:
        for date in forecast_dates:
            centers = find_pressure_centers(grid, date)
            pressure_centers_per_day.append({"date": date, "centers": centers})
        decisions_applied.append("find_pressure_centers")

    # 6. Bise + Vb-Lage
    if grid:
        bise = decide_bise(grid, snapshots, forecast_dates)
        decisions_applied.append("decide_bise")
        vb_lage = decide_vb_lage(grid, forecast_dates)
        decisions_applied.append("decide_vb_lage")
    else:
        bise = {"value": "unbekannt", "active_any_day": False,
                "per_day": [], "decided_by": "decide_bise",
                "source": "grid_unavailable"}
        vb_lage = {"value": "unbekannt", "active_any_day": False,
                   "per_day": [], "decided_by": "decide_vb_lage",
                   "source": "grid_unavailable"}

    # 7. Foehn
    foehn = decide_foehn_summary(forecast_dates)
    if foehn.get("source") != "fetch_failed":
        decisions_applied.append("decide_foehn_summary")
    else:
        decisions_applied.append("decide_foehn_summary(fetch_failed)")

    # 8. Niederschlag + Schneefallgrenze
    precip = decide_precip_pattern_nord_sued(weather_cache, forecast_dates)
    decisions_applied.append("decide_precip_pattern_nord_sued")

    # 8b. Wind-Fliegbarkeit (Anteile windkritischer Spots pro Tag/Seite) —
    # autoritative Basis fuer die Flug-Bilanz des LLM-Overviews.
    wind_pattern = decide_wind_pattern_nord_sued(weather_cache, forecast_dates)
    decisions_applied.append("decide_wind_pattern_nord_sued")

    # 8c. Flugwetter-Zonen (Synoptik 2.0): 4 Zonen mit Tagesfenstern +
    # Zugbahn-Detektor. Die Nord/Sued-Aggregate (8/8b) bleiben parallel
    # bestehen (Audit-Vergleichbarkeit); der LLM-Pfad nutzt die Zonen.
    try:
        zone_map = build_spot_zone_map()
        precip_zones = decide_precip_pattern_zones(weather_cache, forecast_dates,
                                                   zone_map)
        decisions_applied.append("decide_precip_pattern_zones")
        wind_zones = decide_wind_pattern_zones(weather_cache, forecast_dates,
                                               zone_map)
        decisions_applied.append("decide_wind_pattern_zones")
        zugbahn = decide_zugbahn(weather_cache, forecast_dates, zone_map)
        decisions_applied.append("decide_zugbahn")
    except Exception:
        logger.exception("Zonen-Aggregation fehlgeschlagen — "
                         "Block laeuft ohne Zonen-Felder weiter")
        precip_zones = None
        wind_zones = None
        zugbahn = None

    # 8d. Hoehenwind-Spitze je Region (neben dem Schweizer Mittel)
    try:
        aloft_regional = decide_aloft_regional(weather_cache, forecast_dates,
                                               build_spot_region_map())
        decisions_applied.append("decide_aloft_regional")
    except Exception:
        logger.exception("Hoehenwind regional fehlgeschlagen — Feld fehlt")
        aloft_regional = None

    # 8j. Modellvergleich (MeteoSchweiz, DWD, NOAA) auf allen Referenzpunkten
    try:
        modelle = modell_vergleich(forecast_dates, weather_cache.get("_regions") or {})
    except Exception:
        logger.exception("Modellvergleich fehlgeschlagen — Feld fehlt")
        modelle = None

    # 8i. Thermik und Basis je Zone
    try:
        thermik = thermik_zonen(weather_cache.get("_regions") or {}, forecast_dates)
    except Exception:
        logger.exception("Thermik-Zonen fehlgeschlagen — Feld fehlt")
        thermik = None

    # 8h. Starke Winde an einzelnen Startplaetzen (Prognosepunkte)
    try:
        starkwind = starkwind_punkte(weather_cache, forecast_dates, build_spot_region_map())
    except Exception:
        logger.exception("Starkwind-Check fehlgeschlagen — Feld fehlt")
        starkwind = None

    # 8g. Bise am Boden (Nordostwind im Mittelland) — Abgleich zur Synoptik
    try:
        bise_bod = bise_boden(weather_cache, forecast_dates, build_spot_region_map())
    except Exception:
        logger.exception("Bise-Bodencheck fehlgeschlagen — Feld fehlt")
        bise_bod = None

    # 8f. Frontsignatur in den eigenen Prognosedaten (Druck/Wind/T850/Regen)
    try:
        frontsignatur = detect_frontsignatur(weather_cache.get("_regions") or {},
                                             forecast_dates)
        if frontsignatur:
            decisions_applied.append("detect_frontsignatur")
    except Exception:
        logger.exception("Frontsignatur fehlgeschlagen — Feld fehlt")
        frontsignatur = None

    # 8e. DWD-Frontdurchgaenge (Zone, Typ, Zeitfenster) — fuer KI und Briefing
    try:
        fronten = load_dwd_frontdurchgaenge(forecast_dates)
        if fronten:
            decisions_applied.append("load_dwd_frontdurchgaenge")
    except Exception:
        logger.exception("Frontdurchgaenge fehlgeschlagen — Feld fehlt")
        fronten = None

    current_month = datetime.now().month
    ssg = decide_schneefallgrenze(snapshots, current_month)
    if ssg:
        decisions_applied.append("decide_schneefallgrenze")

    # 9. Konfidenz
    confidence = decide_confidence_per_day(len(forecast_dates))

    # 10. Lage-Label (kombiniert)
    lage_label = decide_lage_label(pressure_influence, flow_overhead,
                                   bise, foehn, vb_lage)
    decisions_applied.append("decide_lage_label")

    # Weiche Konvektions-Signale (Ensemble + Wolkentop) je Tag/Zone — die
    # Wetterlage soll Gewitter ERKENNEN koennen, nicht nur den 13-%-Code sehen.
    konvektion = None
    try:
        konvektion = summarize_convection(
            weather_cache.get("_regions") or {}, forecast_dates)
        if konvektion:
            decisions_applied.append("summarize_convection")
    except Exception:
        logger.exception("build_synoptic_context: summarize_convection fehlgeschlagen")

    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "forecast_dates": forecast_dates,
        "konvektion": konvektion,
        "lage_label": lage_label,
        "pressure_influence": pressure_influence,
        "flow_overhead": flow_overhead,
        "t850_trend": t850_trend,
        "pressure_centers_per_day": pressure_centers_per_day,
        "bise": bise,
        "vb_lage": vb_lage,
        "foehn": foehn,
        "precip_pattern": precip,
        "wind_pattern": wind_pattern,
        "precip_zones": precip_zones,
        "wind_zones": wind_zones,
        "aloft_regional": aloft_regional,
        "fronten": fronten,
        "frontsignatur": frontsignatur,
        "bise_boden": bise_bod,
        "starkwind_punkte": starkwind,
        "thermik_zonen": thermik,
        "modell_vergleich": modelle,
        "zugbahn": zugbahn,
        "schneefallgrenze": ssg,
        "confidence_per_day": [
            {"date": forecast_dates[i], "level": confidence[i]}
            for i in range(len(forecast_dates))
        ],
        "ch_snapshots": snapshots,
        "europe_grid": grid,
        "_synoptic_decisions_applied": decisions_applied,
    }

    if write_audit:
        try:
            _write_audit_log(result)
            _rotate_audit_logs()
        except Exception as e:
            logger.warning("Audit-Log schreiben fehlgeschlagen: %s", e)

    # Cache fuer UI/Email
    try:
        _write_synoptic_cache(result)
    except Exception as e:
        logger.warning("Synoptic-Cache schreiben fehlgeschlagen: %s", e)

    return result


# ============================================================================
# I/O: Cache + Audit-Log
# ============================================================================

def _extract_forecast_dates(weather_cache: dict, max_days: int = 5) -> list[str]:
    """Extrahiert die ersten N Forecast-Dates aus dem Cache (Spot-Daten)."""
    for spot_name, spot in weather_cache.items():
        if spot_name.startswith("_"):
            continue
        hd = spot.get("hourly_data", {})
        if not hd:
            continue
        dates = sorted({t[:10] for t in hd.keys()})
        return dates[:max_days]
    return []


def _atomic_write_json(path: Path, data: dict) -> None:
    """Atomic JSON write via tempfile + os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", delete=False,
        dir=str(path.parent), suffix=".tmp",
    )
    try:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, path)
    except Exception:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


def _write_synoptic_cache(result: dict) -> None:
    """Schreibt das Wetterlage-Strukturfeld nach data/synoptic_context.json."""
    _atomic_write_json(config.SYNOPTIC_CACHE_PATH, result)


def _write_audit_log(result: dict) -> None:
    """Schreibt Audit-JSON nach data/synoptic_audit/<date>.json.

    Date = Generierungsdatum (heute). Bei mehrfacher Generierung am selben
    Tag wird die Datei ueberschrieben (letzter Run gilt).
    """
    today = datetime.now().date().isoformat()
    audit_dir = Path(config.SYNOPTIC_AUDIT_DIR)
    audit_path = audit_dir / f"{today}.json"
    _atomic_write_json(audit_path, result)


def _rotate_audit_logs() -> None:
    """Loescht Audit-Files aelter als SYNOPTIC_AUDIT_KEEP_DAYS."""
    audit_dir = Path(config.SYNOPTIC_AUDIT_DIR)
    if not audit_dir.exists():
        return
    cutoff = datetime.now() - timedelta(days=config.SYNOPTIC_AUDIT_KEEP_DAYS)
    for f in audit_dir.glob("*.json"):
        try:
            # Filename ist YYYY-MM-DD.json
            file_date = datetime.fromisoformat(f.stem)
            if file_date < cutoff:
                f.unlink()
        except (ValueError, OSError):
            continue


def load_synoptic_cache() -> Optional[dict]:
    """Laedt das letzte Wetterlage-Strukturfeld aus dem Cache.

    Wird von Web-Layer (Wingcast/Email) verwendet, um den fertig
    generierten Block anzuzeigen. Kein neuer LLM-Call hier.
    """
    path = Path(config.SYNOPTIC_CACHE_PATH)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("load_synoptic_cache: %s", e)
        return None


# ============================================================================
# DATEN-AGGREGATION (Phase 2)
# ============================================================================

def _msl_from_surface(p_surf_hpa: float, elevation_m: float,
                      temp_2m_c: Optional[float] = None) -> float:
    """Reduziert surface_pressure auf Meereshoehe via hydrostatischer Formel.

    Fallback wenn pressure_msl nicht im Cache ist. Hat geringere Genauigkeit
    als ICON-MSL (~0.5-1.5 hPa Fehler), reicht aber fuer CH-Mittel.

    P_msl = P_surf * exp(g * h / (R * T_K))
    """
    if p_surf_hpa is None or elevation_m is None:
        return None
    t_kelvin = (temp_2m_c if temp_2m_c is not None else 15.0) + 273.15
    if t_kelvin <= 0:
        return None
    factor = math.exp(_GRAVITY_M_PER_S2 * elevation_m
                      / (_GAS_CONSTANT_AIR_J_PER_KG_K * t_kelvin))
    return p_surf_hpa * factor


def _wind_vector_mean(samples: list[tuple[float, float]]) -> Optional[dict]:
    """Vektor-Mittel fuer (speed_kmh, direction_deg)-Tupel.

    Direction muss vektoriell gemittelt werden, sonst gibt's Unsinn bei
    Werten um 0/360 herum.
    """
    if not samples:
        return None
    sum_u = 0.0
    sum_v = 0.0
    for speed, dir_deg in samples:
        if speed is None or dir_deg is None:
            continue
        rad = math.radians(dir_deg)
        sum_u += speed * math.sin(rad)
        sum_v += speed * math.cos(rad)
    n = sum(1 for s, d in samples if s is not None and d is not None)
    if n == 0:
        return None
    u_mean = sum_u / n
    v_mean = sum_v / n
    speed_mean = math.sqrt(u_mean ** 2 + v_mean ** 2)
    dir_mean = math.degrees(math.atan2(u_mean, v_mean)) % 360
    return {"speed_kmh": round(speed_mean, 1), "dir_deg": round(dir_mean, 0)}


def aggregate_ch_daily_snapshot(weather_cache: dict,
                                forecast_dates: list[str]) -> Optional[list[dict]]:
    """Baut CH-Mittel-Schnappschuesse fuer jeden Forecast-Tag (12 UTC).

    Mittelt ueber alle Spots im Cache (487 Spots = breite CH-Abdeckung).
    Felder pro Tag: pressure_msl, temperature_850hPa, wind_speed_700hPa,
    wind_direction_700hPa (Vektor-Mittel).

    Returns:
        Liste von Snapshot-Dicts pro Tag, oder None wenn keine Daten.
    """
    if not forecast_dates:
        return None
    snapshots = []
    msl_source = None  # "pressure_msl" (preferred) oder "derived_from_surface"

    for date_str in forecast_dates:
        time_key = f"{date_str}T12:00"
        msl_vals = []
        t850_vals = []
        gh850_vals = []
        wind700 = []  # (speed, dir) Tupel

        for spot_name, spot in weather_cache.items():
            if spot_name.startswith("_"):
                continue
            hd = spot.get("hourly_data", {}) or {}
            pld = spot.get("pressure_level_data", {}) or {}
            h_rec = hd.get(time_key)
            p_rec = pld.get(time_key)

            # MSL: bevorzugt direkt aus API; sonst aus surface_pressure herleiten
            if h_rec is not None:
                msl = h_rec.get("pressure_msl")
                if msl is not None:
                    msl_vals.append(msl)
                    if msl_source is None:
                        msl_source = "pressure_msl"
                else:
                    p_surf = h_rec.get("surface_pressure")
                    elev = spot.get("elevation_m")
                    t2m = h_rec.get("temperature_2m")
                    msl_derived = _msl_from_surface(p_surf, elev, t2m)
                    if msl_derived is not None:
                        msl_vals.append(msl_derived)
                        if msl_source is None:
                            msl_source = "derived_from_surface"

            if p_rec is not None:
                t850 = p_rec.get("temperature_850hPa")
                if t850 is not None:
                    t850_vals.append(t850)
                gh850 = p_rec.get("geopotential_height_850hPa")
                if gh850 is not None:
                    gh850_vals.append(gh850)
                ws = p_rec.get("wind_speed_700hPa")
                wd = p_rec.get("wind_direction_700hPa")
                if ws is not None and wd is not None:
                    wind700.append((ws, wd))

        snap = {
            "date": date_str,
            "n_spots": len(msl_vals),
            "msl_hpa": round(statistics.mean(msl_vals), 1) if msl_vals else None,
            "t850_c": round(statistics.mean(t850_vals), 1) if t850_vals else None,
            "gh850_m": round(statistics.mean(gh850_vals), 0) if gh850_vals else None,
            "wind_700": _wind_vector_mean(wind700),
            "msl_source": msl_source,
        }
        snapshots.append(snap)

    # Wenn alle MSL-Werte fehlen, koennen wir keine Druck-Einschaetzung machen
    if not any(s.get("msl_hpa") is not None for s in snapshots):
        logger.warning("aggregate_ch_daily_snapshot: keine MSL-Werte gefunden")
        return None
    return snapshots


def fetch_europe_pressure_grid(forecast_dates: list[str]) -> Optional[list[dict]]:
    """Holt pressure_msl fuer die 15 Europa-Punkte via separaten Open-Meteo-Call.

    Returns:
        Liste mit Eintraegen pro Punkt:
        [{lat, lon, label, msl_by_day: {date: value}}]
        Oder None bei API-Fehler.
    """
    if not forecast_dates:
        return None

    lats = [p["lat"] for p in config.EUROPE_PRESSURE_GRID]
    lons = [p["lon"] for p in config.EUROPE_PRESSURE_GRID]

    params = {
        "latitude": ",".join(str(x) for x in lats),
        "longitude": ",".join(str(x) for x in lons),
        "hourly": "pressure_msl",
        "models": "ecmwf_ifs025",  # globales Modell, deckt ganz Europa ab
        "start_date": forecast_dates[0],
        "end_date": forecast_dates[-1],
        "timezone": "UTC",
    }
    params = config.with_api_key(params)

    try:
        r = requests.get(config.API_URL, params=params, timeout=config.API_TIMEOUT)
        r.raise_for_status()
        payload = r.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("fetch_europe_pressure_grid: API-Fehler: %s", e)
        return None

    # Open-Meteo gibt bei Multi-Location eine Liste zurueck
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list) or len(payload) != len(config.EUROPE_PRESSURE_GRID):
        logger.warning("fetch_europe_pressure_grid: unerwartetes Payload-Format")
        return None

    out = []
    for grid_def, loc in zip(config.EUROPE_PRESSURE_GRID, payload):
        hourly = loc.get("hourly", {}) or {}
        times = hourly.get("time", []) or []
        msls = hourly.get("pressure_msl", []) or []
        msl_by_day = {}
        for d in forecast_dates:
            target = f"{d}T12:00"
            try:
                idx = times.index(target)
                val = msls[idx] if idx < len(msls) else None
                if val is not None:
                    msl_by_day[d] = round(float(val), 1)
            except ValueError:
                continue
        if msl_by_day:
            out.append({
                "lat": grid_def["lat"],
                "lon": grid_def["lon"],
                "label": grid_def["label"],
                "msl_by_day": msl_by_day,
            })
    if not out:
        logger.warning("fetch_europe_pressure_grid: kein Punkt hat gueltige Daten")
        return None
    return out


# ============================================================================
# BASIS-DETEKTOREN (Phase 2)
# ============================================================================

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Grosskreisdistanz in km."""
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def find_pressure_centers(grid_values: list[dict], date_str: str) -> list[dict]:
    """Detektiert Hoch/Tief-Zentren aus dem Druckraster fuer einen Tag.

    Algorithmus:
      1. Fuer jeden Punkt: vergleiche mit 4 naechsten Nachbarn (Haversine)
      2. Lokales Minimum (alle Nachbarn hoeher) -> Tief-Kandidat
      3. Lokales Maximum (alle Nachbarn tiefer) -> Hoch-Kandidat
      4. Filter: Gradient zum Nachbar-Mittel muss >= MIN_GRADIENT_HPA sein
      5. Schwaechere Verteilungen werden verworfen (keine Erfindung)

    Returns:
        Liste detektierter Zentren mit Provenance.
    """
    centers = []
    points_with_value = [
        p for p in grid_values if p.get("msl_by_day", {}).get(date_str) is not None
    ]
    if len(points_with_value) < 5:
        return centers

    for p in points_with_value:
        msl_p = p["msl_by_day"][date_str]
        # Distanzen zu allen anderen Punkten
        others = [
            (q, _haversine_km(p["lat"], p["lon"], q["lat"], q["lon"]))
            for q in points_with_value if q is not p
        ]
        others.sort(key=lambda x: x[1])
        neighbors = [q for q, _ in others[:4]]
        nb_msls = [q["msl_by_day"][date_str] for q in neighbors]
        if not nb_msls:
            continue
        nb_mean = statistics.mean(nb_msls)

        # Lokales Minimum?
        if msl_p < min(nb_msls):
            gradient = nb_mean - msl_p
            if gradient >= config.SYNOPTIC_PRESSURE_CENTER_MIN_GRADIENT_HPA:
                centers.append({
                    "type": "Tief",
                    "region_label": p["label"],
                    "lat": p["lat"],
                    "lon": p["lon"],
                    "msl_hpa": msl_p,
                    "gradient_hpa": round(gradient, 1),
                    "decided_by": "find_pressure_centers",
                    "thresholds": {
                        "min_gradient_hpa": config.SYNOPTIC_PRESSURE_CENTER_MIN_GRADIENT_HPA,
                    },
                })
        # Lokales Maximum?
        elif msl_p > max(nb_msls):
            gradient = msl_p - nb_mean
            if gradient >= config.SYNOPTIC_PRESSURE_CENTER_MIN_GRADIENT_HPA:
                centers.append({
                    "type": "Hoch",
                    "region_label": p["label"],
                    "lat": p["lat"],
                    "lon": p["lon"],
                    "msl_hpa": msl_p,
                    "gradient_hpa": round(gradient, 1),
                    "decided_by": "find_pressure_centers",
                    "thresholds": {
                        "min_gradient_hpa": config.SYNOPTIC_PRESSURE_CENTER_MIN_GRADIENT_HPA,
                    },
                })
    return centers


def decide_pressure_influence(snapshots: list[dict]) -> dict:
    """Klassifiziert CH-Druckeinfluss ueber alle Forecast-Tage.

    Ableitung:
      - Pro Tag: Hochdruck (>= HOCH), Tiefdruck (<= TIEF), neutral (zwischen)
      - Trend ueber die Woche: stabil / aufbauend / abschwaechend / wechselnd
      - Aggregiertes Label: dominantes Tagesregime, oder "Uebergangslage"
    """
    msls = [s.get("msl_hpa") for s in snapshots if s.get("msl_hpa") is not None]
    if not msls:
        return {
            "value": "unbekannt",
            "decided_by": "decide_pressure_influence",
            "inputs": {"msl_by_day": []},
            "thresholds": {},
            "per_day": [],
        }

    per_day = []
    for s in snapshots:
        v = s.get("msl_hpa")
        if v is None:
            per_day.append({"date": s["date"], "regime": "unbekannt", "msl_hpa": None})
            continue
        if v >= config.SYNOPTIC_HOCH_HPA:
            regime = "Hochdruck"
        elif v <= config.SYNOPTIC_STRONG_TIEF_HPA:
            regime = "starker Tiefdruck"
        elif v <= config.SYNOPTIC_TIEF_HPA:
            regime = "Tiefdruck"
        else:
            regime = "neutral"
        per_day.append({"date": s["date"], "regime": regime, "msl_hpa": v})

    # Trend: linearer Fit (Steigung in hPa/Tag)
    n = len(msls)
    if n >= 2:
        xs = list(range(n))
        x_mean = sum(xs) / n
        y_mean = sum(msls) / n
        num = sum((xs[i] - x_mean) * (msls[i] - y_mean) for i in range(n))
        den = sum((xs[i] - x_mean) ** 2 for i in range(n)) or 1.0
        slope = num / den
        if abs(slope) < config.SYNOPTIC_PRESSURE_TREND_THRESHOLD_HPA:
            trend = "stabil"
        elif slope > 0:
            trend = "aufbauend"
        else:
            trend = "abschwaechend"
    else:
        slope = 0.0
        trend = "stabil"

    # Aggregiertes Hauptlabel: dominantes Regime
    regimes = [d["regime"] for d in per_day if d["regime"] != "unbekannt"]
    if not regimes:
        main = "unbekannt"
    else:
        counts = {r: regimes.count(r) for r in set(regimes)}
        main = max(counts.items(), key=lambda kv: kv[1])[0]
        # Wenn Regime-Wechsel innerhalb der Woche: Uebergangslage
        if len(set(regimes)) > 1 and max(counts.values()) < len(regimes):
            main = "Uebergangslage"

    return {
        "value": main,
        "trend": trend,
        "slope_hpa_per_day": round(slope, 2),
        "per_day": per_day,
        "decided_by": "decide_pressure_influence",
        "inputs": {"msl_by_day": msls},
        "thresholds": {
            "hoch_hpa": config.SYNOPTIC_HOCH_HPA,
            "tief_hpa": config.SYNOPTIC_TIEF_HPA,
            "strong_tief_hpa": config.SYNOPTIC_STRONG_TIEF_HPA,
            "trend_hpa_per_day": config.SYNOPTIC_PRESSURE_TREND_THRESHOLD_HPA,
        },
    }


def decide_flow_overhead(snapshots: list[dict]) -> dict:
    """Klassifiziert uebergeordnete Stroemung aus 700hPa-Wind ueber die Woche.

    Liefert: dominante Richtung, Staerke-Klasse, und Wendepunkt-Detection.
    """
    wind_by_day = []
    for s in snapshots:
        w = s.get("wind_700")
        if w is None:
            wind_by_day.append(None)
            continue
        sector = _wind_direction_to_sector(w["dir_deg"])
        strength = _flow_strength(w["speed_kmh"])
        wind_by_day.append({
            "date": s["date"],
            "speed_kmh": w["speed_kmh"],
            "dir_deg": w["dir_deg"],
            "sector": sector,
            "strength": strength,
        })

    valid = [w for w in wind_by_day if w is not None]
    if not valid:
        return {
            "value": "unbekannt",
            "decided_by": "decide_flow_overhead",
            "inputs": {},
            "per_day": [],
        }

    # Dominante Richtung: Vektor-Mittel aller Tage
    samples = [(w["speed_kmh"], w["dir_deg"]) for w in valid]
    mean = _wind_vector_mean(samples)
    dominant_sector = _wind_direction_to_sector(mean["dir_deg"]) if mean else "Nord"
    dominant_strength = _flow_strength(mean["speed_kmh"]) if mean else "schwach"

    # Wendepunkt: signifikante Drehung (> 90 Grad) zwischen zwei aufeinanderfolgenden Tagen
    rotation = None
    for i in range(len(wind_by_day) - 1):
        a = wind_by_day[i]
        b = wind_by_day[i + 1]
        if a is None or b is None:
            continue
        # Differenz auf [0, 180] normieren
        diff = abs(b["dir_deg"] - a["dir_deg"])
        diff = min(diff, 360 - diff)
        if diff >= 90 and a["sector"] != b["sector"]:
            rotation = {
                "from_sector": a["sector"],
                "to_sector": b["sector"],
                "from_date": a["date"],
                "to_date": b["date"],
                "diff_deg": round(diff, 0),
            }
            break

    if rotation:
        trend = f"dreht von {rotation['from_sector']} auf {rotation['to_sector']} ab {rotation['to_date']}"
    else:
        # Alle Tage gleicher Sektor?
        sectors = {w["sector"] for w in valid}
        trend = "stabil" if len(sectors) <= 1 else "leicht drehend"

    return {
        "value": dominant_sector,
        "strength": dominant_strength,
        "trend": trend,
        "rotation": rotation,
        "per_day": wind_by_day,
        "decided_by": "decide_flow_overhead",
        "inputs": {
            "wind_700_by_day": [
                {"speed": w["speed_kmh"], "dir": w["dir_deg"]} if w else None
                for w in wind_by_day
            ],
        },
        "thresholds": {
            "schwach_kmh": config.SYNOPTIC_FLOW_SCHWACH_KMH,
            "maessig_kmh": config.SYNOPTIC_FLOW_MAESSIG_KMH,
            "kraeftig_kmh": config.SYNOPTIC_FLOW_KRAEFTIG_KMH,
            "rotation_deg": 90,
        },
    }


def decide_t850_trend(snapshots: list[dict]) -> dict:
    """Klassifiziert T850-Verlauf ueber die Woche.

    Erkennt signifikante Luftmassen-Wechsel (>= 4 K binnen 24-48h).
    """
    t850 = [s.get("t850_c") for s in snapshots]
    valid_pairs = [(i, t) for i, t in enumerate(t850) if t is not None]
    if len(valid_pairs) < 2:
        return {
            "value": "unbekannt",
            "decided_by": "decide_t850_trend",
            "inputs": {"t850_by_day": t850},
            "per_day": t850,
        }

    # Suche signifikante Aenderung zwischen aufeinanderfolgenden Tagen
    change = None
    for i in range(len(valid_pairs) - 1):
        idx_a, t_a = valid_pairs[i]
        idx_b, t_b = valid_pairs[i + 1]
        delta = t_b - t_a
        if abs(delta) >= config.SYNOPTIC_T850_TREND_THRESHOLD_K:
            direction = "kuehler" if delta < 0 else "waermer"
            change = {
                "from_idx": idx_a,
                "to_idx": idx_b,
                "from_date": snapshots[idx_a]["date"],
                "to_date": snapshots[idx_b]["date"],
                "delta_k": round(delta, 1),
                "direction": direction,
            }
            break

    if change is None:
        # Gesamttrend ueber die Woche
        total = valid_pairs[-1][1] - valid_pairs[0][1]
        if abs(total) >= config.SYNOPTIC_T850_TREND_THRESHOLD_K:
            value = f"insgesamt {'waermer' if total > 0 else 'kuehler'}"
        else:
            value = "stabil"
        return {
            "value": value,
            "delta_total_k": round(total, 1),
            "change": None,
            "per_day": t850,
            "decided_by": "decide_t850_trend",
            "inputs": {"t850_by_day": t850},
            "thresholds": {"threshold_k": config.SYNOPTIC_T850_TREND_THRESHOLD_K},
        }

    return {
        "value": f"{change['direction']} ab {change['to_date']}",
        "change": change,
        "per_day": t850,
        "decided_by": "decide_t850_trend",
        "inputs": {"t850_by_day": t850},
        "thresholds": {"threshold_k": config.SYNOPTIC_T850_TREND_THRESHOLD_K},
    }


# ============================================================================
# HOEHERE KLASSIFIKATOREN (Phase 3)
# ============================================================================

# Schwellen fuer Druckraster-Aggregation pro Box (Nord-Ost-Pol / Sued-Pol)
_BISE_NE_POLE_LABELS = ("Suedskandinavien", "Mitteleuropa", "Osteuropa")
_BISE_S_POLE_LABELS = ("Westliches Mittelmeer", "Adria", "Norditalien")


def _msl_for_labels(grid: list[dict], date_str: str, labels: tuple) -> Optional[float]:
    """Mittel der MSL-Werte fuer eine Liste von Region-Labels (Skip Missing)."""
    vals = []
    for p in grid:
        if p.get("label") in labels:
            v = p.get("msl_by_day", {}).get(date_str)
            if v is not None:
                vals.append(v)
    if not vals:
        return None
    return statistics.mean(vals)


def decide_bise(grid: list[dict], snapshots: list[dict],
                forecast_dates: list[str]) -> dict:
    """Erkennt Bisenlage deterministisch.

    Bedingungen pro Tag (alle muessen erfuellt sein):
      1. ΔP NE-Europa - Mittelmeer >= SYNOPTIC_BISE_DELTA_P_THRESHOLD_HPA
      2. 700hPa-Wind ueber CH aus NE-Sektor (30-90 Grad)
      3. 700hPa-Speed >= SYNOPTIC_BISE_WIND_MIN_KMH

    Liefert pro Tag aktiv/inaktiv + Wochen-Aggregat (anhaltend / kurz / nicht).
    """
    per_day = []
    for i, date in enumerate(forecast_dates):
        snap = snapshots[i] if i < len(snapshots) else None
        ne_msl = _msl_for_labels(grid, date, _BISE_NE_POLE_LABELS)
        s_msl = _msl_for_labels(grid, date, _BISE_S_POLE_LABELS)
        delta_p = None
        if ne_msl is not None and s_msl is not None:
            delta_p = round(ne_msl - s_msl, 1)

        # 700hPa-Wind aus NE-Sektor?
        wind_ok = False
        wind_dir = None
        wind_speed = None
        if snap and snap.get("wind_700"):
            w = snap["wind_700"]
            wind_dir = w["dir_deg"]
            wind_speed = w["speed_kmh"]
            in_ne_sector = (config.SYNOPTIC_BISE_WIND_DIR_MIN
                            <= wind_dir
                            <= config.SYNOPTIC_BISE_WIND_DIR_MAX)
            strong_enough = wind_speed >= config.SYNOPTIC_BISE_WIND_MIN_KMH
            wind_ok = in_ne_sector and strong_enough

        delta_p_ok = (delta_p is not None
                      and delta_p >= config.SYNOPTIC_BISE_DELTA_P_THRESHOLD_HPA)

        active = bool(delta_p_ok and wind_ok)
        # Stuerke aus ΔP
        if delta_p is None:
            strength = None
        elif delta_p >= 10:
            strength = "stark"
        elif delta_p >= 6:
            strength = "mittel"
        else:
            strength = "schwach"

        per_day.append({
            "date": date,
            "active": active,
            "strength": strength if active else None,
            "delta_p_hpa": delta_p,
            "wind_700_dir_deg": wind_dir,
            "wind_700_speed_kmh": wind_speed,
        })

    days_active = [d["date"] for d in per_day if d["active"]]
    summary = "nicht aktiv"
    if len(days_active) >= 3:
        summary = "anhaltend"
    elif days_active:
        summary = "kurz"

    return {
        "value": summary,
        "active_any_day": bool(days_active),
        "days_active": days_active,
        "per_day": per_day,
        "decided_by": "decide_bise",
        "inputs": {
            "ne_pole_labels": list(_BISE_NE_POLE_LABELS),
            "s_pole_labels": list(_BISE_S_POLE_LABELS),
        },
        "thresholds": {
            "delta_p_hpa": config.SYNOPTIC_BISE_DELTA_P_THRESHOLD_HPA,
            "wind_dir_sector": [config.SYNOPTIC_BISE_WIND_DIR_MIN,
                                config.SYNOPTIC_BISE_WIND_DIR_MAX],
            "wind_min_kmh": config.SYNOPTIC_BISE_WIND_MIN_KMH,
        },
    }


def decide_vb_lage(grid: list[dict], forecast_dates: list[str]) -> dict:
    """Erkennt Vb-/Genua-Tief-Pattern.

    Tief-Zentrum in der Norditalien-/Adria-Box mit MSL <= SYNOPTIC_VB_MAX_MSL_HPA.
    """
    per_day = []
    for date in forecast_dates:
        # Punkte aus dem Grid die in der Box liegen
        in_box = [
            p for p in grid
            if (config.SYNOPTIC_VB_BOX_LAT_MIN <= p["lat"] <= config.SYNOPTIC_VB_BOX_LAT_MAX
                and config.SYNOPTIC_VB_BOX_LON_MIN <= p["lon"] <= config.SYNOPTIC_VB_BOX_LON_MAX)
        ]
        msls_in_box = [
            (p, p.get("msl_by_day", {}).get(date))
            for p in in_box
        ]
        msls_in_box = [(p, v) for p, v in msls_in_box if v is not None]
        if not msls_in_box:
            per_day.append({"date": date, "active": False, "msl_hpa": None,
                            "region_label": None})
            continue
        # Niedrigster Druck in der Box
        msls_in_box.sort(key=lambda pv: pv[1])
        lowest_point, lowest_msl = msls_in_box[0]
        is_low = lowest_msl <= config.SYNOPTIC_VB_MAX_MSL_HPA
        per_day.append({
            "date": date,
            "active": is_low,
            "msl_hpa": lowest_msl,
            "region_label": lowest_point["label"] if is_low else None,
        })

    days_active = [d["date"] for d in per_day if d["active"]]
    summary = "nicht aktiv"
    if len(days_active) >= 2:
        summary = "ausgepraegt"
    elif days_active:
        summary = "kurz"

    return {
        "value": summary,
        "active_any_day": bool(days_active),
        "days_active": days_active,
        "per_day": per_day,
        "decided_by": "decide_vb_lage",
        "inputs": {
            "box_lat": [config.SYNOPTIC_VB_BOX_LAT_MIN, config.SYNOPTIC_VB_BOX_LAT_MAX],
            "box_lon": [config.SYNOPTIC_VB_BOX_LON_MIN, config.SYNOPTIC_VB_BOX_LON_MAX],
        },
        "thresholds": {"max_msl_hpa": config.SYNOPTIC_VB_MAX_MSL_HPA},
    }


def decide_foehn_summary(forecast_dates: list[str]) -> dict:
    """Aggregiert Foehn-Status pro Tag via foehn_indicators.fetch_foehn_data.

    Pro Tag: Stunden im Flugfenster (FLIGHT_HOURS_START..END) pruefen, aktiv
    ab SYNOPTIC_FOEHN_ACTIVE_MIN_HOURS Stunden caution+ in Sued- oder
    Nord-Richtung. Gleiche Regel wie die Regions-Analyse
    (weather_context._format_foehn_info) — damit gilt: hat eine Region Foehn,
    zeigt ihn auch die Synoptik. evaluate_foehn("Beide") ist je Stunde das
    Maximum aus "Sued" und "Nord", jede Region-Richtung ist also abgedeckt.
    Frueher 10-16 Uhr und >= 2 h (Vorfall 16.09.2026: 1 h Nordfoehn,
    Oberwallis "Foehn maessig", Synoptik "kein Foehn").

    Bei API-Fehler: liefert active=False mit source="fetch_failed", damit
    der Synoptik-Block nicht komplett ausfaellt.
    """
    from foehn_indicators import (
        fetch_foehn_data, evaluate_foehn,
        THRESHOLD_DELTA_P_CAUTION, THRESHOLD_DELTA_P_DANGER,
    )

    min_hours = config.SYNOPTIC_FOEHN_ACTIVE_MIN_HOURS
    h_start, h_end = config.FLIGHT_HOURS_START, config.FLIGHT_HOURS_END

    days_n = max(len(forecast_dates), 2)
    data = fetch_foehn_data(forecast_days=days_n)
    if data is None:
        return {
            "value": "unbekannt",
            "active": False,
            "side": None,
            "days_affected": [],
            "per_day": [],
            "decided_by": "decide_foehn_summary",
            "source": "fetch_failed",
            "inputs": {},
            "thresholds": {
                "delta_p_caution_hpa": THRESHOLD_DELTA_P_CAUTION,
                "delta_p_danger_hpa": THRESHOLD_DELTA_P_DANGER,
                "active_min_hours": min_hours,
            },
        }

    times = data["nord"].get("hourly", {}).get("time", []) or []
    if not times:
        return {
            "value": "unbekannt", "active": False, "side": None,
            "days_affected": [], "per_day": [],
            "decided_by": "decide_foehn_summary", "source": "no_times",
            "inputs": {}, "thresholds": {},
        }

    _level_rank = {"none": 0, "caution": 1, "danger": 2}

    def _peak(a, b):
        return a if _level_rank[a] >= _level_rank[b] else b

    per_day = []
    for date in forecast_dates:
        day_indices = [
            i for i, t in enumerate(times)
            if t.startswith(date) and h_start <= int(t[11:13]) < h_end
        ]
        sued_hours = 0
        nord_hours = 0
        peak_sued = "none"
        peak_nord = "none"
        # Tagesverlauf je Seite: Stunden und Spitze pro Tagesfenster. Ohne das
        # steht in der Warnung nur "6 h Foehn" — der Pilot will aber wissen, ob
        # er morgens noch fliegt und der Foehn erst nachmittags durchgreift.
        win_sued = {w[0]: {"hours": 0, "peak": "none"}
                    for w in config.SYNOPTIC_DAY_WINDOWS}
        win_nord = {w[0]: {"hours": 0, "peak": "none"}
                    for w in config.SYNOPTIC_DAY_WINDOWS}

        def _bucket(hour: int):
            for wname, h_lo, h_hi in config.SYNOPTIC_DAY_WINDOWS:
                if h_lo <= hour < h_hi:
                    return wname
            return None

        dp_sued_max = dp_nord_max = crest_max = None
        gust_nord_max = gust_sued_max = None      # Lee-Boeen: Nordseite (Suedfoehn), Suedseite (Nordfoehn)
        g_nord = (data["nord"].get("hourly") or {}).get("wind_gusts_10m") or []
        g_sued = (data["sued"].get("hourly") or {}).get("wind_gusts_10m") or []
        for i in day_indices:
            hour = int(times[i][11:13])
            wname = _bucket(hour)
            ev_sued = evaluate_foehn(data["nord"], data["sued"], i,
                                     kritischer_foehn="Süd")
            ev_nord = evaluate_foehn(data["nord"], data["sued"], i,
                                     kritischer_foehn="Nord")
            # Anspruch der Synoptik und Antwort der Daten fuer den Abgleich im Briefing
            for val, cur, name in ((ev_sued.get("delta_p_hpa"), dp_sued_max, "s"),
                                   (ev_nord.get("delta_p_hpa"), dp_nord_max, "n")):
                if isinstance(val, (int, float)) and (cur is None or val > cur):
                    if name == "s":
                        dp_sued_max = float(val)
                    else:
                        dp_nord_max = float(val)
            cw = ev_sued.get("crest_wind_kmh") or ev_nord.get("crest_wind_kmh")
            if isinstance(cw, (int, float)) and (crest_max is None or cw > crest_max):
                crest_max = float(cw)
            if i < len(g_nord) and isinstance(g_nord[i], (int, float)):
                gust_nord_max = max(gust_nord_max or 0.0, float(g_nord[i]))
            if i < len(g_sued) and isinstance(g_sued[i], (int, float)):
                gust_sued_max = max(gust_sued_max or 0.0, float(g_sued[i]))
            if ev_sued.get("level", "none") != "none":
                sued_hours += 1
                peak_sued = _peak(peak_sued, ev_sued["level"])
                if wname:
                    win_sued[wname]["hours"] += 1
                    win_sued[wname]["peak"] = _peak(win_sued[wname]["peak"],
                                                    ev_sued["level"])
            if ev_nord.get("level", "none") != "none":
                nord_hours += 1
                peak_nord = _peak(peak_nord, ev_nord["level"])
                if wname:
                    win_nord[wname]["hours"] += 1
                    win_nord[wname]["peak"] = _peak(win_nord[wname]["peak"],
                                                    ev_nord["level"])
        sued_active = sued_hours >= min_hours
        nord_active = nord_hours >= min_hours
        per_day.append({
            "date": date,
            "sued_active": sued_active,
            "nord_active": nord_active,
            "peak_sued": peak_sued,
            "peak_nord": peak_nord,
            "sued_hours": sued_hours,
            "nord_hours": nord_hours,
            "sued_windows": win_sued,
            "nord_windows": win_nord,
            "claim": {"delta_p_sued_max_hpa": (round(dp_sued_max, 1) if dp_sued_max is not None else None),
                      "delta_p_nord_max_hpa": (round(dp_nord_max, 1) if dp_nord_max is not None else None),
                      "crest_wind_max_kmh": (round(crest_max) if crest_max is not None else None)},
            "lee": {"gust_nord_max_kmh": (round(gust_nord_max) if gust_nord_max is not None else None),
                    "gust_sued_max_kmh": (round(gust_sued_max) if gust_sued_max is not None else None)},
        })

    any_sued = any(d["sued_active"] for d in per_day)
    any_nord = any(d["nord_active"] for d in per_day)
    if any_sued and any_nord:
        side = "wechselnd"
    elif any_sued:
        side = "Sued"
    elif any_nord:
        side = "Nord"
    else:
        side = None

    active = side is not None
    if not active:
        value = "nicht aktiv"
    else:
        any_danger = any(_level_rank[d["peak_sued"]] >= 2 or _level_rank[d["peak_nord"]] >= 2
                         for d in per_day)
        value = f"{side}foehn ({'stark' if any_danger else 'maessig'})" \
            if side != "wechselnd" else "wechselnd"

    days_affected = [d["date"] for d in per_day
                     if d["sued_active"] or d["nord_active"]]

    return {
        "value": value,
        "active": active,
        "side": side,
        "days_affected": days_affected,
        "per_day": per_day,
        "decided_by": "decide_foehn_summary",
        "source": "foehn_indicators.fetch_foehn_data + evaluate_foehn",
        "inputs": {"forecast_dates": forecast_dates},
        "thresholds": {
            "delta_p_caution_hpa": THRESHOLD_DELTA_P_CAUTION,
            "delta_p_danger_hpa": THRESHOLD_DELTA_P_DANGER,
            "active_min_hours": min_hours,
            "day_hours_checked": [h_start, h_end - 1],
        },
    }


# Stroemungs-Sektor -> Lage-Begriff in Pilotensprache
_SECTOR_TO_LAGE = {
    "West": "Westlage",
    "Suedwest": "Suedwestlage",
    "Nordwest": "Nordwestlage",
    "Nord": "Nordlage",
    "Nordost": "Nordostlage",
    "Ost": "Ostlage",
    "Suedost": "Suedostlage",
    "Sued": "Suedlage",
}


def decide_lage_label_for_day(ctx: dict, date: str) -> dict:
    """Lage-Label fuer EINEN Tag — gleiche Hierarchie wie decide_lage_label,
    aber aus den per_day-Feldern.

    decide_lage_label beschreibt das ganze Prognosefenster: am 16.09.2026 stand
    "Nordfoehnlage" (Foehn erst am Donnerstag) ueber einem Tag mit "Kein Foehn".
    In der Tages-Sektion des Briefings gilt nur dieser Tag.
    """
    def day(key):
        for d in (ctx.get(key) or {}).get("per_day") or []:
            if isinstance(d, dict) and d.get("date") == date:
                return d
        return {}

    fo = day("foehn")
    nord, sued = bool(fo.get("nord_active")), bool(fo.get("sued_active"))
    if nord and sued:
        return {"value": "Foehnlage (wechselnd)", "trigger": "foehn.both"}
    if sued:
        return {"value": "Suedfoehnlage", "trigger": "foehn.sued_active"}
    if nord:
        return {"value": "Nordfoehnlage", "trigger": "foehn.nord_active"}
    if day("vb_lage").get("active"):
        return {"value": "Genua-Tief", "trigger": "vb_lage.active"}
    if day("bise").get("active"):
        return {"value": "Bisenlage", "trigger": "bise.active"}
    flow = day("flow_overhead")
    sector, strength = flow.get("sector"), flow.get("strength")
    if sector and sector != "unbekannt" and strength and strength != "schwach":
        return {"value": _SECTOR_TO_LAGE.get(sector, f"{sector}lage"),
                "trigger": f"flow.sector={sector},strength={strength}"}
    regime = day("pressure_influence").get("regime")
    if regime == "Hochdruck":
        return {"value": "Hochdrucklage", "trigger": "regime=Hochdruck"}
    if regime in ("Tiefdruck", "starker Tiefdruck"):
        return {"value": "Tiefdrucklage", "trigger": f"regime={regime}"}
    return {"value": "unbestimmt", "trigger": "no_trigger_fired"}


def decide_lage_label(pressure_influence: dict, flow_overhead: dict,
                      bise: dict, foehn: dict, vb_lage: dict) -> dict:
    """Kombiniert alle vorherigen Decisions zu einem Hauptlabel in Pilotensprache.

    Hierarchie (erste passende Bedingung gewinnt):
      1. Foehn aktiv (Sued/Nord/wechselnd)
      2. Vb-/Genua-Tief aktiv
      3. Bisenlage aktiv
      4. West-/NW-/SW-Lage aus dominanter Stroemung
      5. Hochdruck (wenn dominant)
      6. Tiefdruck (wenn dominant)
      7. Uebergangslage
    """
    # 1. Foehn
    if foehn and foehn.get("active"):
        side = foehn.get("side")
        if side == "Sued":
            return {
                "value": "Suedfoehnlage",
                "decided_by": "decide_lage_label",
                "trigger": "foehn.side=Sued",
            }
        elif side == "Nord":
            return {
                "value": "Nordfoehnlage",
                "decided_by": "decide_lage_label",
                "trigger": "foehn.side=Nord",
            }
        else:
            return {
                "value": "Foehnlage (wechselnd)",
                "decided_by": "decide_lage_label",
                "trigger": "foehn.side=wechselnd",
            }

    # 2. Vb-Lage. Im Label steht bewusst NUR "Genua-Tief": "Vb" ist die
    # Zugbahn-Nummer nach van Bebber (Bahn V, Variante b) und als Kuerzel
    # in der Ueberschrift des Casts unverstaendlich. Der Feldname bleibt
    # vb_lage — intern ist das der etablierte Begriff.
    if vb_lage and vb_lage.get("active_any_day"):
        return {
            "value": "Genua-Tief",
            "decided_by": "decide_lage_label",
            "trigger": "vb_lage.active",
        }

    # 3. Bise
    if bise and bise.get("active_any_day"):
        return {
            "value": "Bisenlage",
            "decided_by": "decide_lage_label",
            "trigger": "bise.active",
        }

    # 4. Stroemungs-Lage aus dominanter Richtung (nur wenn nicht schwach)
    flow_sector = flow_overhead.get("value") if flow_overhead else None
    flow_strength = flow_overhead.get("strength") if flow_overhead else None
    if flow_sector and flow_sector != "unbekannt" and flow_strength != "schwach":
        lage = _SECTOR_TO_LAGE.get(flow_sector, f"{flow_sector}lage")
        return {
            "value": lage,
            "decided_by": "decide_lage_label",
            "trigger": f"flow.value={flow_sector},strength={flow_strength}",
        }

    # 5+6. Druckeinfluss-Hauptlabel
    pi_val = pressure_influence.get("value") if pressure_influence else None
    if pi_val == "Hochdruck":
        return {"value": "Hochdrucklage", "decided_by": "decide_lage_label",
                "trigger": "pressure_influence=Hochdruck"}
    if pi_val in ("Tiefdruck", "starker Tiefdruck"):
        return {"value": "Tiefdrucklage", "decided_by": "decide_lage_label",
                "trigger": f"pressure_influence={pi_val}"}
    if pi_val == "Uebergangslage":
        return {"value": "Uebergangslage", "decided_by": "decide_lage_label",
                "trigger": "pressure_influence=Uebergangslage"}

    return {"value": "unbestimmt", "decided_by": "decide_lage_label",
            "trigger": "no_trigger_fired"}


# --- Niederschlag Nord vs. Sued der Alpen --------------------------------

def _classify_nord_sued(lat: float, lon: float) -> str:
    """Klassifiziert einen Spot nach Alpennord/Alpensued.

    Vereinfachte Geometrie:
      - Tessin (lat < 46.45, lon > 8.5): alpensued
      - Wallis Haupttal (lat < 46.35, 6.5 < lon < 8.5): alpensued
      - alles andere: alpennord
    """
    if lat is None or lon is None:
        return "unknown"
    if lat < 46.45 and lon > 8.5:
        return "alpensued"
    if lat < 46.35 and 6.5 < lon < 8.5:
        return "alpensued"
    return "alpennord"


def classify_precip_pattern(coverage: float | None, peak_mm: float | None) -> str:
    """Klassifiziert eine Stunde Niederschlag in 4 Klassen.

    Verwendet die gleichen Schwellen wie der Synoptik-Layer (FLAECHIG/KONVEKTIV),
    damit beide Konsumenten (Region-Tag + globale Wetterlage) konsistent bleiben.

    Args:
        coverage: Anteil RPs mit Regen > NOISE_MM (0.0-1.0), None erlaubt
        peak_mm: Maximum mm/h ueber alle RPs

    Returns:
        "widespread" — coverage >= SYNOPTIC_PRECIP_COVERAGE_FLAECHIG (0.7), flaechiger Regen
        "scattered"  — coverage zwischen KONVEKTIV (0.4) und FLAECHIG (0.7), verstreute Zellen
        "isolated"   — coverage < KONVEKTIV (0.4), aber peak >= SIGNIFICANT_MM (0.2): Einzelzelle
        "dry"        — peak < NOISE_MM (0.05) oder coverage 0

    Beispiele:
        16 RPs, 12 nass, peak 1.8mm/h  → coverage=0.75 → "widespread"
        16 RPs,  5 nass, peak 0.8mm/h  → coverage=0.31 → "isolated" (peak >= 0.2)
        16 RPs,  8 nass, peak 0.5mm/h  → coverage=0.50 → "scattered"
        16 RPs,  0 nass, peak 0.0mm/h  → coverage=0.00 → "dry"
    """
    if peak_mm is None or peak_mm < config.PRECIP_NOISE_MM:
        return "dry"
    cov = coverage if coverage is not None else 0.0
    if cov >= config.SYNOPTIC_PRECIP_COVERAGE_FLAECHIG:
        return "widespread"
    if cov >= config.SYNOPTIC_PRECIP_COVERAGE_KONVEKTIV:
        return "scattered"
    if peak_mm >= config.PRECIP_SIGNIFICANT_MM:
        return "isolated"
    return "dry"


def _aggregate_precip_side(spots_day: list[dict]) -> dict:
    """Aggregiert Niederschlags-Rohwerte ueber Spots einer Seite und eines Tages.

    Pure-LLM-Variante (Mai 2026): keine deterministische Charakter-Klassifikation
    mehr — der LLM bekommt die Rohzahlen und bewertet selbst in Pilotensprache.
    Frueher gab es eine if/elif-Kaskade fuer "trocken/Schauer/Gewitter/flaechig",
    die Edge-Cases (z.B. Hitzegewitter mit wet_share=4% und cape=2300) faelschlich
    als "trocken" klassifizierte — der LLM mit Kontext schneidet besser ab.

    Rueckgabe-Felder:
      - n_spots: Anzahl Spots auf dieser Seite
      - peak_mm: max. stuendliche Niederschlagsmenge ueber alle Spots
      - wet_share: Anteil Spots mit total_mm >= DRY_MM (0..1)
      - max_cape: max. CAPE-Wert (J/kg) ueber alle Spots, Indikator fuer Konvektion
      - max_coverage: max. precipitation_coverage (0..1) — DWD-Modell-Confidence
        fuer flaechigen vs. konvektiven NS, None wenn nicht verfuegbar
    """
    if not spots_day:
        return {"n_spots": 0, "peak_mm": 0.0, "wet_share": 0.0,
                "max_cape": 0, "max_wc": 0, "gewitter_share": 0.0,
                "max_coverage": None}
    peaks = [s["peak_mm"] for s in spots_day]
    totals = [s["total_mm"] for s in spots_day]
    capes = [s["max_cape"] for s in spots_day]
    wcs = [s.get("max_wc", 0) for s in spots_day]
    coverages = [s["max_coverage"] for s in spots_day if s["max_coverage"] is not None]

    peak_max = max(peaks)
    nass_anteil = sum(1 for t in totals if t >= config.SYNOPTIC_PRECIP_DRY_MM) / len(totals)
    cape_max = max(capes)
    wc_max = max(wcs)
    # Gewitter-Anteil = Spots mit weather_code 95/96/99 (Modell-Gewitter).
    # Das ist das massgebliche Gewitter-Signal — NICHT max_cape.
    ts_anteil = sum(1 for s in spots_day if s.get("has_ts")) / len(spots_day)
    coverage_max = max(coverages) if coverages else None

    return {
        "n_spots": len(spots_day),
        "peak_mm": round(peak_max, 1),
        "wet_share": round(nass_anteil, 2),
        "max_cape": round(cape_max, 0) if cape_max else 0,
        "max_wc": wc_max,
        "gewitter_share": round(ts_anteil, 2),
        "max_coverage": round(coverage_max, 2) if coverage_max is not None else None,
    }


def decide_precip_pattern_nord_sued(weather_cache: dict,
                                    forecast_dates: list[str]) -> dict:
    """Aggregiert Niederschlag pro Tag separat fuer Alpennord und Alpensued.

    Pro Spot pro Tag: max precipitation, total mm, max CAPE, max weather_code,
    max coverage. Aggregation pro Seite zu einer Charakter-Klasse.
    """
    per_day = []
    n_nord_spots = 0
    n_sued_spots = 0

    # Spot-Klassifikation einmalig
    spot_class = {}
    for spot_name, spot in weather_cache.items():
        if spot_name.startswith("_"):
            continue
        lat = spot.get("latitude")
        lon = spot.get("longitude")
        spot_class[spot_name] = _classify_nord_sued(lat, lon)

    n_nord_spots = sum(1 for c in spot_class.values() if c == "alpennord")
    n_sued_spots = sum(1 for c in spot_class.values() if c == "alpensued")

    for date in forecast_dates:
        nord_day = []
        sued_day = []
        for spot_name, side in spot_class.items():
            spot = weather_cache[spot_name]
            hd = spot.get("hourly_data", {}) or {}
            # Stunden 6-20 lokal (Tagflugfenster mit Vor-/Nachlauf)
            day_recs = [
                rec for t, rec in hd.items()
                if t.startswith(date) and 6 <= int(t[11:13]) <= 20
            ]
            if not day_recs:
                continue
            peak = max((r.get("precipitation") or 0) for r in day_recs)
            total = sum((r.get("precipitation") or 0) for r in day_recs)
            max_cape = max((r.get("cape") or 0) for r in day_recs)
            max_wc = max((r.get("weather_code") or 0) for r in day_recs)
            # Gewitter-Signal = WMO weather_code 95/96/99 (Modell-Urteil).
            # CAPE ist NUR Konvektions-/Instabilitaets-Indikator, kein Gewitter.
            has_ts = any(int(r.get("weather_code") or 0) in (95, 96, 99)
                         for r in day_recs)
            covs = [r.get("precipitation_coverage") for r in day_recs
                    if r.get("precipitation_coverage") is not None]
            max_cov = max(covs) if covs else None
            entry = {
                "peak_mm": peak,
                "total_mm": total,
                "max_cape": max_cape,
                "max_wc": max_wc,
                "has_ts": has_ts,
                "max_coverage": max_cov,
            }
            if side == "alpennord":
                nord_day.append(entry)
            elif side == "alpensued":
                sued_day.append(entry)

        per_day.append({
            "date": date,
            "alpennord": _aggregate_precip_side(nord_day),
            "alpensued": _aggregate_precip_side(sued_day),
        })

    return {
        "per_day": per_day,
        "n_nord_spots": n_nord_spots,
        "n_sued_spots": n_sued_spots,
        "decided_by": "decide_precip_pattern_nord_sued",
        "dry_mm": config.SYNOPTIC_PRECIP_DRY_MM,  # Threshold fuer wet_share-Zaehlung
    }


# Drucklevels, aus denen das Flugband interpolationsfrei bedient wird —
# identisch zur fetch_weather-Levelliste (600 hPa deckt ~4200 m ab).
_WIND_PL_LEVELS = (1000, 975, 950, 925, 900, 875, 850, 825, 800, 775, 750, 700, 600)


def _spot_day_wind(spot: dict, date: str) -> Optional[dict]:
    """Max. Flugband-Hoehenwind + Boden-Boeen eines Spots am Tag (Kernstunden).

    Flugband = Spot-Hoehe + [SYNOPTIC_WIND_BAND_LOWER_M, SYNOPTIC_WIND_BAND_UPPER_M].
    Vereinfachung gegenueber der Spot-Analyse (_check_aloft_in_band nutzt das
    Thermik-Top-Band mit Interpolation): hier zaehlen die PL-Knoten, deren
    geopotential_height im Band liegt — fuers CH-weite Anteils-Aggregat genug.

    Returns {"aloft_max": kmh, "gust_max": kmh} oder None ohne Daten.
    """
    elev = spot.get("elevation_m")
    if elev is None:
        return None
    band_lo = elev + config.SYNOPTIC_WIND_BAND_LOWER_M
    band_hi = elev + config.SYNOPTIC_WIND_BAND_UPPER_M
    h_lo, h_hi = config.SYNOPTIC_WIND_HOURS

    pld = spot.get("pressure_level_data") or {}
    hd = spot.get("hourly_data") or {}

    aloft_max = None
    gust_max = None
    for t, rec in pld.items():
        if not t.startswith(date):
            continue
        try:
            hour = int(t[11:13])
        except (ValueError, IndexError):
            continue
        if not (h_lo <= hour <= h_hi):
            continue
        for lvl in _WIND_PL_LEVELS:
            gh = rec.get(f"geopotential_height_{lvl}hPa")
            ws = rec.get(f"wind_speed_{lvl}hPa")
            if gh is None or ws is None:
                continue
            if band_lo <= gh <= band_hi:
                if aloft_max is None or ws > aloft_max:
                    aloft_max = ws
    for t, rec in hd.items():
        if not t.startswith(date):
            continue
        try:
            hour = int(t[11:13])
        except (ValueError, IndexError):
            continue
        if not (h_lo <= hour <= h_hi):
            continue
        g = rec.get("wind_gusts_10m")
        if g is not None and (gust_max is None or g > gust_max):
            gust_max = g

    if aloft_max is None and gust_max is None:
        return None
    return {"aloft_max": aloft_max, "gust_max": gust_max}


def _aggregate_wind_side(entries: list) -> dict:
    """Aggregiert Spot-Windwerte einer Alpenseite zu Anteils-Kennzahlen.

    crit  = Hoehenwind > WIND_DANGER_KMH ODER Boeen > GUST_DANGER_KMH
            (fuer die meisten Piloten kein nutzbarer Tag)
    warn  = Hoehenwind > WIND_WARN_KMH ODER Boeen > GUST_WARN_KMH
            (spuerbar windig, Einschraenkungen) — enthaelt crit NICHT doppelt,
            share_warn zaehlt inkl. crit-Spots (monotone Lesart: warn >= crit).
    """
    n = len(entries)
    if n == 0:
        return {"n_spots": 0, "share_wind_crit": None, "share_wind_warn": None,
                "share_aloft_crit": None, "share_gust_crit": None,
                "aloft_over_kmh": None, "gust_over_kmh": None,
                "wind_driver": None,
                "max_aloft_kmh": None, "median_aloft_kmh": None,
                "wind_class": None}
    crit = 0
    warn = 0
    aloft_crit = 0
    gust_crit = 0
    alofts = []
    gusts = []
    for e in entries:
        a = e.get("aloft_max")
        g = e.get("gust_max")
        if a is not None:
            alofts.append(a)
            if a > config.WIND_DANGER_KMH:
                aloft_crit += 1
        if g is not None:
            gusts.append(g)
            if g > config.GUST_DANGER_KMH:
                gust_crit += 1
        is_crit = ((a is not None and a > config.WIND_DANGER_KMH)
                   or (g is not None and g > config.GUST_DANGER_KMH))
        is_warn = is_crit or ((a is not None and a > config.WIND_WARN_KMH)
                              or (g is not None and g > config.GUST_WARN_KMH))
        if is_crit:
            crit += 1
        if is_warn:
            warn += 1
    share_crit = crit / n
    share_warn = warn / n
    share_aloft_crit = aloft_crit / n
    share_gust_crit = gust_crit / n

    # Kumulative Verteilung — Anteil der Spots ueber 10/20/.../60 km/h.
    # Gibt dem LLM das VOLLE Windbild statt eines einzelnen Schwellen-Flags
    # ("gut die Haelfte ueber 30, vereinzelt ueber 50" ist eine andere Lage
    # als "alle knapp ueber 30").
    def _cum_dist(values: list) -> Optional[dict]:
        if not values:
            return None
        m = len(values)
        return {str(t): round(sum(1 for v in values if v > t) / m, 2)
                for t in config.SYNOPTIC_WIND_DIST_BANDS_KMH}

    # Dominante Ursache der Wind-Kritikalitaet — Hoehenwind und Boden-Boeen
    # haben verschiedene Pilot-Konsequenzen (keine Basis oben vs. Start/
    # Landung kritisch) und muessen im Text unterscheidbar sein.
    if share_aloft_crit < 0.15 and share_gust_crit < 0.15:
        wind_driver = None
    elif share_aloft_crit >= 2 * share_gust_crit:
        wind_driver = "hoehenwind"
    elif share_gust_crit >= 2 * share_aloft_crit:
        wind_driver = "boeen"
    else:
        wind_driver = "beide"
    # Deterministisches Klassen-Label — autoritativ fuer die LLM-Wortwahl.
    # Zahlen-Kalibrierung allein befolgt der LLM unzuverlaessig; ein
    # explizites Label pro Tag/Seite haelt er ein (und der Post-Validator
    # prueft Lob-Vokabular dagegen).
    if share_crit >= 0.6:
        wind_class = "verblasen"
    elif share_crit >= 0.3:
        wind_class = "stark_eingeschraenkt"
    elif share_warn >= 0.5:
        wind_class = "windig"
    else:
        wind_class = "unauffaellig"
    return {
        "n_spots": n,
        "share_wind_crit": round(share_crit, 2),
        "share_wind_warn": round(share_warn, 2),
        "share_aloft_crit": round(share_aloft_crit, 2),
        "share_gust_crit": round(share_gust_crit, 2),
        "aloft_over_kmh": _cum_dist(alofts),
        "gust_over_kmh": _cum_dist(gusts),
        "wind_driver": wind_driver,
        "max_aloft_kmh": round(max(alofts), 1) if alofts else None,
        "median_aloft_kmh": round(statistics.median(alofts), 1) if alofts else None,
        "wind_class": wind_class,
    }


def decide_wind_pattern_nord_sued(weather_cache: dict,
                                  forecast_dates: list[str]) -> dict:
    """Aggregiert Wind-Fliegbarkeit pro Tag separat fuer Alpennord und -sued.

    Pro Spot pro Tag: max. Hoehenwind im vereinfachten Flugband + max.
    Boden-Boeen im Kern-Flugfenster. Aggregation pro Seite zu Anteilen
    (share_wind_crit/share_wind_warn) — die autoritative Datenbasis fuer
    die Flug-Bilanz des Synoptik-Blocks. Hintergrund: 05.07.2026 nannte
    die Synoptik einen Tag "excellent", an dem 23/29 Regionen am
    Hoehenwind scheiterten — sie hatte schlicht keine Wind-Fliegbarkeits-
    Daten im Input.
    """
    per_day = []
    spot_class = {}
    for spot_name, spot in weather_cache.items():
        if spot_name.startswith("_"):
            continue
        spot_class[spot_name] = _classify_nord_sued(
            spot.get("latitude"), spot.get("longitude"))

    for date in forecast_dates:
        nord_day = []
        sued_day = []
        for spot_name, side in spot_class.items():
            w = _spot_day_wind(weather_cache[spot_name], date)
            if w is None:
                continue
            if side == "alpennord":
                nord_day.append(w)
            elif side == "alpensued":
                sued_day.append(w)
        per_day.append({
            "date": date,
            "alpennord": _aggregate_wind_side(nord_day),
            "alpensued": _aggregate_wind_side(sued_day),
        })

    return {
        "per_day": per_day,
        "decided_by": "decide_wind_pattern_nord_sued",
        "thresholds": {
            "wind_warn_kmh": config.WIND_WARN_KMH,
            "wind_danger_kmh": config.WIND_DANGER_KMH,
            "gust_warn_kmh": config.GUST_WARN_KMH,
            "gust_danger_kmh": config.GUST_DANGER_KMH,
            "band_above_spot_m": [config.SYNOPTIC_WIND_BAND_LOWER_M,
                                  config.SYNOPTIC_WIND_BAND_UPPER_M],
            "hours": list(config.SYNOPTIC_WIND_HOURS),
        },
    }


# ============================================================================
# FLUGWETTER-ZONEN (Synoptik 2.0) — 4 Zonen + Tagesfenster + Zugbahn
# ============================================================================
# Zone = Summe ihrer Analyse-Regionen (zone-Spalte in data/regionen.csv);
# Spots erben die Zone ueber ihr analyse_region-Feld. Regionen werden NIE
# aufgeteilt — damit laesst sich die Synoptik spaeter sauber auf
# Regionen-Analysen herunterbrechen (Hierarchie Spot -> Region -> Zone -> CH).


def build_spot_region_map() -> dict[str, str]:
    """{sanitisierter Spot-Name: analyse_region} — der Regionsname, wie ihn
    App und Briefing anzeigen. Spots ohne analyse_region fehlen."""
    import spots as spots_mod
    return {s["name"]: (s.get("analyse_region") or "").strip()
            for s in spots_mod.load_spots()
            if (s.get("analyse_region") or "").strip()}


def merge_passagen_runs(max_runs: int = 3) -> tuple[list[dict], Optional[str]]:
    """Durchgangs-Aussagen der letzten Laeufe zusammenfuehren.

    Ein Lauf rechnet nur mit den DWD-Vorhersagekarten ab +36 h — die naechsten
    36 Stunden sieht der neueste Lauf NICHT (am 18.09.2026 fehlte so die
    Kaltfront, die der Vortageslauf fuer denselben Nachmittag angesetzt hatte).
    Deshalb: die letzten Laeufe uebereinanderlegen, je (Zone, Typ, Tag) gilt
    der neueste. Returns (aussagen, name der neuesten Datei)."""
    import glob
    import json
    from zoneinfo import ZoneInfo
    cands = sorted(glob.glob(str(config.PROJECT_ROOT / "validation" / "fronten"
                                 / "aussagen" / "passagen_*.json")))[-max_runs:]
    if not cands:
        return [], None
    tz = ZoneInfo("Europe/Zurich")
    by_key: dict = {}
    for f in cands:                       # alt -> neu: der neuere ueberschreibt
        try:
            with open(f, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            logger.warning("merge_passagen_runs: %s nicht lesbar", f)
            continue
        for a in raw.get("aussagen") or []:
            try:
                local = datetime.fromisoformat(
                    (a.get("durchgang_median_utc") or "").replace("Z", "+00:00")).astimezone(tz)
            except (TypeError, ValueError):
                continue
            a = dict(a)
            a["lauf"] = raw.get("lauf")
            by_key[(a.get("zone"), a.get("typ"), local.date().isoformat())] = a
    latest = max((a.get("lauf") or "" for a in by_key.values()), default="")
    for a in by_key.values():
        a["aus_vortageslauf"] = (a.get("lauf") or "") != latest
    return list(by_key.values()), Path(cands[-1]).name


def load_ist_durchgaenge(max_age_h: int = 36) -> list[dict]:
    """Tatsaechliche Durchgaenge aus der DWD-Analysekette
    (validation/fronten/observations.csv, Spalten ana_*), nicht aelter als
    max_age_h — fuer den Satz "gestern ist die Kaltfront durchgezogen, heute
    Rueckseite". Dedupliziert je (Zone, Typ, Stunde)."""
    import csv
    from datetime import timezone
    path = config.PROJECT_ROOT / "validation" / "fronten" / "observations.csv"
    if not path.exists():
        return []
    now = datetime.now(timezone.utc)
    out, seen = [], set()
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                am = (r.get("ana_median_utc") or "").strip()
                if not am or (r.get("ana_front_da") or "").strip() != "1":
                    continue
                try:
                    med = datetime.fromisoformat(am.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if med.tzinfo is None:
                    med = med.replace(tzinfo=timezone.utc)
                if med > now or (now - med).total_seconds() > max_age_h * 3600:
                    continue
                key = (r.get("zone"), r.get("typ"), am[:13])
                if key in seen:
                    continue
                seen.add(key)
                out.append({"zone": r.get("zone"), "typ": r.get("typ"),
                            "art": r.get("art") or "quert",
                            "median_utc": med.isoformat(timespec="minutes")})
    except OSError:
        return []
    out.sort(key=lambda d: d["median_utc"])
    return out


# build_spot_region_map liefert Regions-NAMEN (analyse_region), deshalb beide Formen
BISE_PLATEAU_REGIONS = ("mittelland_ost", "zentrales_mittelland", "genferseeregion",
                        "bodenseeraum", "tafeljura", "neuenburger_jura", "jura_zentral",
                        'Mittelland Ost', 'Genferseeregion', 'Tafeljura', 'Neuenburger Jura', 'Jura Zentral', 'Bodenseeraum', 'Zentrales Mittelland')


def bise_boden(weather_cache: dict, forecast_dates: list[str],
               region_map: dict[str, str]) -> Optional[dict]:
    """Zeigt sich die Bise der Synoptik am Boden? Je Tag der Anteil der
    Mittelland-/Jura-Startplaetze, an denen der 10-m-Wind im Flugfenster aus
    Nordost (30-90 Grad) mit >= 15 km/h weht, plus die staerkste Stunde."""
    h_start, h_end = config.FLIGHT_HOURS_START, config.FLIGHT_HOURS_END
    spots = [s for s, r in region_map.items() if r in BISE_PLATEAU_REGIONS and s in weather_cache]
    if not spots:
        return None
    per_day = []
    for date in forecast_dates:
        n_ne, n_all, max_kmh = 0, 0, 0.0
        for name in spots:
            hd = weather_cache[name].get("hourly_data") or {}
            best, seen = 0.0, False
            for hour in range(h_start, h_end):
                rec = hd.get(f"{date}T{hour:02d}:00") or {}
                d, v = rec.get("wind_direction_10m"), rec.get("wind_speed_10m")
                if not isinstance(d, (int, float)) or not isinstance(v, (int, float)):
                    continue
                seen = True
                if 30 <= d <= 90 and v >= 15:
                    best = max(best, float(v))
            if seen:
                n_all += 1
                if best > 0:
                    n_ne += 1
                    max_kmh = max(max_kmh, best)
        per_day.append({"date": date, "share_ne": (round(n_ne / n_all, 2) if n_all else None),
                        "max_kmh": round(max_kmh), "n_spots": n_all})
    return {"per_day": per_day, "decided_by": "bise_boden",
            "thresholds": {"dir_sector": [30, 90], "min_kmh": 15, "regions": list(BISE_PLATEAU_REGIONS)}}


def thermik_zonen(region_weather_data: dict, forecast_dates: list[str]) -> Optional[dict]:
    """Thermik und Basis je Zone und Tag aus den Regions-Prognosen
    (thermals_spotmedian: climb_rate m/s, max_height m, lcl m je Stunde;
    hourly_data: cloud_cover_low, sunshine_duration). Je Zone der Median ueber
    ihre Regionen: Tagesspitze des Steigens, Basis (lcl) um 13 Uhr, nutzbare
    Hoehe, Thermikbeginn (erste Stunde >= 0.5 m/s), tiefe Bewoelkung und
    Sonnenanteil im Mittagsfenster. Nur Prognosedaten."""
    if not region_weather_data or not forecast_dates:
        return None
    by_zone: dict[str, list[dict]] = {}
    for rdata in region_weather_data.values():
        if isinstance(rdata, dict):
            z = _zone_of_region(rdata)
            if z in config.SYNOPTIC_ZONES:
                by_zone.setdefault(z, []).append(rdata)
    h_start, h_end = config.FLIGHT_HOURS_START, config.FLIGHT_HOURS_END
    per_day = []
    for date in forecast_dates:
        zones = {}
        for z in config.SYNOPTIC_ZONES:
            climbs, bases, heights, starts, lows, suns = [], [], [], [], [], []
            totals, midhigh = [], []
            for r in by_zone.get(z) or []:
                th = r.get("thermals_spotmedian") or {}
                hd = r.get("hourly_data") or {}
                peak, start = 0.0, None
                for hour in range(h_start, h_end):
                    key = f"{date}T{hour:02d}:00"
                    t = th.get(key) or {}
                    c = t.get("climb_rate")
                    if isinstance(c, (int, float)):
                        peak = max(peak, float(c))
                        if start is None and c >= 0.5:
                            start = hour
                climbs.append(peak)
                if start is not None:
                    starts.append(start)
                t13 = th.get(f"{date}T13:00") or {}
                if isinstance(t13.get("lcl"), (int, float)):
                    bases.append(float(t13["lcl"]))
                if isinstance(t13.get("max_height"), (int, float)):
                    heights.append(float(t13["max_height"]))
                lo, su, tot, mh = [], [], [], []
                for hour in range(10, 16):
                    rec = hd.get(f"{date}T{hour:02d}:00") or {}
                    if isinstance(rec.get("cloud_cover_low"), (int, float)):
                        lo.append(float(rec["cloud_cover_low"]))
                    if isinstance(rec.get("cloud_cover"), (int, float)):
                        tot.append(float(rec["cloud_cover"]))
                    m = rec.get("cloud_cover_mid")
                    h = rec.get("cloud_cover_high")
                    if isinstance(m, (int, float)) or isinstance(h, (int, float)):
                        mh.append(max(float(m or 0), float(h or 0)))
                    if isinstance(rec.get("sunshine_duration"), (int, float)):
                        su.append(float(rec["sunshine_duration"]) / 3600.0)
                if lo:
                    lows.append(statistics.mean(lo))
                if su:
                    suns.append(statistics.mean(su))
                if tot:
                    totals.append(statistics.mean(tot))
                if mh:
                    midhigh.append(statistics.mean(mh))
            if not climbs:
                zones[z] = None
                continue
            zones[z] = {
                "climb_ms": round(statistics.median(climbs), 1),
                "base_m": (round(statistics.median(bases) / 100) * 100 if bases else None),
                "top_m": (round(statistics.median(heights) / 100) * 100 if heights else None),
                "start_hour": (int(statistics.median(starts)) if starts else None),
                "low_cloud_pct": (round(statistics.median(lows)) if lows else None),
                "cloud_pct": (round(statistics.median(totals)) if totals else None),
                "mid_high_pct": (round(statistics.median(midhigh)) if midhigh else None),
                "sun_share": (round(statistics.median(suns), 2) if suns else None),
                "n_regions": len(climbs),
            }
        per_day.append({"date": date, "zones": zones})
    return {"per_day": per_day, "decided_by": "thermik_zonen",
            "thresholds": {"start_climb_ms": 0.5, "base_hour": 13, "sun_hours": [10, 16]}}


# Modellvergleich: ein Punkt je Zone, fuenf Modelle (MeteoSchweiz, DWD, NOAA)
MODEL_COMPARE_POINTS = {
    "alpennordhang": (46.69, 7.86),        # Interlaken
    "wallis": (46.23, 7.36),               # Sion
    "tessin": (46.17, 8.80),               # Locarno
    "graubuenden_engadin": (46.85, 9.53),  # Chur
}
MODEL_COMPARE_MODELS = {
    "meteoswiss_icon_ch1": "ICON-CH1", "meteoswiss_icon_ch2": "ICON-CH2",
    "icon_d2": "ICON-D2", "icon_eu": "ICON-EU", "gfs_seamless": "GFS",
}


# Modellvergleich v2 (24.09.2026): Klassenraster je Groesse, Urteil je Region
# (Median ihrer Referenzpunkte je Modell), Zone uneinig ab einem Drittel
# uneiniger Regionen. "Uneinig" heisst zwei Klassen Abstand — Nachbarklassen (24 vs. 26 km/h) sind Grenzrauschen,
# kein Streit. Obere Klassen bis 80 km/h, damit 30 und 80 km/h nicht dasselbe
# Urteil bekommen. Gemessen wird je Tagesfenster (SYNOPTIC_DAY_WINDOWS im
# Flugtag), denn "Sturm am Vormittag" vs. "Sturm ab Mittag" ist fuer den
# Piloten der groesstmoegliche Streit — eine Tageszahl saehe ihn nicht.
MODEL_COMPARE_CLASSES = {
    "gust":      (15, 25, 40, 60, 80),          # km/h, Spitze im Fenster
    "speed":     (10, 20, 30, 45, 60, 80),      # km/h, Mittel im Fenster
    "cloud":     (20, 40, 60, 80),              # %, Mittel im Fenster
    "cloud_low": (20, 40, 60, 80),
}
MODEL_COMPARE_PARAMS = ("rain", "dir", "speed", "gust", "cloud", "cloud_low")
MODEL_COMPARE_THRESHOLDS = {
    "class_gap": 2,          # Klassen Abstand, ab dem ein Punkt "uneinig" ist
    "sector_gap": 2,         # Sektoren (45 Grad) Abstand fuer die Windrichtung
    "dir_min_speed_kmh": 8,  # Richtung nur bewertet, wenn ueberhaupt Wind weht
    "wet_mm": 1.0,           # nass im Fenster
    "region_share": 1 / 3,   # Anteil uneiniger Regionen, ab dem die Zone uneinig ist
    "spread_excludes": ["gfs_seamless"],   # bei Wind/Wolken nicht in der Wertung
}
MODEL_COMPARE_HOURLY = ("wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
                        "precipitation", "cloud_cover", "cloud_cover_low")


def _mc_class(param: str, val: float) -> int:
    return sum(1 for b in MODEL_COMPARE_CLASSES[param] if val >= b)


def _mc_sector(deg: float) -> int:
    return int(((deg + 22.5) % 360) // 45)


def _mc_sector_gap(a: int, b: int) -> int:
    d = abs(a - b) % 8
    return min(d, 8 - d)


def _mc_windows() -> list[tuple[str, int, int]]:
    """Tagesfenster im Flugtag (der Abend faellt raus)."""
    h_start, h_end = config.FLIGHT_HOURS_START, config.FLIGHT_HOURS_END
    return [(w, max(a, h_start), min(b, h_end)) for w, a, b in config.SYNOPTIC_DAY_WINDOWS
            if max(a, h_start) < min(b, h_end)]


def _mc_point_values(hourly: dict, models: list[str], date: str) -> dict:
    """Je Modell und Fenster die Kennzahlen eines Punkts. Ein Modell ohne
    Daten im Fenster (ICON-D2 nach 48 h) fehlt dort einfach."""
    times = hourly.get("time") or []
    idx = {t: i for i, t in enumerate(times)}
    out = {}
    for w, a, b in _mc_windows():
        row = {}
        for m in models:
            def col(name):
                arr = hourly.get(f"{name}_{m}") or []
                vals = []
                for h in range(a, b):
                    i = idx.get(f"{date}T{h:02d}:00")
                    if i is not None and i < len(arr) and isinstance(arr[i], (int, float)):
                        vals.append(float(arr[i]))
                return vals
            sp, dr, gu = col("wind_speed_10m"), col("wind_direction_10m"), col("wind_gusts_10m")
            ra, cl, lo = col("precipitation"), col("cloud_cover"), col("cloud_cover_low")
            if not sp and not gu and not ra:
                continue
            v = {}
            if gu:
                v["gust"] = max(gu)
            if sp:
                v["speed"] = statistics.mean(sp)
            if sp and dr and len(sp) == len(dr):
                sx = sum(s_ * math.cos(math.radians(d)) for s_, d in zip(sp, dr))
                sy = sum(s_ * math.sin(math.radians(d)) for s_, d in zip(sp, dr))
                if abs(sx) > 1e-9 or abs(sy) > 1e-9:
                    v["dir"] = (math.degrees(math.atan2(sy, sx)) + 360) % 360
            if ra:
                v["rain"] = sum(ra)
            if cl:
                v["cloud"] = statistics.mean(cl)
            if lo:
                v["cloud_low"] = statistics.mean(lo)
            row[m] = v
        out[w] = row
    return out


def _mc_verdict(summary: dict, param: str, thr: dict) -> Optional[bool]:
    """Streiten die Modelle ueber die Groesse? summary = je Modell {"cls",
    "val", "speed"} (aus _mc_model_summary). None = nicht bewertbar (nur ein
    Modell; Flaute bei der Richtung)."""
    excl = set(thr.get("spread_excludes") or []) if param != "rain" else set()
    rows = {m: v for m, v in summary.items() if m not in excl}
    if len(rows) < 2:
        return None
    cls = [int(v["cls"]) for v in rows.values()]
    if param == "rain":
        return 0 < sum(cls) < len(cls)
    if param == "dir":
        speeds = [v["speed"] for v in rows.values() if v.get("speed") is not None]
        if not speeds or statistics.mean(speeds) < thr["dir_min_speed_kmh"]:
            return None
        return max(_mc_sector_gap(a, b) for a in cls for b in cls) >= thr["sector_gap"]
    return max(cls) - min(cls) >= thr["class_gap"]


def _mc_gap(summary: dict, param: str, thr: dict) -> int:
    excl = set(thr.get("spread_excludes") or []) if param != "rain" else set()
    cls = [int(v["cls"]) for m, v in summary.items() if m not in excl]
    if len(cls) < 2:
        return 0
    if param == "dir":
        return max(_mc_sector_gap(a, b) for a in cls for b in cls)
    return max(cls) - min(cls)


def _mc_model_summary(rows: list[dict], param: str, thr: dict) -> dict:
    """Je Modell die typische Klasse ueber mehrere Punkte (Median) — damit
    vergleichen wir Modell gegen Modell, nicht Punkt-Rauschen gegen
    Punkt-Rauschen. rain: Anteil nasser Punkte (Klasse 1 ab der Haelfte),
    dir: Sektor des Vektor-Mittels, dazu der mittlere Grundwind."""
    per_model: dict[str, list] = {}
    speeds: dict[str, list] = {}
    for row in rows:
        for m, v in row.items():
            if v.get(param) is not None:
                per_model.setdefault(m, []).append(v[param])
                if v.get("speed") is not None:
                    speeds.setdefault(m, []).append(v["speed"])
    out = {}
    for m, vals in per_model.items():
        if param == "rain":
            share = sum(1 for x in vals if x >= thr["wet_mm"]) / len(vals)
            rec = {"cls": int(share >= 0.5), "val": round(share, 2)}
        elif param == "dir":
            sx = sum(math.cos(math.radians(d)) for d in vals)
            sy = sum(math.sin(math.radians(d)) for d in vals)
            deg = (math.degrees(math.atan2(sy, sx)) + 360) % 360
            rec = {"cls": _mc_sector(deg), "val": round(deg)}
        else:
            med = statistics.median(vals)
            rec = {"cls": _mc_class(param, med), "val": round(med)}
        if speeds.get(m):
            rec["speed"] = round(statistics.mean(speeds[m]), 1)
        out[m] = rec
    return out


def modell_vergleich_aus_punkten(points: list[dict], forecast_dates: list[str]) -> Optional[dict]:
    """Der Vergleich selbst, ohne API: points = [{"zone", "region", "hourly"}]
    mit Open-Meteo-hourly je Modell (Suffix _<modell>).

    Ebenen: Punkt -> Region (Median je Modell ueber ihre Punkte, dort das
    Urteil einig/uneinig) -> Zone (Anteil uneiniger Regionen). Das Urteil
    faellt auf Regionsebene, weil Punkt gegen Punkt nur Rauschen misst
    (Live-Probe 24.09.: 37 % der Punkte "uneinig", alle Modell-Mediane in
    derselben Klasse). Die Modell-Gruppen fuer den Satz kommen aus den
    uneinigen Regionen — und wenn deren Mediane den Streit verwischen, aus
    der Region mit dem groessten Abstand: der Satz zeigt immer zwei Gruppen."""
    thr = MODEL_COMPARE_THRESHOLDS
    models = list(MODEL_COMPARE_MODELS)
    windows = [w for w, _, _ in _mc_windows()]
    per_day = []
    for date in forecast_dates:
        zones: dict[str, Optional[dict]] = {}
        for zone in config.SYNOPTIC_ZONES:
            pts = [p for p in points if p.get("zone") == zone]
            if not pts:
                zones[zone] = None
                continue
            by_reg: dict[str, list[dict]] = {}
            for p in pts:
                by_reg.setdefault(p.get("region") or "", []).append(
                    _mc_point_values(p.get("hourly") or {}, models, date))
            params = {}
            for param in MODEL_COMPARE_PARAMS:
                wins = {}
                for w in windows:
                    reg_sum = {reg: _mc_model_summary([pv.get(w) or {} for pv in pvs], param, thr)
                               for reg, pvs in by_reg.items()}
                    verdicts = {reg: _mc_verdict(sm, param, thr) for reg, sm in reg_sum.items()}
                    judged = {reg: v for reg, v in verdicts.items() if v is not None}
                    if not judged:
                        continue
                    dis = sorted(reg for reg, v in judged.items() if v)
                    share = len(dis) / len(judged)
                    src = dis or list(judged)
                    summary = _mc_model_summary([pv.get(w) or {} for reg in src for pv in by_reg[reg]], param, thr)
                    if dis and not _mc_verdict(summary, param, thr):
                        worst = max(dis, key=lambda r: _mc_gap(reg_sum[r], param, thr))
                        summary = reg_sum[worst]
                    wins[w] = {"share": round(share, 2), "n_regions": len(judged),
                               "disagree": share >= thr["region_share"],
                               "regions": dis, "models": summary}
                if not wins:
                    continue
                worst_w = max(wins, key=lambda w: wins[w]["share"])
                params[param] = {"windows": wins, "disagree": any(v["disagree"] for v in wins.values()),
                                 "worst_window": worst_w, "share": wins[worst_w]["share"]}
            zones[zone] = {"n_points": len(pts), "n_regions": len(by_reg), "params": params} if params else None
        per_day.append({"date": date, "zones": zones})
    return {"per_day": per_day, "decided_by": "modell_vergleich", "version": 2,
            "models": MODEL_COMPARE_MODELS, "windows": windows,
            "classes": {k: list(v) for k, v in MODEL_COMPARE_CLASSES.items()},
            "thresholds": {k: (v if not isinstance(v, float) else round(v, 3)) for k, v in thr.items()}}


def _mc_points_from_regions(region_weather_data: Optional[dict]) -> list[dict]:
    pts = []
    for name, rdata in (region_weather_data or {}).items():
        if not isinstance(rdata, dict):
            continue
        zone = _zone_of_region(rdata)
        if zone not in config.SYNOPTIC_ZONES:
            continue
        for rp in rdata.get("reference_points") or []:
            if isinstance(rp, (list, tuple)) and len(rp) >= 2:
                pts.append({"zone": zone, "region": rdata.get("region_name") or name,
                            "lat": float(rp[0]), "lon": float(rp[1])})
    return pts


def modell_vergleich(forecast_dates: list[str],
                     region_weather_data: Optional[dict] = None) -> Optional[dict]:
    """Sind sich die Modelle einig? Auf ALLEN Referenzpunkten der Regionen
    (Alpennordhang 112, Graubuenden 49, Wallis 28, Tessin 14; ohne Regionsdaten
    die vier Punkte MODEL_COMPARE_POINTS), fuer ICON-CH1/CH2 (MeteoSchweiz),
    ICON-D2/EU (DWD) und GFS (NOAA), je Tagesfenster: Regen, Windrichtung,
    Grundwind, Boeen, Bewoelkung, tiefe Bewoelkung. Regeln: MODEL_COMPARE_*
    oben, Rechnung in modell_vergleich_aus_punkten. Doku docs/BRIEFING.md.
    Kosten: 203 Punkte x 5 Modelle in 5 Calls, ~2 s (Probe 24.09.2026)."""
    if not forecast_dates:
        return None
    pts = _mc_points_from_regions(region_weather_data)
    if not pts:
        pts = [{"zone": z, "region": z, "lat": lat, "lon": lon}
               for z, (lat, lon) in MODEL_COMPARE_POINTS.items()]
    models = list(MODEL_COMPARE_MODELS)
    base = {"timezone": "Europe/Zurich", "hourly": ",".join(MODEL_COMPARE_HOURLY),
            "models": ",".join(models), "forecast_days": max(len(forecast_dates), 3)}
    config.with_api_key(base)
    chunk = 50
    got = []
    for i in range(0, len(pts), chunk):
        part = pts[i:i + chunk]
        params = {**base, "latitude": ",".join(f"{p['lat']:.4f}" for p in part),
                  "longitude": ",".join(f"{p['lon']:.4f}" for p in part)}
        try:
            resp = requests.get(config.API_URL, params=params, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("modell_vergleich: Punkte %d-%d fehlgeschlagen: %s", i, i + len(part), e)
            continue
        if not isinstance(data, list):
            data = [data]
        for p, d in zip(part, data):
            got.append({**p, "hourly": (d or {}).get("hourly") or {}})
    if not got:
        return None
    return modell_vergleich_aus_punkten(got, forecast_dates)


def starkwind_punkte(weather_cache: dict, forecast_dates: list[str],
                     region_map: dict[str, str]) -> Optional[dict]:
    """Starke Winde an einzelnen Startplaetzen — Prognosepunkte, keine
    Messungen, und ohne Tal-Zuordnung (welcher Punkt im Tal liegt, wissen wir
    nicht). Je Tag: die staerkste 10-m-Boe im Flugfenster mit Spot, Region,
    Hoehe, Richtung und dem CH2-Wert derselben Stunde (Modell-Uneinigkeit),
    plus Anteil der Spots mit Boeen >= 40 km/h."""
    h_start, h_end = config.FLIGHT_HOURS_START, config.FLIGHT_HOURS_END
    per_day = []
    for date in forecast_dates:
        best, n_strong, n_all = None, 0, 0
        for spot, region in region_map.items():
            sd = weather_cache.get(spot) or {}
            hd = sd.get("hourly_data") or {}
            mx, seen = None, False
            for hour in range(h_start, h_end):
                rec = hd.get(f"{date}T{hour:02d}:00") or {}
                g = rec.get("wind_gusts_10m")
                if not isinstance(g, (int, float)):
                    continue
                seen = True
                if mx is None or g > mx[0]:
                    mx = (float(g), hour, rec.get("wind_direction_10m"), rec.get("wind_gusts_10m_ch2"))
            if not seen:
                continue
            n_all += 1
            if mx[0] >= 40:
                n_strong += 1
            if best is None or mx[0] > best[0]:
                best = (mx[0], spot, region, sd.get("elevation_m"), mx[1], mx[2], mx[3])
        if best is None:
            per_day.append({"date": date, "max_gust_kmh": None})
            continue
        per_day.append({
            "date": date, "max_gust_kmh": round(best[0]), "spot": best[1], "region": best[2],
            "elevation_m": best[3], "hour": best[4],
            "dir_deg": (round(best[5]) if isinstance(best[5], (int, float)) else None),
            "gust_ch2_kmh": (round(best[6]) if isinstance(best[6], (int, float)) else None),
            "n_spots": n_all, "share_strong": (round(n_strong / n_all, 2) if n_all else None),
        })
    return {"per_day": per_day, "decided_by": "starkwind_punkte",
            "thresholds": {"strong_gust_kmh": 40, "hours": [h_start, h_end]}}


def load_dwd_frontdurchgaenge(forecast_dates: list[str]) -> Optional[dict]:
    """DWD-Frontenprognose als Strukturfeld-Block fuer die KI.

    Quelle: validation/fronten/aussagen/passagen_*.json — der Server rechnet
    aus den DWD-Vorhersagekarten (+36…+108 h) je Zone, ob und wann eine Front
    die Zone quert oder streift. Bis 2026-09 bekam die KI keine Frontendaten
    und durfte deshalb keine Fronten nennen (Halluzinationsschutz). Jetzt
    liegen die Durchgaenge vor; die KI darf sie nennen — und nur sie.

    Returns None, wenn keine Datei da ist (dann bleibt das Frontverbot).
    """
    from zoneinfo import ZoneInfo
    aussagen, datei = merge_passagen_runs()
    if datei is None:
        return None
    tz = ZoneInfo("Europe/Zurich")
    window_end = forecast_dates[-1] if forecast_dates else ""

    def _local(iso):
        try:
            return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(tz)
        except (TypeError, ValueError, AttributeError):
            return None

    out = []
    for a in aussagen:
        local = _local(a.get("durchgang_median_utc") or "")
        if local is None:
            continue
        tag = local.date().isoformat()
        von = _local(a.get("fenster_von_utc") or "") or local
        bis = _local(a.get("fenster_bis_utc") or "") or local
        out.append({
            "zone": a.get("zone"),
            "typ": a.get("typ"),                       # kalt | warm | okklusion
            "art": a.get("art"),                       # quert | streift
            "tag": tag,
            "fenster_lokal": [von.strftime("%H:%M"), bis.strftime("%H:%M")],
            # Randkontakt: DWD-Linie trifft nur den Zonenrand oder kaum Spots —
            # die KI muss das als unsicher formulieren
            "randkontakt": bool(a.get("randwert")) or (a.get("anteil") or 0) < 0.1,
            "im_fenster": bool(window_end) and tag <= window_end,
            # aus dem Vortageslauf uebernommen (der neueste sieht <36 h nicht)
            "aus_vortageslauf": bool(a.get("aus_vortageslauf")),
        })
    out.sort(key=lambda d: (d["tag"], d["fenster_lokal"][0]))
    # durchgezogene Fronten der letzten 36 h (DWD-Analyse) — Rueckseite
    vergangen = []
    for e in load_ist_durchgaenge():
        local = _local(e["median_utc"])
        if local is None:
            continue
        vergangen.append({"zone": e["zone"], "typ": e["typ"], "art": e["art"],
                          "tag": local.date().isoformat(),
                          "zeit_lokal": local.strftime("%H:%M")})
    return {
        "quelle": "DWD-Frontenprognose",
        "lauf": datei,
        "durchgaenge": out,
        "vergangen": vergangen,
        "decided_by": "load_dwd_frontdurchgaenge",
        "inputs": {"datei": datei},
    }


def decide_aloft_regional(weather_cache: dict, forecast_dates: list[str],
                          region_map: dict[str, str]) -> dict:
    """Staerkster Hoehenwind (700 hPa) je Tag auf Regionsebene.

    Das Schweizer Mittel in flow_overhead ist ein Vektor-Mittel: gegenlaeufige
    Winde heben sich auf, und 18 km/h im Mittel standen am 16.09.2026 neben
    Regionen, die verblasen waren. Deshalb zusaetzlich die Spitze — ohne
    Ausreisser:
      1. je Region und Stunde der MEDIAN ueber ihre Spots (ein einzelner Spot
         kann den Wert nicht treiben; Regionen unter
         SYNOPTIC_ALOFT_REGION_MIN_SPOTS zaehlen nicht mit)
      2. je Region die Spitze dieser Stundenwerte im Flugfenster
         FLIGHT_HOURS_START..END
      3. die staerkste Region — eine genuegt fuer "regional bis xx km/h"

    Returns: {"per_day": [{"date", "max_kmh", "region", "hour", "top",
              "n_regions"}], "decided_by", "thresholds"}
      top — die drei staerksten Regionen [{"region", "kmh"}]
    """
    min_spots = config.SYNOPTIC_ALOFT_REGION_MIN_SPOTS
    h_start, h_end = config.FLIGHT_HOURS_START, config.FLIGHT_HOURS_END
    spots_by_region: dict[str, list[str]] = {}
    for spot, region in region_map.items():
        if spot in weather_cache:
            spots_by_region.setdefault(region, []).append(spot)

    per_day = []
    for date in forecast_dates:
        peaks = []   # (kmh, region, hour)
        for region, spot_names in spots_by_region.items():
            best = None
            for hour in range(h_start, h_end):
                key = f"{date}T{hour:02d}:00"
                vals = []
                for name in spot_names:
                    rec = ((weather_cache[name].get("pressure_level_data") or {})
                           .get(key) or {})
                    v = rec.get("wind_speed_700hPa")
                    if isinstance(v, (int, float)):
                        vals.append(v)
                if len(vals) < min_spots:
                    continue
                med = statistics.median(vals)
                if best is None or med > best[0]:
                    best = (med, hour)
            if best is not None:
                peaks.append((best[0], region, best[1]))
        peaks.sort(key=lambda p: -p[0])
        if not peaks:
            per_day.append({"date": date, "max_kmh": None, "region": None,
                            "hour": None, "top": [], "n_regions": 0})
            continue
        kmh, region, hour = peaks[0]
        lo_kmh, lo_region, _ = peaks[-1]
        per_day.append({
            "date": date, "max_kmh": round(kmh), "region": region, "hour": hour,
            # Spanne ueber die Regionen: die schwaechste Regionsspitze — der
            # Pilot will den Bereich, nicht das Schweizer Mittel
            "min_kmh": round(lo_kmh), "min_region": lo_region,
            "top": [{"region": r, "kmh": round(k)} for k, r, _ in peaks[:3]],
            "n_regions": len(peaks),
        })
    return {
        "per_day": per_day,
        "decided_by": "decide_aloft_regional",
        "thresholds": {"region_min_spots": min_spots,
                       "hours": [h_start, h_end], "level_hpa": 700},
    }


def build_spot_zone_map() -> dict[str, str]:
    """{sanitisierter Spot-Name: zone_id} — Kette Spot -> analyse_region ->
    regionen.csv[zone].

    Spot-Namen sind bereits sanitisiert (spots.load_spots nutzt
    sanitize_spot_name) und matchen damit die weather_cache-Keys.
    Spots ohne aufloesbare analyse_region fallen auf eine grobe
    Lat/Lon-Heuristik zurueck (defensiv — aktuell 0 Faelle).
    """
    import csv as _csv
    import spots as spots_mod

    zone_by_region: dict[str, str] = {}
    try:
        with open(config.REGIONEN_CSV_PATH, encoding="utf-8-sig", newline="") as f:
            for row in _csv.DictReader(f):
                z = (row.get("zone") or "").strip()
                if z:
                    zone_by_region[(row.get("region_name") or "").strip()] = z
    except OSError as e:
        logger.error("build_spot_zone_map: regionen.csv nicht lesbar: %s", e)

    out: dict[str, str] = {}
    for s in spots_mod.load_spots():
        ar = (s.get("analyse_region") or "").strip()
        zone = zone_by_region.get(ar)
        if zone is None:
            zone = _classify_zone_fallback(s.get("latitude"), s.get("longitude"))
        if zone in config.SYNOPTIC_ZONES:
            out[s["name"]] = zone
    return out


def summarize_convection(region_weather_data: dict,
                          forecast_dates: list[str]) -> Optional[dict]:
    """Weiche Konvektions-Signale je Tag und Zone — fuer die Wetterlage.

    Ergaenzt gewitter_share (deterministischer Code, erkennt nur ~13 % der
    Gewittertage, Saison-Backtest docs/GEWITTER.md par.0c) um die Signale,
    die Spots/Regionen seit 03.08. laengst haben: Ensemble-Gewitterstunden
    und Ueberentwicklung (convection.py — DIESELBEN Regeln wie Meteogramm
    und Regions-KI, die Wetterlage kann der Regions-Analyse nie widersprechen).

    Zonen-Zuordnung: Mittel der Referenzpunkte -> _classify_zone_fallback.
    Rueckgabe {"per_day": [{"date", "zones": {zone: {"gewitter": [[Region,
    "HH-HH"], ...], "ueberentwicklung": [...]}}}]} oder None ohne Daten.
    """
    import convection
    if not region_weather_data:
        return None
    out = []
    for d in forecast_dates:
        zones = {z: {"gewitter": [], "ueberentwicklung": []}
                 for z in config.SYNOPTIC_ZONES}
        for rid, rdata in region_weather_data.items():
            if not isinstance(rdata, dict):
                continue
            refs = rdata.get("reference_points") or []
            lats = [r[0] for r in refs if isinstance(r, (list, tuple)) and len(r) >= 2]
            lons = [r[1] for r in refs if isinstance(r, (list, tuple)) and len(r) >= 2]
            if not lats:
                continue
            zone = _classify_zone_fallback(sum(lats) / len(lats),
                                           sum(lons) / len(lons))
            if zone not in zones:
                continue
            ens = (rdata.get("thunder_ensemble") or {}).get(d) or {}
            shares = ens.get("hourly_share_pct") or {}
            hourly = rdata.get("hourly_data") or {}
            therms = rdata.get("thermals_spotmedian") or {}
            cloud_top = rdata.get("cloud_top") or {}
            storm_hours, od_hours = [], []
            for ts in sorted(hourly):
                if not ts.startswith(d):
                    continue
                data = hourly.get(ts) or {}
                _wc = data.get("weather_code")
                storm = (convection.is_ensemble_storm_hour(
                             shares.get(ts[11:16]), data)
                         or (_wc is not None and int(_wc) in (95, 96, 99)))
                if storm:
                    storm_hours.append(ts[11:16])
                elif convection.is_overdev_hour(cloud_top.get(ts), data,
                                                therm=therms.get(ts)):
                    od_hours.append(ts[11:16])
            rname = rdata.get("region_name") or rid
            if storm_hours:
                zones[zone]["gewitter"].append(
                    [rname, f"{storm_hours[0]}-{storm_hours[-1]}"])
            if od_hours:
                zones[zone]["ueberentwicklung"].append(
                    [rname, f"{od_hours[0]}-{od_hours[-1]}"])
        out.append({"date": d, "zones": zones})
    return {"per_day": out}


_DRUCK_TAGESGANG_PATH = config.DATA_DIR / "druck_tagesgang.json"
_druck_tagesgang_cache: Optional[dict] = None


def load_druck_tagesgang(path=None) -> dict:
    """Mittlerer Tagesgang pressure_msl je Zone und Monat: {zone: {"MM": [24
    Anomalien zum Tagesmittel, hPa]}} aus data/druck_tagesgang.json
    (scripts/druck_tagesgang.py). Ueber den Alpen sind das 1-2 hPa am Tag —
    ohne Abzug misst jede Intraday-Tendenz die Tageszeit (23.09.2026).
    Fehlt die Datei: {} und eine Warnung, die Rechnung laeuft unkorrigiert."""
    global _druck_tagesgang_cache
    if path is None and _druck_tagesgang_cache is not None:
        return _druck_tagesgang_cache
    p = Path(path) if path else _DRUCK_TAGESGANG_PATH
    try:
        with open(p, encoding="utf-8") as f:
            zones = (json.load(f) or {}).get("zones") or {}
    except FileNotFoundError:
        logger.warning("druck_tagesgang.json fehlt (%s) — Drucktendenz ohne "
                       "Tagesgang-Korrektur", p)
        zones = {}
    except (OSError, ValueError) as e:
        logger.warning("druck_tagesgang.json unlesbar: %s", e)
        zones = {}
    if path is None:
        _druck_tagesgang_cache = zones
    return zones


def _trend_hpa(msl: dict, hs: list) -> Optional[float]:
    """Lineare Tendenz 06-22 h als Gesamtaenderung ueber das Fenster (hPa).
    Regression statt Endpunkt-Differenz: zwei Einzelstunden tragen den Rest
    des Tagesgangs und jede Modell-Zacke voll, die Gerade nicht."""
    if len(hs) < 4:
        return None
    ys = [msl[h] for h in hs]
    xm = sum(hs) / len(hs)
    ym = sum(ys) / len(ys)
    den = sum((h - xm) ** 2 for h in hs) or 1.0
    slope = sum((h - xm) * (y - ym) for h, y in zip(hs, ys)) / den
    return round(slope * (hs[-1] - hs[0]), 1)


_ZONEN_NORD = ("alpennordhang", "wallis", "graubuenden_engadin")
_ZONEN_SUED = ("tessin",)


def druck_tag_aus_verlauf(verlauf: dict) -> Optional[dict]:
    """Der Drucktag ueber alle Zonen — zwei Kennzahlen mit zwei Jobs.

    Tendenz (Zustand -> Mittel): Mittel der bereinigten 06-22-h-Tendenzen,
    aber nur wenn die Zonen einig sind (keine Zone >= +Schwelle bei einer
    anderen <= -Schwelle). Sonst `einig=false` und, wenn erkennbar, das
    Muster: Nord-Sued (Alpennordhang/Wallis/Graubuenden gegen Tessin) oder
    eine Einzelzone gegen den Rest. Ohne Muster bleibt es "uneinheitlich".
    Sprung (Ereignis -> Maximum): der betragsgroesste 3-h-Sprung ueber alle
    Zonen mit Stunde und Zone; `sprung_hot` ab SYNOPTIC_DRUCK_SPRUNG_HPA.
    Ein Mittel wuerde eine Front, die nur eine Zone trifft, wegmitteln."""
    tr = {z: v["druck_trend_hpa"] for z, v in (verlauf or {}).items()
          if isinstance(v, dict) and v.get("druck_trend_hpa") is not None}
    if not tr:
        return None
    thr = config.SYNOPTIC_DRUCK_TENDENZ_HPA
    up = sorted(z for z, t in tr.items() if t >= thr)
    down = sorted(z for z, t in tr.items() if t <= -thr)
    einig = not (up and down)
    muster = None
    if not einig:
        nord = [z for z in _ZONEN_NORD if z in up or z in down]
        sued = [z for z in _ZONEN_SUED if z in up or z in down]
        nord_einig = len({z in up for z in nord}) == 1
        sued_einig = len({z in up for z in sued}) == 1
        if nord and sued and nord_einig and sued_einig and (nord[0] in up) != (sued[0] in up):
            muster = {"art": "nord_sued", "nord": "up" if nord[0] in up else "down",
                      "sued": "up" if sued[0] in up else "down"}
        elif len(up) == 1 and len(down) >= 2:
            muster = {"art": "einzel", "zone": up[0], "richtung": "up"}
        elif len(down) == 1 and len(up) >= 2:
            muster = {"art": "einzel", "zone": down[0], "richtung": "down"}
    sprung = None
    for z, v in (verlauf or {}).items():
        if not isinstance(v, dict) or v.get("sprung_max_hpa") is None:
            continue
        if sprung is None or abs(v["sprung_max_hpa"]) > abs(sprung["hpa"]):
            sprung = {"hpa": v["sprung_max_hpa"], "hour": v.get("sprung_max_hour"), "zone": z}
    return {
        "tendenz_hpa": round(statistics.mean(tr.values()), 1) if einig else None,
        "einig": einig, "steigend": up, "fallend": down, "muster": muster,
        "sprung": sprung,
        "sprung_hot": bool(sprung and abs(sprung["hpa"]) >= config.SYNOPTIC_DRUCK_SPRUNG_HPA),
    }


def _zone_of_region(rdata: dict) -> Optional[str]:
    refs = rdata.get("reference_points") or []
    lats = [r[0] for r in refs if isinstance(r, (list, tuple)) and len(r) >= 2]
    lons = [r[1] for r in refs if isinstance(r, (list, tuple)) and len(r) >= 2]
    if not lats:
        return None
    return _classify_zone_fallback(sum(lats) / len(lats), sum(lons) / len(lons))


def _circ_mean_deg(degs: list[float]) -> Optional[float]:
    if not degs:
        return None
    sx = sum(math.cos(math.radians(d)) for d in degs)
    sy = sum(math.sin(math.radians(d)) for d in degs)
    if abs(sx) < 1e-9 and abs(sy) < 1e-9:
        return None
    return (math.degrees(math.atan2(sy, sx)) + 360) % 360


def detect_frontsignatur(region_weather_data: dict, forecast_dates: list[str],
                         tagesgang: Optional[dict] = None) -> Optional[dict]:
    """Frontdurchgang in den EIGENEN Prognosedaten je Zone und Tag.

    Die DWD-Karte sagt, wo eine Front gezeichnet ist; ob sie an einem Tag
    ueber eine Zone zieht, muss die Prognose zeigen. Signatur eines
    Durchgangs (Stundenmediane ueber die Regionen der Zone):
      - Druck: Minimum, davor fallend, danach in 3 h >= +1.2 hPa (Pflicht)
      - Wind 700 hPa: Drehung >= 40 Grad zwischen h-3 und h+3 (Pflicht)
      - dazu mindestens eines: T850 in 6 h um >= 2 K gefallen (Kaltfront)
        oder gestiegen (Warmfront), oder >= 1 mm Regen um den Zeitpunkt
    Stundenschluessel sind Lokalzeit (wie ueberall im Cache).

    Der Druck wird vorher um den mittleren Tagesgang der Zone bereinigt
    (`tagesgang`, Default data/druck_tagesgang.json; {} = keine Korrektur).

    Returns {"per_day": [{"date", "zones": {zone: sig | None}, "verlauf":
    {zone: {...}}, "druck_tag": {...}}]}; sig =
    {"hour": "16:00", "druck_hpa": +1.8, "drehung": [225, 300],
     "t850_k": -2.5 | None, "regen_mm": 3.1, "typ_hinweis": "kalt"|"warm"|None};
    verlauf je Zone: druck_trend_hpa (bereinigt, 06-22 h), druck_trend_roh_hpa,
    sprung_max_hpa/-hour (betragsgroesster 3-h-Sprung), anstieg_max_hpa,
    fall_max_hpa, tagesgang_korrigiert, max_drehung_deg, regen_mm;
    druck_tag: siehe druck_tag_aus_verlauf.
    """
    if not region_weather_data or not forecast_dates:
        return None
    if tagesgang is None:
        tagesgang = load_druck_tagesgang()
    by_zone: dict[str, list[dict]] = {}
    for rdata in region_weather_data.values():
        if not isinstance(rdata, dict):
            continue
        z = _zone_of_region(rdata)
        if z in config.SYNOPTIC_ZONES:
            by_zone.setdefault(z, []).append(rdata)

    def series(regions, date, hkey, pkey, field):
        out = {}
        for h in range(24):
            key = f"{date}T{h:02d}:00"
            vals = []
            for r in regions:
                rec = ((r.get(pkey) or {}).get(key) or {})
                v = rec.get(field)
                if isinstance(v, (int, float)):
                    vals.append(float(v))
            if vals:
                out[h] = vals
        return out

    per_day = []
    for date in forecast_dates:
        zones: dict = {}
        verlauf: dict = {}
        for z in config.SYNOPTIC_ZONES:
            regions = by_zone.get(z) or []
            sig = None
            if regions:
                msl_raw = {h: statistics.median(v) for h, v in
                           series(regions, date, "hourly_data", "hourly_data", "pressure_msl").items()}
                # Tagesgang abziehen — sonst misst jede Tendenz die Tageszeit
                # statt das Wetter (06->22 h im Sept. um +0,7..+1,0 hPa verzerrt)
                cyc = (tagesgang.get(z) or {}).get(date[5:7]) or []
                korr = len(cyc) == 24
                msl = {h: v - cyc[h] for h, v in msl_raw.items()} if korr else dict(msl_raw)
                wd = {h: _circ_mean_deg(v) for h, v in
                      series(regions, date, "pressure_level_data", "pressure_level_data",
                             "wind_direction_700hPa").items()}
                t850 = {h: statistics.median(v) for h, v in
                        series(regions, date, "pressure_level_data", "pressure_level_data",
                               "temperature_850hPa").items()}
                rain = {h: statistics.median(v) for h, v in
                        series(regions, date, "hourly_data", "hourly_data", "precipitation").items()}
                best = None
                for h in range(3, 21):
                    if not all(k in msl for k in (h - 3, h, h + 3)):
                        continue
                    rise = msl[h + 3] - msl[h]
                    fall = msl[h] - msl[h - 3]
                    if rise < 1.2 or fall > -0.3:
                        continue
                    if msl[h] > min(msl.get(k, 9e9) for k in range(h - 3, h + 4)):
                        continue                              # kein lokales Minimum
                    a, b = wd.get(h - 3), wd.get(h + 3)
                    if a is None or b is None:
                        continue
                    turn = abs((b - a + 180) % 360 - 180)
                    if turn < 40:
                        continue
                    dt = (t850.get(h + 3) - t850.get(h - 3)
                          if h + 3 in t850 and h - 3 in t850 else None)
                    mm = sum(rain.get(k, 0.0) for k in range(h - 2, h + 4))
                    if not ((dt is not None and abs(dt) >= 2.0) or mm >= 1.0):
                        continue
                    score = rise + turn / 40 + (abs(dt) if dt else 0) + min(mm, 5) / 2
                    if best is None or score > best[0]:
                        best = (score, {
                            "hour": f"{h:02d}:00",
                            "druck_hpa": round(rise, 1),
                            "drehung": [round(a), round(b)],
                            "t850_k": round(dt, 1) if dt is not None else None,
                            "regen_mm": round(mm, 1),
                            "typ_hinweis": ("kalt" if dt is not None and dt <= -2.0
                                            else "warm" if dt is not None and dt >= 2.0
                                            else None),
                        })
                sig = best[1] if best else None
                # Tagesverlauf als Gegenbeleg und fuer die Druckzeile: Tendenz
                # 06-22 h auf der bereinigten Reihe und der groesste 3-h-Sprung
                # des ganzen Tages (eine Front um 03 h zaehlt fuer den Tag)
                hs = [h for h in range(6, 23) if h in msl]
                wds = [wd[h] for h in range(6, 23) if wd.get(h) is not None]
                max_turn = 0
                for i in range(len(wds)):
                    for j in range(i + 1, len(wds)):
                        max_turn = max(max_turn, abs((wds[j] - wds[i] + 180) % 360 - 180))
                d3 = [(msl[h + 3] - msl[h], h) for h in range(0, 21) if h in msl and h + 3 in msl]
                sprung = max(d3, key=lambda t: abs(t[0])) if d3 else None
                verlauf[z] = {
                    "druck_trend_hpa": _trend_hpa(msl, hs),
                    "druck_trend_roh_hpa": (round(msl_raw[hs[-1]] - msl_raw[hs[0]], 1)
                                            if len(hs) >= 2 else None),
                    "sprung_max_hpa": round(sprung[0], 1) if sprung else None,
                    "sprung_max_hour": f"{sprung[1]:02d}:00" if sprung else None,
                    "anstieg_max_hpa": round(max(v for v, _ in d3), 1) if d3 else None,
                    "fall_max_hpa": round(min(v for v, _ in d3), 1) if d3 else None,
                    "tagesgang_korrigiert": korr,
                    "max_drehung_deg": round(max_turn),
                    "regen_mm": round(sum(rain.get(h, 0.0) for h in range(6, 23)), 1),
                }
            zones[z] = sig
        per_day.append({"date": date, "zones": zones, "verlauf": verlauf,
                        "druck_tag": druck_tag_aus_verlauf(verlauf)})
    return {"per_day": per_day, "decided_by": "detect_frontsignatur",
            "thresholds": {"druck_hpa_3h": 1.2, "drehung_deg": 40, "t850_k_6h": 2.0,
                           "regen_mm": 1.0, "level_hpa": 700,
                           "tendenz_hpa": config.SYNOPTIC_DRUCK_TENDENZ_HPA,
                           "sprung_hpa_3h": config.SYNOPTIC_DRUCK_SPRUNG_HPA}}


def _classify_zone_fallback(lat, lon) -> Optional[str]:
    """Grobe Lat/Lon-Zuordnung fuer Spots ohne analyse_region-Match."""
    if lat is None or lon is None:
        return None
    if lat < 46.45 and lon > 8.5:
        return "tessin"
    if lat < 46.45 and 6.5 < lon <= 8.5:
        return "wallis"
    if lon > 9.0:
        return "graubuenden_engadin"
    return "alpennordhang"


def _p90(values: list[float]) -> float:
    """P90 einer Werteliste (robust gegen Einzelspot-Ausreisser).

    Hintergrund: das Tages-Maximum ueber ~330 Spots ist regelmaessig ein
    Einzelspot-Artefakt (35 mm/h an einem Gletscher-Spot praegte am
    25.07.2026 die Aussage fuer die halbe Schweiz). P90 traegt das Bild,
    das Maximum wird separat mitgefuehrt.
    """
    if not values:
        return 0.0
    vals = sorted(values)
    idx = max(0, math.ceil(0.9 * len(vals)) - 1)
    return vals[idx]


def _aggregate_precip_bucket(entries: list[dict]) -> dict:
    """Aggregiert Spot-Niederschlagswerte eines Fensters/Tages einer Zone.

    entries: [{peak_mm, wet, has_ts, max_cape}] pro Spot.
    """
    n = len(entries)
    if n == 0:
        return {"n_spots": 0, "wet_share": None, "p90_mm": None,
                "max_mm": None, "gewitter_share": None, "max_wc": None,
                "max_cape": None}
    peaks = [e["peak_mm"] for e in entries]
    return {
        "n_spots": n,
        "wet_share": round(sum(1 for e in entries if e["wet"]) / n, 2),
        "p90_mm": round(_p90(peaks), 1),
        "max_mm": round(max(peaks), 1),
        # 3 Nachkommastellen: 1 echte Gewitterzelle unter 327 Nordhang-Spots
        # (1/327 = 0.003) darf nicht auf 0.0 wegrunden — die Skill-Regel
        # "Gewitter nur bei gewitter_share > 0" haengt daran.
        "gewitter_share": round(sum(1 for e in entries if e["has_ts"]) / n, 3),
        "max_wc": max(e["max_wc"] for e in entries),
        "max_cape": round(max(e["max_cape"] for e in entries), 0),
    }


def decide_precip_pattern_zones(weather_cache: dict, forecast_dates: list[str],
                                zone_map: dict[str, str]) -> dict:
    """Niederschlag pro Tag, Zone und Tagesfenster (Morgen/Mittag/
    Nachmittag/Abend) — die Zeitachsen-erhaltende Nachfolge von
    decide_precip_pattern_nord_sued.

    Pro Fenster und Zone: wet_share (Anteil Spots mit >= WINDOW_WET_MM in
    einer Fensterstunde), p90_mm/max_mm (robuster Peak + Extrem),
    gewitter_share (weather_code 95/96/99 im Fenster), max_cape.
    Zusaetzlich ein Tages-Aggregat pro Zone (kompatible Kennzahlen inkl.
    max_coverage fuer stratiform-vs-konvektiv).
    """
    windows = config.SYNOPTIC_DAY_WINDOWS
    wet_mm = config.SYNOPTIC_PRECIP_WINDOW_WET_MM
    per_day = []

    for date in forecast_dates:
        zones_out: dict[str, dict] = {}
        # Sammel-Struktur: zone -> window_key -> [spot-entries]
        win_buckets = {z: {w[0]: [] for w in windows} for z in config.SYNOPTIC_ZONES}
        day_buckets = {z: [] for z in config.SYNOPTIC_ZONES}
        cov_by_zone = {z: [] for z in config.SYNOPTIC_ZONES}

        for spot_name, zone in zone_map.items():
            spot = weather_cache.get(spot_name)
            if not spot:
                continue
            hd = spot.get("hourly_data") or {}
            recs = []
            for t, rec in hd.items():
                if not t.startswith(date):
                    continue
                try:
                    hour = int(t[11:13])
                except (ValueError, IndexError):
                    continue
                if 6 <= hour <= 20:
                    recs.append((hour, rec))
            if not recs:
                continue

            # Tages-Aggregat (Semantik wie bisher: wet = total >= DRY_MM)
            precs = [(h, r.get("precipitation") or 0) for h, r in recs]
            total = sum(p for _, p in precs)
            day_buckets[zone].append({
                "peak_mm": max(p for _, p in precs),
                "wet": total >= config.SYNOPTIC_PRECIP_DRY_MM,
                "has_ts": any(int(r.get("weather_code") or 0) in (95, 96, 99)
                              for _, r in recs),
                "max_wc": max((int(r.get("weather_code") or 0)) for _, r in recs),
                "max_cape": max((r.get("cape") or 0) for _, r in recs),
            })
            covs = [r.get("precipitation_coverage") for _, r in recs
                    if r.get("precipitation_coverage") is not None]
            if covs:
                cov_by_zone[zone].append(max(covs))

            # Fenster-Aggregate
            for wname, h_lo, h_hi in windows:
                wrecs = [(h, r) for h, r in recs if h_lo <= h < h_hi]
                if not wrecs:
                    continue
                wprecs = [(r.get("precipitation") or 0) for _, r in wrecs]
                win_buckets[zone][wname].append({
                    "peak_mm": max(wprecs),
                    "wet": max(wprecs) >= wet_mm,
                    "has_ts": any(int(r.get("weather_code") or 0) in (95, 96, 99)
                                  for _, r in wrecs),
                    "max_wc": max((int(r.get("weather_code") or 0)) for _, r in wrecs),
                    "max_cape": max((r.get("cape") or 0) for _, r in wrecs),
                })

        for zone in config.SYNOPTIC_ZONES:
            day_agg = _aggregate_precip_bucket(day_buckets[zone])
            day_agg["max_coverage"] = (round(max(cov_by_zone[zone]), 2)
                                       if cov_by_zone[zone] else None)
            zones_out[zone] = {
                "day": day_agg,
                "windows": {w[0]: _aggregate_precip_bucket(win_buckets[zone][w[0]])
                            for w in windows},
            }

        per_day.append({"date": date, "zones": zones_out})

    return {
        "per_day": per_day,
        "windows": [{"key": w[0], "hours": [w[1], w[2]]} for w in windows],
        "n_spots_by_zone": {z: sum(1 for v in zone_map.values() if v == z)
                            for z in config.SYNOPTIC_ZONES},
        "decided_by": "decide_precip_pattern_zones",
        "thresholds": {"dry_mm": config.SYNOPTIC_PRECIP_DRY_MM,
                       "window_wet_mm": wet_mm},
    }


def _spot_day_wind_hours(spot: dict, date: str) -> dict[int, dict]:
    """Stuendliche Flugband-/Boeen-Werte eines Spots am Tag (6-20 lokal).

    Returns {hour: {"aloft": kmh|None, "gust": kmh|None}} — Basis fuer
    Fenster-Aggregate; die Tages-Klassifikation (wind_class) nutzt weiterhin
    _spot_day_wind (Kernstunden), damit die Semantik zu den Nord/Sued-
    Aggregaten identisch bleibt.
    """
    elev = spot.get("elevation_m")
    out: dict[int, dict] = {}
    if elev is None:
        return out
    band_lo = elev + config.SYNOPTIC_WIND_BAND_LOWER_M
    band_hi = elev + config.SYNOPTIC_WIND_BAND_UPPER_M

    for t, rec in (spot.get("pressure_level_data") or {}).items():
        if not t.startswith(date):
            continue
        try:
            hour = int(t[11:13])
        except (ValueError, IndexError):
            continue
        if not (6 <= hour <= 20):
            continue
        aloft = None
        for lvl in _WIND_PL_LEVELS:
            gh = rec.get(f"geopotential_height_{lvl}hPa")
            ws = rec.get(f"wind_speed_{lvl}hPa")
            if gh is None or ws is None:
                continue
            if band_lo <= gh <= band_hi and (aloft is None or ws > aloft):
                aloft = ws
        if aloft is not None:
            out.setdefault(hour, {})["aloft"] = aloft

    for t, rec in (spot.get("hourly_data") or {}).items():
        if not t.startswith(date):
            continue
        try:
            hour = int(t[11:13])
        except (ValueError, IndexError):
            continue
        if not (6 <= hour <= 20):
            continue
        g = rec.get("wind_gusts_10m")
        if g is not None:
            out.setdefault(hour, {})["gust"] = g
    return out


def decide_wind_pattern_zones(weather_cache: dict, forecast_dates: list[str],
                              zone_map: dict[str, str]) -> dict:
    """Wind-Fliegbarkeit pro Tag und Zone + share_wind_crit pro Tagesfenster.

    Tages-Kennzahlen (wind_class, shares, Verteilungen) identisch zur
    Nord/Sued-Aggregation (_aggregate_wind_side, Kernstunden 10-17) —
    nur der Raumschnitt aendert sich auf die 4 Zonen. Zusaetzlich pro
    Tagesfenster der Anteil windkritischer Spots UND die Boeenwerte (P90 +
    Maximum), damit der Text Wind-Zeitfenster nicht nur benennen, sondern
    beziffern kann ("am Nachmittag frischt es auf" vs. "abends Boeen um
    90 km/h").

    Zum Abendfenster: es faellt bewusst ausserhalb SYNOPTIC_WIND_HOURS und
    damit ausserhalb von `wind_class`. Das ist kein Fehler — die Tagesklasse
    bewertet den Flugtag, und der endet um 17 Uhr. Ein Abendereignis darf ihn
    nicht umetikettieren; es ist eine eigene, zeitlich benannte Aussage.
    """
    windows = config.SYNOPTIC_DAY_WINDOWS
    per_day = []

    for date in forecast_dates:
        day_entries = {z: [] for z in config.SYNOPTIC_ZONES}
        win_entries = {z: {w[0]: [] for w in windows} for z in config.SYNOPTIC_ZONES}

        for spot_name, zone in zone_map.items():
            spot = weather_cache.get(spot_name)
            if not spot:
                continue
            w = _spot_day_wind(spot, date)
            if w is not None:
                day_entries[zone].append(w)
            hours = _spot_day_wind_hours(spot, date)
            if not hours:
                continue
            for wname, h_lo, h_hi in windows:
                vals = [v for h, v in hours.items() if h_lo <= h < h_hi]
                if not vals:
                    continue
                alofts = [v["aloft"] for v in vals if v.get("aloft") is not None]
                gusts = [v["gust"] for v in vals if v.get("gust") is not None]
                if not alofts and not gusts:
                    continue
                win_entries[zone][wname].append({
                    "aloft_max": max(alofts) if alofts else None,
                    "gust_max": max(gusts) if gusts else None,
                })

        zones_out = {}
        for zone in config.SYNOPTIC_ZONES:
            agg = _aggregate_wind_side(day_entries[zone])
            win_out = {}
            for wname, _, _ in windows:
                entries = win_entries[zone][wname]
                if not entries:
                    win_out[wname] = {"share_wind_crit": None,
                                      "p90_gust_kmh": None, "max_gust_kmh": None}
                    continue
                crit = sum(
                    1 for e in entries
                    if (e["aloft_max"] is not None
                        and e["aloft_max"] > config.WIND_DANGER_KMH)
                    or (e["gust_max"] is not None
                        and e["gust_max"] > config.GUST_DANGER_KMH))
                # Boeen- UND Flugbandwerte je Fenster. Der Anteil allein sagt,
                # WIE VIELE Gebiete betroffen sind, nicht WIE STARK — bei der
                # Boeenfront vom 30.07.2026 war genau die Zahl das Alarmierende
                # (bis 100 km/h), und sie stand nirgends. P90 wie beim
                # Niederschlag: das Maximum ueber viele Spots ist regelmaessig
                # ein Einzelspot-Artefakt, P90 traegt das Bild.
                gusts = [e["gust_max"] for e in entries
                         if e["gust_max"] is not None]
                alofts = [e["aloft_max"] for e in entries
                          if e["aloft_max"] is not None]
                p90_gust = round(_p90(gusts), 1) if gusts else None
                p90_aloft = round(_p90(alofts), 1) if alofts else None
                win_out[wname] = {
                    "share_wind_crit": round(crit / len(entries), 2),
                    "p90_gust_kmh": p90_gust,
                    "max_gust_kmh": round(max(gusts), 1) if gusts else None,
                    "p90_aloft_kmh": p90_aloft,
                    "max_aloft_kmh": round(max(alofts), 1) if alofts else None,
                    # Verhaeltnis Boden zu Hoehe — die Frage "rauscht der Wind
                    # oben durch, oder kommt er unten an?". Fuer Piloten der
                    # Unterschied zwischen fliegbar und nicht: 45 km/h im
                    # Flugband bei ruhigem Boden ist ein anderer Tag als
                    # dieselben 45 km/h, die bis zum Boden durchgreifen.
                    #
                    # BEWUSST NUR DIE ZAHL, KEIN LABEL: ein hoher Wert kann
                    # auch aus lokaler Konvektion kommen (Boe ohne
                    # Impulstransport von oben). Die Deutung gehoert in den
                    # Text, nicht in eine Schwelle, die wir nie gemessen haben.
                    # Boeen sind Spitzen, Flugbandwind ist ein Mittel — Werte
                    # ueber 1.0 sind daher moeglich und kein Fehler.
                    "bodenkopplung": (round(p90_gust / p90_aloft, 2)
                                      if p90_gust and p90_aloft else None),
                }
            agg["windows"] = win_out
            zones_out[zone] = agg

        per_day.append({"date": date, "zones": zones_out})

    return {
        "per_day": per_day,
        "decided_by": "decide_wind_pattern_zones",
        "thresholds": {
            "wind_warn_kmh": config.WIND_WARN_KMH,
            "wind_danger_kmh": config.WIND_DANGER_KMH,
            "gust_warn_kmh": config.GUST_WARN_KMH,
            "gust_danger_kmh": config.GUST_DANGER_KMH,
            "band_above_spot_m": [config.SYNOPTIC_WIND_BAND_LOWER_M,
                                  config.SYNOPTIC_WIND_BAND_UPPER_M],
            "hours": list(config.SYNOPTIC_WIND_HOURS),
        },
    }


def decide_zugbahn(weather_cache: dict, forecast_dates: list[str],
                   zone_map: dict[str, str]) -> dict:
    """Zugbahn-Detektor: misst pro Tag die Niederschlags-Einsetz-Zeit pro
    Zonen-Gruppe und leitet daraus die Verlagerungsrichtung ab.

    Gruppen: die 4 Zonen, wobei der Alpennordhang fuer die Messung intern
    in West/Ost geteilt wird (Split-Laenge SYNOPTIC_ZUGBAHN_WEST_OST_SPLIT_LON)
    — NUR Diagnose, keine Erzaehl-Einheit.

    onset = erste Stunde (6-20 lokal), in der der Anteil Spots mit
    >= WINDOW_WET_MM Niederschlag die ONSET_SHARE erreicht. Richtung nur
    bei >= MIN_DIFF_H Stunden Versatz ("west_nach_ost" etc.), sonst
    "gleichzeitig"; null wenn hoechstens eine Gruppe anspringt.
    """
    split_lon = config.SYNOPTIC_ZUGBAHN_WEST_OST_SPLIT_LON
    wet_mm = config.SYNOPTIC_PRECIP_WINDOW_WET_MM
    onset_share = config.SYNOPTIC_ZUGBAHN_ONSET_SHARE
    min_spots = config.SYNOPTIC_ZUGBAHN_MIN_SPOTS
    min_diff = config.SYNOPTIC_ZUGBAHN_MIN_DIFF_H

    # Gruppen-Zuordnung einmalig
    group_of: dict[str, str] = {}
    for spot_name, zone in zone_map.items():
        if zone == "alpennordhang":
            spot = weather_cache.get(spot_name) or {}
            lon = spot.get("longitude")
            if lon is None:
                continue
            group_of[spot_name] = ("alpennordhang_west" if lon < split_lon
                                   else "alpennordhang_ost")
        else:
            group_of[spot_name] = zone
    groups = sorted({g for g in group_of.values()})

    per_day = []
    for date in forecast_dates:
        # pro Gruppe: {hour: [n_wet, n_total]}
        counts: dict[str, dict[int, list[int]]] = {g: {} for g in groups}
        for spot_name, group in group_of.items():
            hd = (weather_cache.get(spot_name) or {}).get("hourly_data") or {}
            for t, rec in hd.items():
                if not t.startswith(date):
                    continue
                try:
                    hour = int(t[11:13])
                except (ValueError, IndexError):
                    continue
                if not (6 <= hour <= 20):
                    continue
                c = counts[group].setdefault(hour, [0, 0])
                c[1] += 1
                if (rec.get("precipitation") or 0) >= wet_mm:
                    c[0] += 1

        onset_by_group: dict[str, Optional[int]] = {}
        for g in groups:
            onset = None
            for hour in sorted(counts[g]):
                n_wet, n_tot = counts[g][hour]
                if n_tot >= min_spots and n_wet / n_tot >= onset_share:
                    onset = hour
                    break
            onset_by_group[g] = onset

        # Richtungs-Ableitung West<->Ost (Nordhang) und Sued<->Nord
        def _dir(a: Optional[int], b: Optional[int],
                 label_ab: str, label_ba: str) -> Optional[str]:
            if a is None or b is None:
                return None
            if b - a >= min_diff:
                return label_ab
            if a - b >= min_diff:
                return label_ba
            return "gleichzeitig"

        west = onset_by_group.get("alpennordhang_west")
        ost = onset_by_group.get("alpennordhang_ost")
        nord_onsets = [o for o in (west, ost) if o is not None]
        nord = min(nord_onsets) if nord_onsets else None
        sued_onsets = [onset_by_group.get("tessin"), onset_by_group.get("wallis")]
        sued_onsets = [o for o in sued_onsets if o is not None]
        sued = min(sued_onsets) if sued_onsets else None

        per_day.append({
            "date": date,
            "onset_hour_by_group": onset_by_group,
            "movement": {
                "west_ost": _dir(west, ost, "west_nach_ost", "ost_nach_west"),
                "sued_nord": _dir(sued, nord, "sued_nach_nord", "nord_nach_sued"),
            },
        })

    return {
        "per_day": per_day,
        "decided_by": "decide_zugbahn",
        "thresholds": {"onset_share": onset_share, "wet_mm": wet_mm,
                       "min_spots": min_spots, "min_diff_h": min_diff,
                       "west_ost_split_lon": split_lon},
    }


def decide_schneefallgrenze(snapshots: list[dict],
                            today_month: int) -> Optional[dict]:
    """Schneefallgrenze pro Tag, nur im saisonalen Fenster (Maerz-Mai + Okt-Nov).

    Formel: SSG = gh850 + (T850_c - 1) / 0.0065
    (Schneefall typisch bei +1 °C am Boden, lapse rate 6.5 K/km)
    """
    if today_month not in config.SYNOPTIC_SNOWLINE_MONTHS:
        return None

    per_day = []
    for s in snapshots:
        t850 = s.get("t850_c")
        gh850 = s.get("gh850_m")
        if t850 is None or gh850 is None:
            per_day.append({"date": s["date"], "ssg_m": None})
            continue
        ssg = gh850 + (t850 - 1) / 0.0065
        # Auf 100m runden, plausibel-clip
        ssg_m = round(ssg / 100) * 100
        ssg_m = max(0, min(5000, ssg_m))
        per_day.append({"date": s["date"], "ssg_m": int(ssg_m)})

    valid = [d["ssg_m"] for d in per_day if d["ssg_m"] is not None]
    if not valid:
        return None

    avg = round(statistics.mean(valid) / 100) * 100
    return {
        "value": int(avg),
        "per_day": per_day,
        "decided_by": "decide_schneefallgrenze",
        "inputs": {"month": today_month},
        "thresholds": {
            "season_months": list(config.SYNOPTIC_SNOWLINE_MONTHS),
            "lapse_rate_k_per_m": 0.0065,
            "snow_threshold_c": 1.0,
        },
    }


def decide_confidence_per_day(day_count: int) -> list[str]:
    """Konfidenz-Decay je Forecast-Tag aus config.SYNOPTIC_CONFIDENCE_BY_DAY."""
    return [
        config.SYNOPTIC_CONFIDENCE_BY_DAY.get(i, "low")
        for i in range(day_count)
    ]


# ============================================================================
# HELFER
# ============================================================================

def _wind_direction_to_sector(dir_deg: float) -> str:
    """Mappt Windrichtung in Grad auf einen Pilotenkompass-Sektor."""
    d = dir_deg % 360
    for low, high, name in config.SYNOPTIC_FLOW_SECTORS:
        if low > high:  # Wrap-Around bei Nord (337.5 -> 22.5)
            if d >= low or d < high:
                return name
        else:
            if low <= d < high:
                return name
    return "Nord"


def _flow_strength(speed_kmh: float) -> str:
    """Stuerkeklasse fuer 700hPa-Wind."""
    if speed_kmh < config.SYNOPTIC_FLOW_SCHWACH_KMH:
        return "schwach"
    if speed_kmh < config.SYNOPTIC_FLOW_MAESSIG_KMH:
        return "maessig"
    if speed_kmh < config.SYNOPTIC_FLOW_KRAEFTIG_KMH:
        return "kraeftig"
    return "stuermisch"
