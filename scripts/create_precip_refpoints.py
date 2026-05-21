"""
Erstellt regionen_referenzpunkte_precip.geojson aus regionen_polygone_mapped.geojson.

Pro Region werden N=16 Niederschlags-Referenzpunkte definiert via reinem
Lloyd-CVT auf einem leicht negativ-gebufferten Polygon. Anders als die 7
Haupt-Referenzpunkte (die Edge-Anker fuer Talwind-Erfassung enthalten)
sind diese 16 Punkte rein raeumlich-gleichmaessig verteilt.

Zweck: Schauer und konvektive Niederschlagszellen sind kleinraeumig
(typische ICON-D2 Gridzelle 2.2 km). Mit 7 Refpoints fallen einzelne
Zellen oft ZWISCHEN den Punkten durch. 16 dichte Punkte erfassen das
Muster ehrlicher und liefern eine Coverage-Statistik (n_wet/n_total),
die zwischen 'flaechig' / 'verstreut' / 'vereinzelt' / 'trocken'
unterscheidet.

Verwendung in der Pipeline:
- fetch_weather.py holt fuer jede Region beide Refpoint-Sets:
  * 7 Haupt-RPs fuer Wind / Wolken / Thermik (unveraendert)
  * 16 Precip-RPs nur fuer precipitation + precipitation_probability
- engine/weather_context.py klassifiziert pro Stunde:
  * widespread:  >= 70% RPs nass
  * scattered:   25-70%
  * isolated:    <25% bei Peak >= 0.2 mm/h
  * dry:         alle <0.05 mm/h
"""

import json
import math
import random
import sys
from pathlib import Path
from shapely.geometry import shape, Point

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
INPUT_PATH = DATA_DIR / "regionen_polygone_mapped.geojson"
OUTPUT_PATH = DATA_DIR / "regionen_referenzpunkte_precip.geojson"

# Anzahl Niederschlags-Referenzpunkte pro Region.
# 16 ist Sweet Spot: gut genug um Konvektionszellen (~5-10 km Skala) zu
# erfassen, ohne API-Last unnoetig zu erhoehen.
N_PRECIP = 16

# Inset fuer Innen-Polygon: kleiner als bei den 7 Haupt-RPs (15%), weil
# wir bewusst auch raender-nahe Niederschlagszellen erfassen wollen.
INSET_FRACTION = 0.07

# Grid-Aufloesung fuer Sampling. Hoeher als bei 7 RPs (60) damit CVT
# auch bei kleinen Regionen genug Samples hat.
GRID_RESOLUTION = 80

# CVT-Iterationen. 50 ist konvergent fuer k=16 auf typischen CH-Regionen.
CVT_ITERATIONS = 50

# Random-Seed fuer Reproduzierbarkeit.
RNG_SEED = 42


def _inner_polygon(polygon, inset_fraction=INSET_FRACTION):
    """Negativ-gebuffertes Polygon. Fallback bei Kollaps: kleinere Insets."""
    minx, miny, maxx, maxy = polygon.bounds
    base_inset = min(maxx - minx, maxy - miny) * inset_fraction
    for factor in (1.0, 0.7, 0.5, 0.3, 0.15, 0.0):
        inset = base_inset * factor
        if inset == 0:
            return polygon
        shrunken = polygon.buffer(-inset)
        if not shrunken.is_empty and shrunken.area > 0:
            return shrunken
    return polygon


def _samples_in_geometry(geom, resolution=GRID_RESOLUTION):
    """Grid-Sample innerhalb (Multi)Polygon."""
    minx, miny, maxx, maxy = geom.bounds
    samples = []
    for i in range(resolution):
        for j in range(resolution):
            x = minx + (maxx - minx) * (i + 0.5) / resolution
            y = miny + (maxy - miny) * (j + 0.5) / resolution
            if geom.contains(Point(x, y)):
                samples.append((x, y))
    return samples


def _kmeans_pp_init(samples, k, seed=RNG_SEED):
    """k-means++ Initialisierung — spreizt Start-Centroide gut."""
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


def _lloyd_cvt(samples, k, iterations=CVT_ITERATIONS):
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


def compute_precip_points(polygon, region_id):
    """N=16 Punkte via Lloyd-CVT auf negativ-gebuffertem Polygon.

    Returns: Liste [[lat, lon], ...] mit 4-Nachkommastellen.
    """
    inner_geom = _inner_polygon(polygon)
    samples = _samples_in_geometry(inner_geom)

    if len(samples) < N_PRECIP:
        # Fallback fuer winzige Regionen: dichteres Sampling auf Original-Polygon.
        samples = _samples_in_geometry(polygon, resolution=GRID_RESOLUTION * 2)

    if len(samples) < N_PRECIP:
        # Letzter Fallback: Centroid + leichte Versatze
        centroid = polygon.centroid
        cx, cy = centroid.x, centroid.y
        bounds = polygon.bounds
        dx = (bounds[2] - bounds[0]) * 0.1
        dy = (bounds[3] - bounds[1]) * 0.1
        rng = random.Random(RNG_SEED)
        inner_xy = []
        for _ in range(N_PRECIP):
            inner_xy.append((cx + rng.uniform(-dx, dx), cy + rng.uniform(-dy, dy)))
    else:
        inner_xy = _lloyd_cvt(samples, N_PRECIP)

    return [[round(pt[1], 4), round(pt[0], 4)] for pt in inner_xy]


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
        precip_points = compute_precip_points(polygon, region_id)

        new_feature = {
            "type": "Feature",
            "geometry": feature["geometry"],
            "properties": {
                "id": region_id,
                "region": feature["properties"].get("region", region_id),
                "name": feature["properties"].get("name", region_id),
                "purpose": "precipitation_only",
                "n_points": len(precip_points),
                "reference_points": precip_points,
            },
        }
        features_out.append(new_feature)
        print(f"  [OK] {region_id}: {len(precip_points)} Precip-Punkte (CVT)")

    output = {"type": "FeatureCollection", "features": features_out}

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n[INFO] {len(features_out)} Regionen geschrieben: {OUTPUT_PATH}")
    print(f"[INFO] Gesamt {len(features_out) * N_PRECIP} Precip-Refpoints")


if __name__ == "__main__":
    main()
