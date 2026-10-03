"""
Föhn-Talpunkte — eigene Punkt-Ebene neben den Regions-Referenzpunkten.

Ein Punkt pro Föhntal mit amtlicher Wahrheit (SwissMetNet-Föhnindex).
Startlage ist die Station selbst, damit Modellwert und Messung am selben
Ort verglichen werden. Die Punkte fliessen (noch) in keine Bewertung ein;
sie sind die Grundlage für einen Modell-Föhnindex pro Tal.

Herleitung der Täler: meteo_research/foehn_valley_forecasting.md §3.2.
"""

import json

import config


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
