"""
Erstellt regionen_referenzpunkte.geojson aus regionen_polygone_mapped.geojson.

Pro Region werden N=7 Referenzpunkte definiert: die 4 alten Edge-Punkte
(Greedy Max-Min-Distance) als Anker am Polygon-Rand + 3 neue Innen-Punkte,
die so platziert werden, dass sie den groesstmoeglichen Abstand zu den
4 Ankern UND zueinander haben (Farthest-Point-Sampling).

Hybrid-Strategie:
- Edge-Anker (4): erfassen Rand-Phaenomene (Talwinde an Haengen, Foehn-Strom)
- Innen-Punkte (3): erfassen Wolkenloecher, Konvektion, Tal-Mitten
- Zusammen: bessere Coverage als nur Edge oder nur Innen

Quelle der Edge-Anker: `regionen_referenzpunkte_legacy4.geojson` (die alten
4 Punkte, die sich bewaehrt haben).
Fuer Mittelland Ost werden die bewaehrten Balderen-Punkte uebernommen.
"""

import json
import math
import random
import sys
from pathlib import Path
from shapely.geometry import shape, Point, MultiPolygon, Polygon

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
INPUT_PATH = DATA_DIR / "regionen_polygone_mapped.geojson"
LEGACY_PATH = DATA_DIR / "regionen_referenzpunkte_legacy4.geojson"
OUTPUT_PATH = DATA_DIR / "regionen_referenzpunkte.geojson"

# Gesamtzahl Referenzpunkte pro Region (Edge-Anker + Innen-Ergaenzung).
N_TOTAL = 7
# Anzahl Innen-Punkte, die zusaetzlich zu den 4 Edge-Ankern platziert werden.
N_INNER = N_TOTAL - 4  # = 3

# Grid-Aufloesung fuer das Sampling innerhalb des Polygons.
GRID_RESOLUTION = 60

MANUAL_REFERENCE_POINTS = {
    "mittelland_ost": [
        [47.4150, 8.5900],
        [47.2500, 8.7500],
        [47.4300, 8.4700],
        [47.1600, 8.6600],
    ],
}


def _load_legacy_anchors():
    """Laedt die 4 Edge-Anker pro Region aus dem Legacy-File."""
    if not LEGACY_PATH.exists():
        print(f"[FEHLER] Legacy-File fehlt: {LEGACY_PATH}")
        sys.exit(1)
    with open(LEGACY_PATH, "r", encoding="utf-8") as f:
        legacy = json.load(f)
    anchors = {}
    for feature in legacy.get("features", []):
        rid = feature["properties"].get("id")
        if rid:
            anchors[rid] = feature["properties"].get("reference_points", [])
    return anchors


def _sample_polygon(polygon, resolution=GRID_RESOLUTION):
    """Erzeugt ein dichtes Grid-Sample (lon, lat) innerhalb des Polygons."""
    minx, miny, maxx, maxy = polygon.bounds
    samples = []
    for i in range(resolution):
        for j in range(resolution):
            x = minx + (maxx - minx) * (i + 0.5) / resolution
            y = miny + (maxy - miny) * (j + 0.5) / resolution
            if polygon.contains(Point(x, y)):
                samples.append((x, y))
    return samples


def _inner_polygon(polygon, inset_fraction=0.15):
    """Erzeugt durch negativen Buffer eine geschrumpfte Innen-Variante des
    Polygons. inset = inset_fraction * min(width, height). Falls der Buffer
    das Polygon kollabiert, wird der Inset iterativ reduziert.

    Returns: Polygon (oder MultiPolygon) im Innern. None wenn nicht moeglich.
    """
    minx, miny, maxx, maxy = polygon.bounds
    base_inset = min(maxx - minx, maxy - miny) * inset_fraction
    for factor in (1.0, 0.7, 0.5, 0.3, 0.15):
        inset = base_inset * factor
        shrunken = polygon.buffer(-inset)
        if not shrunken.is_empty and shrunken.area > 0:
            return shrunken
    return None


def _samples_in_geometry(geom, resolution=GRID_RESOLUTION):
    """Grid-Sample innerhalb einer beliebigen (Multi)Polygon-Geometrie."""
    minx, miny, maxx, maxy = geom.bounds
    samples = []
    for i in range(resolution):
        for j in range(resolution):
            x = minx + (maxx - minx) * (i + 0.5) / resolution
            y = miny + (maxy - miny) * (j + 0.5) / resolution
            if geom.contains(Point(x, y)):
                samples.append((x, y))
    return samples


def _kmeans_pp_init(samples, k, seed=42):
    """k-means++ Initialisierung: spreizt Start-Centroide gut."""
    rng = random.Random(seed)
    if not samples:
        return []
    centroids = [rng.choice(samples)]
    while len(centroids) < k:
        dists = [
            min((s[0] - c[0]) ** 2 + (s[1] - c[1]) ** 2 for c in centroids)
            for s in samples
        ]
        total = sum(dists)
        if total <= 0:
            centroids.append(rng.choice(samples))
            continue
        r = rng.random() * total
        cum = 0.0
        for s, d in zip(samples, dists):
            cum += d
            if cum >= r:
                centroids.append(s)
                break
    return centroids


def _lloyd_cvt(samples, k, iterations=40):
    """Lloyd-CVT: k Centroide gleichmaessig im Sample-Set verteilen."""
    if len(samples) < k:
        return samples[:k]
    centroids = _kmeans_pp_init(samples, k)
    for _ in range(iterations):
        clusters = [[] for _ in range(k)]
        for s in samples:
            best_i, best_d = 0, float("inf")
            for i, c in enumerate(centroids):
                d = (s[0] - c[0]) ** 2 + (s[1] - c[1]) ** 2
                if d < best_d:
                    best_d, best_i = d, i
            clusters[best_i].append(s)
        new_centroids = []
        moved = 0.0
        for i, cluster in enumerate(clusters):
            if not cluster:
                new_centroids.append(centroids[i])
                continue
            cx = sum(s[0] for s in cluster) / len(cluster)
            cy = sum(s[1] for s in cluster) / len(cluster)
            moved += math.hypot(cx - centroids[i][0], cy - centroids[i][1])
            new_centroids.append((cx, cy))
        centroids = new_centroids
        if moved < 1e-6:
            break
    return centroids


def compute_reference_points(polygon, region_id, anchors):
    """
    Berechnet die N_TOTAL Referenzpunkte fuer eine Region:
      - 4 Edge-Anker aus dem Legacy-File (unveraendert, bewaehrte alte Punkte)
      - N_INNER neue Innen-Punkte via CVT auf dem geschrumpften Innen-Polygon

    Strategie: das Polygon wird via negativem Buffer um ca. 15% der
    Bounding-Box-Kantenlaenge geschrumpft. Lloyd-CVT mit k=N_INNER auf
    dem Innen-Polygon platziert die neuen Punkte zwangslaeufig im Innern,
    nicht an den Raendern. Die Edge-Anker bleiben unangetastet.

    Returns: Liste [[lat, lon], ...] (Edge-Anker zuerst, dann Innen-Punkte)
    """
    edge_anchors = anchors.get(region_id, [])
    if not edge_anchors:
        print(f"  [WARN] {region_id}: keine Edge-Anker in Legacy-File")
        edge_anchors = []

    # Innen-Polygon erzeugen (negativer Buffer)
    inner_geom = _inner_polygon(polygon)
    if inner_geom is None:
        # Mini-Polygon-Fallback: Centroid + leicht versetzte Punkte
        centroid = polygon.centroid
        cx, cy = centroid.x, centroid.y
        bounds = polygon.bounds
        dx = (bounds[2] - bounds[0]) * 0.15
        dy = (bounds[3] - bounds[1]) * 0.15
        inner_xy = [(cx, cy), (cx + dx, cy + dy), (cx - dx, cy - dy)][:N_INNER]
    else:
        samples = _samples_in_geometry(inner_geom)
        if len(samples) < N_INNER:
            centroid = inner_geom.centroid
            cx, cy = centroid.x, centroid.y
            inner_xy = [(cx, cy)] * N_INNER  # alle auf Centroid wenn zu klein
        else:
            inner_xy = _lloyd_cvt(samples, N_INNER)

    # Reihenfolge: zuerst Edge-Anker (= alte 4 Punkte), dann Innen-Punkte
    result = list(edge_anchors)
    result.extend([[round(pt[1], 4), round(pt[0], 4)] for pt in inner_xy])
    return result


def main():
    if not INPUT_PATH.exists():
        print(f"[FEHLER] {INPUT_PATH} nicht gefunden")
        sys.exit(1)

    anchors = _load_legacy_anchors()
    print(f"[INFO] {len(anchors)} Regions-Anker aus Legacy-File geladen\n")

    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        source = json.load(f)

    features_out = []

    for feature in source["features"]:
        region_id = feature["properties"]["id"]
        polygon = shape(feature["geometry"])

        if region_id in MANUAL_REFERENCE_POINTS:
            # Manuelle Edge-Anker (z.B. Balderen-Punkte fuer Mittelland Ost)
            # werden wie regulaere Edge-Anker behandelt: behalten + Innen-Punkte
            # via CVT auf negativ-buffered Polygon hinzufuegen.
            manual_anchors = {region_id: MANUAL_REFERENCE_POINTS[region_id]}
            ref_points = compute_reference_points(polygon, region_id, manual_anchors)
            n_edge = len(MANUAL_REFERENCE_POINTS[region_id])
            n_inner = len(ref_points) - n_edge
            print(f"  [OK] {region_id}: {len(ref_points)} Punkte "
                  f"({n_edge} Edge manuell + {n_inner} Innen)")
        else:
            ref_points = compute_reference_points(polygon, region_id, anchors)
            n_edge = len(anchors.get(region_id, []))
            n_inner = len(ref_points) - n_edge
            print(f"  [OK] {region_id}: {len(ref_points)} Punkte "
                  f"({n_edge} Edge + {n_inner} Innen)")

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
