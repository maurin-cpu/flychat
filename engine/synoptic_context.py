"""Synoptik-Kontext fuer den Wetterlage-Block im Wochencast und in der E-Mail.

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
    forecast_dates = _extract_forecast_dates(weather_cache, max_days=5)
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

    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "forecast_dates": forecast_dates,
        "lage_label": lage_label,
        "pressure_influence": pressure_influence,
        "flow_overhead": flow_overhead,
        "t850_trend": t850_trend,
        "pressure_centers_per_day": pressure_centers_per_day,
        "bise": bise,
        "vb_lage": vb_lage,
        "foehn": foehn,
        "precip_pattern": precip,
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

    Wird von Web-Layer (Wochencast/Email) verwendet, um den fertig
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

    Pro Tag: Stunden 10-16 lokal pruefen, aktiv wenn mind. 2h caution+ in
    Sued- oder Nord-Richtung.

    Bei API-Fehler: liefert active=False mit source="fetch_failed", damit
    der Synoptik-Block nicht komplett ausfaellt.
    """
    from foehn_indicators import (
        fetch_foehn_data, evaluate_foehn,
        THRESHOLD_DELTA_P_CAUTION, THRESHOLD_DELTA_P_DANGER,
    )

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
                "active_min_hours": 2,
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
            if t.startswith(date) and 10 <= int(t[11:13]) <= 16
        ]
        sued_hours = 0
        nord_hours = 0
        peak_sued = "none"
        peak_nord = "none"
        for i in day_indices:
            ev_sued = evaluate_foehn(data["nord"], data["sued"], i,
                                     kritischer_foehn="Süd")
            ev_nord = evaluate_foehn(data["nord"], data["sued"], i,
                                     kritischer_foehn="Nord")
            if ev_sued.get("level", "none") != "none":
                sued_hours += 1
                peak_sued = _peak(peak_sued, ev_sued["level"])
            if ev_nord.get("level", "none") != "none":
                nord_hours += 1
                peak_nord = _peak(peak_nord, ev_nord["level"])
        sued_active = sued_hours >= 2
        nord_active = nord_hours >= 2
        per_day.append({
            "date": date,
            "sued_active": sued_active,
            "nord_active": nord_active,
            "peak_sued": peak_sued,
            "peak_nord": peak_nord,
            "sued_hours": sued_hours,
            "nord_hours": nord_hours,
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
            "active_min_hours": 2,
            "day_hours_checked": [10, 16],
        },
    }


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

    # 2. Vb-Lage
    if vb_lage and vb_lage.get("active_any_day"):
        return {
            "value": "Vb-/Genua-Tief",
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
        # Mapping Sektor -> Lage-Begriff in Pilotensprache
        sector_to_lage = {
            "West": "Westlage",
            "Suedwest": "Suedwestlage",
            "Nordwest": "Nordwestlage",
            "Nord": "Nordlage",
            "Nordost": "Nordostlage",
            "Ost": "Ostlage",
            "Suedost": "Suedostlage",
            "Sued": "Suedlage",
        }
        lage = sector_to_lage.get(flow_sector, f"{flow_sector}lage")
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


def _aggregate_precip_side(spots_day: list[dict]) -> dict:
    """Aggregiert Niederschlagscharakter ueber Spots einer Seite und eines Tages."""
    if not spots_day:
        return {"value": "unbekannt", "n_spots": 0}
    peaks = [s["peak_mm"] for s in spots_day]
    totals = [s["total_mm"] for s in spots_day]
    capes = [s["max_cape"] for s in spots_day]
    wcs = [s["max_wc"] for s in spots_day]
    coverages = [s["max_coverage"] for s in spots_day if s["max_coverage"] is not None]

    peak_max = max(peaks)
    nass_anteil = sum(1 for t in totals if t >= config.SYNOPTIC_PRECIP_DRY_MM) / len(totals)
    cape_max = max(capes)
    wc_max = max(wcs)
    coverage_max = max(coverages) if coverages else None

    # Charakter-Klassifikation
    if peak_max < config.SYNOPTIC_PRECIP_DRY_MM:
        char = "trocken"
    elif wc_max >= 95:  # WMO 95/96/99 = Gewitter
        char = "Gewitter"
    elif cape_max >= config.SYNOPTIC_PRECIP_CAPE_GEWITTER and peak_max >= 2.0:
        char = "Gewitter wahrscheinlich"
    elif (coverage_max is not None
          and coverage_max >= config.SYNOPTIC_PRECIP_COVERAGE_FLAECHIG
          and nass_anteil >= 0.5):
        if peak_max >= config.SYNOPTIC_PRECIP_MODERATE_MM:
            char = "flaechiger starker Regen"
        else:
            char = "flaechiger Regen"
    elif (cape_max >= config.SYNOPTIC_PRECIP_CAPE_KONVEKTIV
          and (coverage_max is None or coverage_max < config.SYNOPTIC_PRECIP_COVERAGE_FLAECHIG)):
        char = "Schauer"
    elif peak_max >= config.SYNOPTIC_PRECIP_MODERATE_MM:
        char = "maessiger Regen"
    elif peak_max >= config.SYNOPTIC_PRECIP_LIGHT_MM:
        char = "leichter Regen"
    else:
        char = "Spuren"

    return {
        "value": char,
        "n_spots": len(spots_day),
        "peak_mm": round(peak_max, 1),
        "wet_share": round(nass_anteil, 2),
        "max_cape": round(cape_max, 0) if cape_max else 0,
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
            covs = [r.get("precipitation_coverage") for r in day_recs
                    if r.get("precipitation_coverage") is not None]
            max_cov = max(covs) if covs else None
            entry = {
                "peak_mm": peak,
                "total_mm": total,
                "max_cape": max_cape,
                "max_wc": max_wc,
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
        "thresholds": {
            "dry_mm": config.SYNOPTIC_PRECIP_DRY_MM,
            "light_mm": config.SYNOPTIC_PRECIP_LIGHT_MM,
            "moderate_mm": config.SYNOPTIC_PRECIP_MODERATE_MM,
            "coverage_flaechig": config.SYNOPTIC_PRECIP_COVERAGE_FLAECHIG,
            "cape_konvektiv": config.SYNOPTIC_PRECIP_CAPE_KONVEKTIV,
            "cape_gewitter": config.SYNOPTIC_PRECIP_CAPE_GEWITTER,
        },
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
