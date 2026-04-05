"""
Source-Area-Modul fuer Flychat.

Bestimmt die 5 Referenzpunkte pro Spot:
  Punkt 1 = Startplatz (immer)
  Punkte 2-5 = Regionale Referenzpunkte (aus GeoJSON oder SPOT_CONFIG)

Spots in der gleichen Region teilen die Punkte 2-5.
"""

import json
from shapely.geometry import shape, Point

import config

_regions_cache = None


def _load_regions():
    """Laedt regionen_referenzpunkte.geojson (einmalig, gecacht)."""
    global _regions_cache
    if _regions_cache is not None:
        return _regions_cache

    path = config.REGIONEN_GEOJSON_PATH
    if not path.exists():
        print(f"[WARN] Regionen-GeoJSON nicht gefunden: {path}")
        _regions_cache = []
        return _regions_cache

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    _regions_cache = []
    for feature in data.get("features", []):
        polygon = shape(feature["geometry"])
        props = feature["properties"]
        _regions_cache.append({
            "id": props["id"],
            "region": props["region"],
            "polygon": polygon,
            "reference_points": props.get("reference_points", []),
            "elevation_ref": props.get("elevation_ref"),
            "kritischer_foehn": props.get("kritischer_foehn", "Beide"),
        })

    print(f"[INFO] {len(_regions_cache)} Regionen geladen aus {path.name}")
    return _regions_cache


def find_region_for_point(lat, lon):
    """Findet die Region fuer einen Punkt via Point-in-Polygon."""
    regions = _load_regions()
    pt = Point(lon, lat)  # shapely: (x=lon, y=lat)
    for region in regions:
        if region["polygon"].contains(pt):
            return region
    return None


def get_reference_points(spot_name, lat, lon, quiet=False):
    """
    Gibt die 5 Referenzpunkte fuer einen Spot zurueck.
    [spot_coords, ref1, ref2, ref3, ref4]

    Prioritaet: SPOT_SOURCE_AREAS (Spot-Name) > GeoJSON (Region)
    """
    # 1. SPOT_CONFIG Override
    if hasattr(config, "SPOT_SOURCE_AREAS") and spot_name in config.SPOT_SOURCE_AREAS:
        custom_points = config.SPOT_SOURCE_AREAS[spot_name]
        if not quiet:
            print(f"  [INFO] {spot_name}: Nutze SPOT_CONFIG ({len(custom_points)} Punkte)")
        return [[lat, lon]] + custom_points

    # 2. GeoJSON Region-Lookup
    region = find_region_for_point(lat, lon)
    if region and region["reference_points"]:
        if not quiet:
            print(f"  [INFO] {spot_name}: Region '{region['region']}' ({len(region['reference_points'])} Ref-Punkte)")
        return [[lat, lon]] + region["reference_points"]

    # 3. Fehler - Spot muss einer Region zugeordnet sein
    if not quiet:
        print(f"  [WARN] {spot_name}: Keine Region gefunden fuer ({lat}, {lon}) - Fallback 3-Punkt-Raster")
    return [
        [lat, lon],
        [lat + 0.015, lon + 0.020],
        [lat - 0.015, lon + 0.020],
    ]


def get_region_name_for_spot(spot_name, lat, lon):
    """Gibt den Region-Namen fuer einen Spot zurueck (fuer Anzeige)."""
    region = find_region_for_point(lat, lon)
    return region["region"] if region else None


def get_all_regions():
    """Gibt die gecachte Liste aller Regionen zurueck (fuer Region-Analyse)."""
    return _load_regions()


def get_all_regions_geojson():
    """Gibt das vollstaendige Regionen-GeoJSON zurueck (fuer Karten-Overlay)."""
    path = config.REGIONEN_GEOJSON_PATH
    if not path.exists():
        return {"type": "FeatureCollection", "features": []}

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
