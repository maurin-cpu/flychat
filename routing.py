"""
Routing- und Geocoding-Modul für Gleitcast (Phase 1).

Stellt drei Funktionen für den Chat-Tool-Use bereit:
- geocode(query): Adresse → lat/lon (Nominatim)
- isochrone(lat, lon, minutes, mode): Erreichbare Zone (Valhalla)
- spots_in_polygon(polygon, spots): Welche Spots liegen drin (shapely)

Bei Ausfall der externen Services wird `RoutingError` geworfen — KEIN Fallback.
"""

import logging
import time
from typing import Optional

import requests

import config

logger = logging.getLogger(__name__)


# ============================================================================
# EXCEPTIONS
# ============================================================================

class RoutingError(Exception):
    """Routing-Service (Valhalla / Nominatim) ist nicht erreichbar oder lieferte
    eine ungültige Antwort. Wird vom Chat-Engine in eine ehrliche Fehlermeldung
    übersetzt — kein Fallback auf Haversine-Kreise oder OSRM."""
    pass


# ============================================================================
# GEOCODE-CACHE (in-memory, 24h)
# ============================================================================
# Nominatim erlaubt nur 1 Request/Sekunde + verlangt korrekten User-Agent.
# Caching ist Pflicht für freundliche Nutzung.

_GEOCODE_CACHE: dict = {}  # key -> (timestamp, result)
_LAST_NOMINATIM_REQUEST: float = 0.0


def _cache_get(key: str):
    entry = _GEOCODE_CACHE.get(key)
    if not entry:
        return None
    ts, value = entry
    if time.time() - ts > config.GEOCODE_CACHE_TTL:
        _GEOCODE_CACHE.pop(key, None)
        return None
    return value


def _cache_put(key: str, value):
    _GEOCODE_CACHE[key] = (time.time(), value)


def _throttle_nominatim():
    """Stelle sicher, dass mindestens 1 Sekunde zwischen Nominatim-Calls liegt."""
    global _LAST_NOMINATIM_REQUEST
    elapsed = time.time() - _LAST_NOMINATIM_REQUEST
    if elapsed < 1.05:
        time.sleep(1.05 - elapsed)
    _LAST_NOMINATIM_REQUEST = time.time()


# ============================================================================
# GEOCODING (Nominatim)
# ============================================================================

def geocode(query: str, lang: str = "de") -> Optional[dict]:
    """Geokodiert eine Adresse / Ortsangabe via Nominatim.

    Args:
        query: Free-text query, z.B. "Zürich" oder "Bahnhofstrasse 1, Bern".
        lang: Sprache der Antwort (Display-Name).

    Returns:
        Dict {lat, lon, display_name} oder None wenn nichts gefunden wurde.

    Raises:
        RoutingError: Wenn Nominatim nicht erreichbar ist oder einen HTTP-Fehler liefert.
    """
    if not query or not query.strip():
        return None

    cache_key = f"{lang}::{query.strip().lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.debug(f"geocode cache hit: {query}")
        return cached

    _throttle_nominatim()

    url = f"{config.NOMINATIM_URL}/search"
    params = {
        "q": query.strip(),
        "format": "json",
        "limit": 1,
        "accept-language": lang,
        "addressdetails": 0,
    }
    headers = {
        "User-Agent": config.ROUTING_USER_AGENT,
        "Accept": "application/json",
    }

    try:
        resp = requests.get(
            url, params=params, headers=headers, timeout=config.ROUTING_TIMEOUT
        )
    except requests.exceptions.RequestException as e:
        logger.error(f"Nominatim request failed: {e}")
        raise RoutingError(f"Nominatim nicht erreichbar: {e}") from e

    if resp.status_code != 200:
        logger.error(f"Nominatim HTTP {resp.status_code}: {resp.text[:200]}")
        raise RoutingError(f"Nominatim HTTP {resp.status_code}")

    try:
        items = resp.json()
    except ValueError as e:
        raise RoutingError(f"Nominatim ungültige JSON-Antwort: {e}") from e

    if not items:
        _cache_put(cache_key, None)
        return None

    first = items[0]
    try:
        result = {
            "lat": float(first["lat"]),
            "lon": float(first["lon"]),
            "display_name": first.get("display_name", query),
        }
    except (KeyError, ValueError) as e:
        raise RoutingError(f"Nominatim Antwort unvollständig: {e}") from e

    _cache_put(cache_key, result)
    return result


# ============================================================================
# ISOCHRONE (Valhalla)
# ============================================================================

_VALID_COSTING = {"auto", "bicycle", "pedestrian"}


def isochrone(lat: float, lon: float, minutes: int, mode: str = "auto") -> dict:
    """Berechnet eine Isochrone (erreichbare Zone) via Valhalla.

    Args:
        lat: Origin Latitude (WGS84).
        lon: Origin Longitude (WGS84).
        minutes: Gewünschte Reisezeit in Minuten (1-360).
        mode: Verkehrsmittel — "auto", "bicycle" oder "pedestrian".

    Returns:
        GeoJSON FeatureCollection mit (i.d.R.) genau einem Polygon-Feature.
        Format kompatibel mit Leaflet L.geoJSON().

    Raises:
        RoutingError: Wenn Valhalla nicht erreichbar ist, ein HTTP-Fehler kommt
            oder die Antwort kein verwertbares Polygon enthält.
        ValueError: Wenn Argumente ungültig sind (sofortige Validierung).
    """
    if mode not in _VALID_COSTING:
        raise ValueError(f"Unbekannter Modus '{mode}', erlaubt: {sorted(_VALID_COSTING)}")
    if not (1 <= minutes <= 360):
        raise ValueError(f"minutes muss zwischen 1 und 360 liegen, war {minutes}")
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise ValueError(f"Ungültige Koordinaten: ({lat}, {lon})")

    url = f"{config.VALHALLA_URL.rstrip('/')}/isochrone"
    payload = {
        "locations": [{"lat": lat, "lon": lon}],
        "costing": mode,
        "contours": [{"time": minutes, "color": "4f46e5"}],
        "polygons": True,
        "denoise": 0.5,
        "generalize": 50,
        "id": "gleitcast",
    }
    headers = {
        "User-Agent": config.ROUTING_USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        resp = requests.post(
            url, json=payload, headers=headers, timeout=config.ROUTING_TIMEOUT
        )
    except requests.exceptions.RequestException as e:
        logger.error(f"Valhalla isochrone request failed: {e}")
        raise RoutingError(f"Valhalla nicht erreichbar: {e}") from e

    if resp.status_code != 200:
        logger.error(f"Valhalla HTTP {resp.status_code}: {resp.text[:200]}")
        raise RoutingError(f"Valhalla HTTP {resp.status_code}")

    try:
        data = resp.json()
    except ValueError as e:
        raise RoutingError(f"Valhalla ungültige JSON-Antwort: {e}") from e

    if not isinstance(data, dict) or "features" not in data:
        raise RoutingError("Valhalla Antwort ohne 'features' Feld")

    features = data.get("features") or []
    if not features:
        raise RoutingError("Valhalla Antwort ohne Polygone")

    # Sicherstellen, dass es eine FeatureCollection ist (Valhalla liefert das normalerweise so).
    if data.get("type") != "FeatureCollection":
        data = {"type": "FeatureCollection", "features": features}

    return data


# ============================================================================
# POINT-IN-POLYGON FILTER
# ============================================================================

def spots_in_polygon(polygon_geojson: dict, spots: list) -> list:
    """Filtert Spots, die innerhalb eines GeoJSON-Polygons liegen.

    Args:
        polygon_geojson: GeoJSON FeatureCollection oder Feature mit Polygon /
            MultiPolygon / GeometryCollection.
        spots: Liste von Spot-Dicts mit `latitude` + `longitude` Schlüsseln.

    Returns:
        Subset der spots-Liste, die innerhalb des Polygons liegen.
    """
    try:
        from shapely.geometry import shape, Point
        from shapely.ops import unary_union
    except ImportError as e:
        raise RoutingError(f"shapely fehlt: {e}") from e

    if not polygon_geojson or not spots:
        return []

    # Geometrien sammeln (FeatureCollection → einzelne Geometrien)
    geometries = []
    if polygon_geojson.get("type") == "FeatureCollection":
        for feat in polygon_geojson.get("features", []):
            geom = feat.get("geometry")
            if geom:
                geometries.append(geom)
    elif polygon_geojson.get("type") == "Feature":
        geom = polygon_geojson.get("geometry")
        if geom:
            geometries.append(geom)
    else:
        # Direkte Geometrie
        geometries.append(polygon_geojson)

    if not geometries:
        return []

    # Geometrien zu shapely-Objekten + ggf. Vereinigung
    shp_geoms = []
    for g in geometries:
        try:
            s = shape(g)
            if not s.is_valid:
                s = s.buffer(0)  # repair self-intersections
            shp_geoms.append(s)
        except Exception as e:
            logger.warning(f"Ungültige Geometrie übersprungen: {e}")
            continue

    if not shp_geoms:
        return []

    try:
        merged = unary_union(shp_geoms) if len(shp_geoms) > 1 else shp_geoms[0]
    except Exception as e:
        logger.warning(f"unary_union fehlgeschlagen: {e}")
        merged = shp_geoms[0]

    matched = []
    for spot in spots:
        lat = spot.get("latitude")
        lon = spot.get("longitude")
        if lat is None or lon is None:
            continue
        try:
            pt = Point(float(lon), float(lat))
        except (TypeError, ValueError):
            continue
        if merged.contains(pt) or merged.intersects(pt):
            matched.append(spot)

    return matched
