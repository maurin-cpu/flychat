"""
Erstellt regionen_referenzpunkte.geojson aus regionen_polygone_mapped.geojson.

Pro Region werden 4 Referenzpunkte innerhalb des Polygons berechnet,
die als Source-Area-Raster fuer die Wetter-Aggregation dienen.

Fuer Mittelland Ost werden die bewaehrten Balderen-Punkte uebernommen.
"""

import json
import sys
from pathlib import Path
from shapely.geometry import shape, Point
import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
INPUT_PATH = DATA_DIR / "regionen_polygone_mapped.geojson"
OUTPUT_PATH = DATA_DIR / "regionen_referenzpunkte.geojson"

MANUAL_REFERENCE_POINTS = {
    "mittelland_ost": [
        [47.4150, 8.5900],
        [47.2500, 8.7500],
        [47.4300, 8.4700],
        [47.1600, 8.6600],
    ],
}


def compute_reference_points(polygon, n=4):
    """
    Berechnet n Referenzpunkte innerhalb eines Polygons.

    Strategie: Bounding-Box in ein Raster aufteilen, Punkte die innerhalb
    des Polygons liegen auswaehlen, und die n am besten verteilten nehmen.
    """
    bounds = polygon.bounds  # (minx, miny, maxx, maxy)
    minx, miny, maxx, maxy = bounds
    centroid = polygon.centroid

    candidates = []

    # Erzeuge ein dichtes Raster innerhalb der Bounding-Box
    grid_size = 8
    for i in range(grid_size):
        for j in range(grid_size):
            x = minx + (maxx - minx) * (i + 0.5) / grid_size
            y = miny + (maxy - miny) * (j + 0.5) / grid_size
            pt = Point(x, y)
            if polygon.contains(pt):
                dist_to_centroid = pt.distance(centroid)
                candidates.append((x, y, dist_to_centroid))

    if len(candidates) < n:
        # Fallback: Centroid + leicht versetzte Punkte
        cx, cy = centroid.x, centroid.y
        dx = (maxx - minx) * 0.2
        dy = (maxy - miny) * 0.2
        return [
            [cy + dy, cx],
            [cy - dy, cx],
            [cy, cx + dx],
            [cy, cx - dx],
        ][:n]

    # Greedy-Auswahl: Maximiere minimale Distanz zwischen gewaehlten Punkten
    candidates.sort(key=lambda c: c[2], reverse=True)
    selected = [candidates[0]]  # Starte mit dem Punkt am weitesten vom Centroid
    remaining = candidates[1:]

    while len(selected) < n and remaining:
        best_idx = -1
        best_min_dist = -1
        for i, cand in enumerate(remaining):
            min_dist = min(
                ((cand[0] - s[0])**2 + (cand[1] - s[1])**2)**0.5
                for s in selected
            )
            if min_dist > best_min_dist:
                best_min_dist = min_dist
                best_idx = i
        if best_idx >= 0:
            selected.append(remaining.pop(best_idx))
        else:
            break

    # GeoJSON-Koordinaten sind [lon, lat], aber unsere ref_points sind [lat, lon]
    return [[round(pt[1], 4), round(pt[0], 4)] for pt in selected]


def main():
    if not INPUT_PATH.exists():
        print(f"[FEHLER] {INPUT_PATH} nicht gefunden")
        sys.exit(1)

    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        source = json.load(f)

    features_out = []

    for feature in source["features"]:
        region_id = feature["properties"]["id"]
        polygon = shape(feature["geometry"])

        if region_id in MANUAL_REFERENCE_POINTS:
            ref_points = MANUAL_REFERENCE_POINTS[region_id]
            print(f"  [OK] {region_id}: Manuelle Punkte ({len(ref_points)})")
        else:
            ref_points = compute_reference_points(polygon, n=4)
            print(f"  [OK] {region_id}: Berechnete Punkte ({len(ref_points)})")

        new_feature = {
            "type": "Feature",
            "geometry": feature["geometry"],
            "properties": {
                **feature["properties"],
                "reference_points": ref_points,
            },
        }
        features_out.append(new_feature)

    output = {"type": "FeatureCollection", "features": features_out}

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n[INFO] {len(features_out)} Regionen geschrieben: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
