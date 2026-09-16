"""Ortssuche und Erreichbarkeit — routing.py (Nominatim/Valhalla) mit Luftlinien-Fallback.

Beide Dienste sind oeffentlich und koennen ausfallen oder drosseln; der Fallback
(Haversine-Radius) wird in der Antwort ausdruecklich genannt.
"""
from __future__ import annotations

from .screening import haversine_km


def geocode(query: str) -> dict | None:
    try:
        import routing
        return routing.geocode(query)
    except Exception:
        return None


def spots_within(lat: float, lon: float, minutes: int, mode: str, spots: list[dict],
                 radius_km: float | None = None) -> tuple[list[dict], str]:
    """(Treffer mit 'distance_km', Methode-Text). Isochrone zuerst, sonst Luftlinie."""
    hits: list[dict] = []
    method = ""
    if radius_km is None:
        try:
            import routing
            iso = routing.isochrone(lat, lon, minutes, mode)
            # routing.spots_in_polygon erwartet latitude/longitude-Keys
            shaped = [dict(s, latitude=s["lat"], longitude=s["lon"]) for s in spots]
            inside = routing.spots_in_polygon(iso, shaped)
            names = {s["name"] for s in inside}
            hits = [s for s in spots if s["name"] in names]
            method = f"Isochrone {minutes} min ({mode}, Valhalla)"
        except Exception as e:  # noqa: BLE001
            radius_km = _minutes_to_km(minutes, mode)
            method = f"Luftlinie {radius_km:.0f} km (Isochrone nicht verfuegbar: {type(e).__name__})"
    if radius_km is not None:
        hits = [s for s in spots if haversine_km(lat, lon, s["lat"], s["lon"]) <= radius_km]
        method = method or f"Luftlinie {radius_km:.0f} km"
    for s in hits:
        s["distance_km"] = round(haversine_km(lat, lon, s["lat"], s["lon"]), 1)
    hits.sort(key=lambda s: s["distance_km"])
    return hits, method


def _minutes_to_km(minutes: int, mode: str) -> float:
    # grobe Luftlinien-Naeherung: Auto ~55 km/h effektiv, Velo ~18, zu Fuss ~4
    kmh = {"auto": 55, "bicycle": 18, "pedestrian": 4}.get(mode, 55)
    return max(5.0, minutes / 60.0 * kmh * 0.7)
