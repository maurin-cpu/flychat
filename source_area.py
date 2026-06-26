"""
Source-Area-Modul fuer Wingcast.

Bestimmt die Referenzpunkte pro Spot:
  Punkt 1     = Startplatz (immer)
  Punkte 2..N = Regionale Referenzpunkte (aus GeoJSON oder SPOT_CONFIG)

Standard: 7 regionale Referenzpunkte pro Region, CVT-verteilt im Polygon-
Innern (Apr 2026, vorher 4 Punkte am Rand via Greedy Max-Min-Distance).
Spots in der gleichen Region teilen die regionalen Punkte.

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
_active_geojson_path = None  # zuletzt geladener Pfad — fuer Cache-Invalidierung


def invalidate_cache():
    """Erzwingt Neulade von regionen.csv und regionen_referenzpunkte.geojson.
    Aufgerufen nach einem Admin-Save, damit Aenderungen sofort wirken."""
    global _regions_cache, _csv_props_cache, _active_geojson_path
    _regions_cache = None
    _csv_props_cache = None
    _active_geojson_path = None


def update_reference_points(region_id: str, new_points: list) -> None:
    """Schreibt 7 reference_points fuer EINE Region atomar zurueck ins GeoJSON.

    new_points: Liste aus 7 [lat, lon] Paaren.
    Andere Regionen + Polygon-Geometrie bleiben unveraendert.
    Cache wird danach invalidiert.

    Raises: ValueError wenn Region oder Punkte invalid, FileNotFoundError wenn File fehlt.
    """
    if not isinstance(new_points, list) or len(new_points) != 7:
        raise ValueError(f"Genau 7 Reference Points erwartet, bekommen: {len(new_points) if isinstance(new_points, list) else type(new_points).__name__}")
    cleaned = []
    for i, p in enumerate(new_points):
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            raise ValueError(f"Punkt {i} muss [lat, lon] sein, bekommen: {p!r}")
        try:
            lat = float(p[0]); lon = float(p[1])
        except (TypeError, ValueError):
            raise ValueError(f"Punkt {i} hat nicht-numerische Koordinaten: {p!r}")
        cleaned.append([lat, lon])

    path = _current_geojson_path()
    if not path.exists():
        raise FileNotFoundError(f"GeoJSON nicht gefunden: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    found = False
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        if str(props.get("id", "")).strip() == region_id.strip():
            props["reference_points"] = cleaned
            feature["properties"] = props
            found = True
            break
    if not found:
        raise ValueError(f"Region nicht gefunden im GeoJSON: {region_id}")

    config.atomic_write_json(path, data)
    invalidate_cache()


def _current_geojson_path():
    """Gibt den aktiven Pfad zurueck (CVT-7 oder Legacy-4 je nach Config).
    Wird dynamisch ausgewertet, damit ein Toggle ohne Restart greift —
    der Cache wird in _load_regions() automatisch invalidiert."""
    if getattr(config, "USE_LEGACY_REGION_REFPOINTS", False):
        legacy = getattr(config, "REGIONEN_GEOJSON_LEGACY_PATH", None)
        if legacy and legacy.exists():
            return legacy
        print("[WARN] USE_LEGACY_REGION_REFPOINTS=True aber Legacy-File fehlt — Fallback auf Default")
    return config.REGIONEN_GEOJSON_PATH


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
    Properties aus regionen.csv (CSV = Master). Gecacht — bei Wechsel des
    aktiven Pfads (Legacy-Toggle) wird der Cache automatisch invalidiert."""
    global _regions_cache, _active_geojson_path

    path = _current_geojson_path()
    if _regions_cache is not None and _active_geojson_path == path:
        return _regions_cache
    # Pfad hat sich geaendert (Legacy-Toggle) — Cache verwerfen
    _regions_cache = None
    _active_geojson_path = path

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
    Gibt die Referenzpunkte fuer einen Spot zurueck.
    Format: [spot_coords, ref1, ref2, ..., refN]
    Standard: 1 Spot + 7 regionale Referenzpunkte (Apr 2026).

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


_precip_refpoints_cache: dict[str, list] | None = None


def get_precip_reference_points() -> dict[str, list]:
    """Laedt die 16 dichten Niederschlags-Referenzpunkte pro Region.

    Returns: {region_id: [[lat, lon], ...]} — leer falls Datei fehlt.

    Wird in fetch_weather.py genutzt um Niederschlag mit dichterem Sampling
    zu aggregieren (Coverage-Klassifikation widespread/scattered/isolated).
    Die Datei wird via scripts/create_precip_refpoints.py generiert.
    """
    global _precip_refpoints_cache
    if _precip_refpoints_cache is not None:
        return _precip_refpoints_cache

    path = getattr(config, "REGIONEN_GEOJSON_PRECIP_PATH", None)
    if path is None or not path.exists():
        print(f"[WARN] Precip-Refpoint-Datei fehlt: {path} — Fallback auf 7 Haupt-RPs")
        _precip_refpoints_cache = {}
        return _precip_refpoints_cache

    with open(path, "r", encoding="utf-8") as f:
        geojson = json.load(f)

    out: dict[str, list] = {}
    for feature in geojson.get("features", []):
        rid = (feature.get("properties") or {}).get("id")
        pts = (feature.get("properties") or {}).get("reference_points", [])
        if rid and pts:
            out[rid] = pts

    _precip_refpoints_cache = out
    print(f"[INFO] {len(out)} Regionen × {len(next(iter(out.values()), []))} Precip-RPs geladen")
    return out


def get_all_regions_geojson():
    """Gibt das Regionen-GeoJSON zurueck, mit Properties aus der CSV gemerged.

    Geometrie kommt aus regionen_referenzpunkte.geojson, alle textuellen
    Properties (region, terrain_type, elevation_ref, kritischer_foehn,
    description) aus regionen.csv. Damit erhaelt das Frontend (Karte,
    Tooltips) immer die aktuellen CSV-Werte ohne separates Sync-Skript.
    """
    path = _current_geojson_path()
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
