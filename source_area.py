"""
Source-Area-Modul fuer Gleitcast.

Bestimmt die 5 Referenzpunkte pro Spot:
  Punkt 1 = Startplatz (immer)
  Punkte 2-5 = Regionale Referenzpunkte (aus GeoJSON oder SPOT_CONFIG)

Spots in der gleichen Region teilen die Punkte 2-5.

Datenquellen:
  - regionen.csv  → MASTER fuer textuelle Properties (region_name,
                    terrain_type, elevation_ref, kritischer_foehn,
                    description). Aenderungen hier wirken sich direkt auf
                    die ganze App aus.
  - regionen_referenzpunkte.geojson → Geometrie (Polygon) + reference_points.
                    Properties in diesem File werden ignoriert/ueberschrieben
                    (CSV ist Master).

Join-Key: `id` (muss in beiden Files identisch sein).
"""

import csv
import json
from shapely.geometry import shape, Point

import config

_regions_cache = None
_csv_props_cache = None


def _load_csv_properties():
    """Laedt regionen.csv und gibt {id: properties_dict} zurueck.

    CSV-Spalten -> Python-Keys:
      region_name      -> region
      terrain_type     -> terrain_type
      elevation_ref    -> elevation_ref (int)
      kritischer_foehn -> kritischer_foehn
      description      -> description
    """
    global _csv_props_cache
    if _csv_props_cache is not None:
        return _csv_props_cache

    path = config.REGIONEN_CSV_PATH
    if not path.exists():
        print(f"[WARN] regionen.csv nicht gefunden: {path}")
        _csv_props_cache = {}
        return _csv_props_cache

    result = {}
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rid = (row.get("id") or "").strip()
            if not rid:
                continue
            try:
                elev = int(row["elevation_ref"]) if row.get("elevation_ref") else None
            except (ValueError, TypeError):
                elev = None
            result[rid] = {
                "region": (row.get("region_name") or "").strip(),
                "terrain_type": (row.get("terrain_type") or "").strip(),
                "elevation_ref": elev,
                "kritischer_foehn": (row.get("kritischer_foehn") or "").strip() or "Beide",
                "description": (row.get("description") or "").strip(),
            }

    print(f"[INFO] {len(result)} Region-Properties geladen aus {path.name}")
    _csv_props_cache = result
    return _csv_props_cache


def _load_regions():
    """Laedt Regionen: Geometrie + reference_points aus GeoJSON, textuelle
    Properties aus regionen.csv (CSV = Master). Einmalig gecacht."""
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

    csv_props = _load_csv_properties()

    _regions_cache = []
    geojson_ids = set()
    for feature in data.get("features", []):
        polygon = shape(feature["geometry"])
        props = feature["properties"]
        rid = props["id"]
        geojson_ids.add(rid)

        cprops = csv_props.get(rid)
        if not cprops:
            # Fallback: wenn CSV den Eintrag (noch) nicht hat, GeoJSON-Werte
            # benutzen, damit die App nicht crasht. Sollte mittelfristig
            # immer aus der CSV kommen.
            print(f"[WARN] Region '{rid}' in GeoJSON aber nicht in CSV — Fallback auf GeoJSON-Properties")
            cprops = {}

        _regions_cache.append({
            "id": rid,
            "region": cprops.get("region") or props.get("region", rid),
            "polygon": polygon,
            "reference_points": props.get("reference_points", []),
            "elevation_ref": cprops.get("elevation_ref")
                if cprops.get("elevation_ref") is not None
                else props.get("elevation_ref"),
            "kritischer_foehn": cprops.get("kritischer_foehn")
                or props.get("kritischer_foehn", "Beide"),
            "terrain_type": cprops.get("terrain_type")
                or props.get("terrain_type"),
            "description": cprops.get("description")
                or props.get("description", ""),
        })

    csv_only = set(csv_props.keys()) - geojson_ids
    if csv_only:
        print(
            f"[WARN] {len(csv_only)} Region(en) in CSV aber nicht in GeoJSON "
            f"(keine Geometrie -> nicht auf Karte sichtbar): {sorted(csv_only)}"
        )

    print(
        f"[INFO] {len(_regions_cache)} Regionen geladen "
        f"(Geometrie aus {path.name}, Properties aus regionen.csv)"
    )
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
    """Gibt das Regionen-GeoJSON zurueck, mit Properties aus der CSV gemerged.

    Geometrie kommt aus regionen_referenzpunkte.geojson, alle textuellen
    Properties (region, terrain_type, elevation_ref, kritischer_foehn,
    description) aus regionen.csv. Damit erhaelt das Frontend (Karte,
    Tooltips) immer die aktuellen CSV-Werte ohne separates Sync-Skript.
    """
    path = config.REGIONEN_GEOJSON_PATH
    if not path.exists():
        return {"type": "FeatureCollection", "features": []}

    with open(path, "r", encoding="utf-8") as f:
        geojson = json.load(f)

    csv_props = _load_csv_properties()
    for feature in geojson.get("features", []):
        rid = (feature.get("properties") or {}).get("id")
        if rid and rid in csv_props:
            # CSV-Werte UEBERSCHREIBEN GeoJSON-Werte (CSV = Master).
            # reference_points und id bleiben aus dem GeoJSON erhalten.
            merged = {**(feature.get("properties") or {}), **csv_props[rid]}
            feature["properties"] = merged

    return geojson
