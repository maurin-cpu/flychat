"""
Föhn-Talpunkte — eigene Punkt-Ebene neben den Regions-Referenzpunkten.

Ein Punkt pro Föhntal mit amtlicher Wahrheit (SwissMetNet-Föhnindex).
Startlage ist die Station selbst, damit Modellwert und Messung am selben
Ort verglichen werden. Die Punkte fliessen (noch) in keine Bewertung ein;
sie sind die Grundlage für einen Modell-Föhnindex pro Tal.

Herleitung der Täler: meteo_research/foehn_valley_forecasting.md §3.2.
"""

import json
import logging
from datetime import datetime
from typing import Optional

import requests

import config

logger = logging.getLogger(__name__)

_HOURLY = "wind_speed_10m,wind_direction_10m,wind_gusts_10m,relative_humidity_2m,temperature_2m"


def load_talpunkte() -> list[dict]:
    """Alle Talpunkte als flache Dicts: Properties + lat/lon."""
    path = config.FOEHN_TALPUNKTE_PATH
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for feature in data.get("features", []):
        lon, lat = feature["geometry"]["coordinates"]
        out.append({**feature.get("properties", {}), "lat": lat, "lon": lon})
    return out


def update_talpunkt(punkt_id: str, lat: float, lon: float) -> dict:
    """Verschiebt EINEN Talpunkt und schreibt die Datei atomar zurück.

    Raises: ValueError wenn die id fehlt, FileNotFoundError wenn die Datei fehlt.
    """
    path = config.FOEHN_TALPUNKTE_PATH
    if not path.exists():
        raise FileNotFoundError(f"Föhn-Talpunkte nicht gefunden: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for feature in data.get("features", []):
        props = feature.get("properties", {})
        if props.get("id") == punkt_id:
            feature["geometry"]["coordinates"] = [round(float(lon), 4), round(float(lat), 4)]
            config.atomic_write_json(path, data)
            return {**props, "lat": round(float(lat), 4), "lon": round(float(lon), 4)}
    raise ValueError(f"Föhn-Talpunkt nicht gefunden: {punkt_id}")


def fetch_talpunkt_wind(forecast_days: int = 5) -> Optional[dict]:
    """Stundenwind an allen Talpunkten (ein Open-Meteo-Call, ICON-CH2, lokale Zeit).

    Rückgabe: {"model", "fetched_at", "time": [...],
               "punkte": {id: {"meta": {Properties + lat/lon}, "hourly": {...}}}}
    `meta` wird mitgeschrieben, damit ein Archivtag auch nach späterem
    Verschieben eines Punkts im Admin nachvollziehbar bleibt. None bei Fehler.
    """
    punkte = load_talpunkte()
    if not punkte:
        return None
    model = config.SURFACE_SECONDARY_MODEL
    params = config.with_api_key({
        "latitude": ",".join(str(p["lat"]) for p in punkte),
        "longitude": ",".join(str(p["lon"]) for p in punkte),
        "hourly": _HOURLY,
        "models": model,
        "forecast_days": forecast_days,
        "timezone": config.TIMEZONE,
        "wind_speed_unit": "kmh",
    })
    try:
        resp = requests.get(config.API_URL, params=params, timeout=config.API_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("fetch_talpunkt_wind fehlgeschlagen: %s", e)
        return None
    if isinstance(data, dict):
        data = [data]
    if len(data) != len(punkte):
        logger.warning("fetch_talpunkt_wind: %d Antworten für %d Punkte", len(data), len(punkte))
        return None
    times = (data[0].get("hourly") or {}).get("time") or []
    out = {"model": model, "fetched_at": datetime.now().isoformat(timespec="seconds"),
           "time": times, "punkte": {}}
    for p, d in zip(punkte, data):
        h = d.get("hourly") or {}
        out["punkte"][p["id"]] = {
            "meta": p,
            "hourly": {k: h.get(k, []) for k in _HOURLY.split(",")},
        }
    return out


def tal_kurzname(tal: str) -> str:
    """Kurzname für Texte: 'Reusstal / Urnerland' → 'Reusstal',
    'Misox (unten)' → 'Misox', 'St. Galler Rheintal oben' → 'St. Galler Rheintal'.
    Einzige Quelle für Talnamen im Briefing — Validator und Satz nutzen sie beide."""
    name = (tal or "").split(" /")[0].split(" (")[0]
    for suffix in (" oben", " unten"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name.strip()


def tal_namen(tal_summary: dict) -> list:
    """Kurznamen der bestätigten Täler, nach Böenspitze absteigend, ohne Dubletten."""
    best = [t for t in (tal_summary or {}).get("taeler") or [] if t.get("bestaetigt")]
    out = []
    for t in sorted(best, key=lambda t: -(t.get("gust_max_kmh") or 0)):
        k = tal_kurzname(t.get("tal", ""))
        if k and k not in out:
            out.append(k)
    return out
