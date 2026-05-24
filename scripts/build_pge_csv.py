"""Build data/fluggebiete_pge.csv from PGE snapshot + DHV backup.

Output schema (21 cols):
  region, fluggebiet, site_name, latitude, longitude, elevation_m,
  wind_N, wind_NE, wind_E, wind_SE, wind_S, wind_SW, wind_W, wind_NW   (binary 0/1, PGE 0/1/2 collapsed to 0/1),
  slope_azimuth, slope_angle, kritischer_foehn, terrain_type, analyse_region,
  bemerkungen_flug, bemerkungen_sicherheit                              (left empty — populated by classify_pge_descriptions.py)

Rules:
  - PGE features with all-zero sectors are dropped (no Sektor-Information = nicht brauchbar fuer Sicherheits-Bewertung).
  - Each kept PGE feature is matched to the nearest DHV spot (<=500m).
      Match: region, fluggebiet, kritischer_foehn, analyse_region, terrain_type,
             slope_azimuth, slope_angle  ← from DHV
      No match (PGE-only):
             region, fluggebiet           ← nearest DHV (any distance, organisational label only)
             terrain_type, analyse_region, kritischer_foehn  ← polygon lookup + regionen.csv
             slope_azimuth, slope_angle   ← empty (PGE liefert keine Slope-Daten)
"""

import csv
import json
import math
from collections import Counter
from pathlib import Path

from shapely.geometry import Point, shape

ROOT = Path(__file__).resolve().parents[1]
PGE_PATH = ROOT / "data" / "_pge_ch_snapshot.json"
DHV_PATH = ROOT / "data" / "fluggebiete_dhv.backup_pre_pge.csv"
REGIONEN_CSV = ROOT / "data" / "regionen.csv"
REGIONEN_GEOJSON = ROOT / "data" / "regionen_polygone_mapped.geojson"
OUT_PATH = ROOT / "data" / "fluggebiete_pge.csv"

MATCH_RADIUS_M = 500
SECTOR_KEYS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

OUTPUT_COLUMNS = [
    "region", "fluggebiet", "site_name", "latitude", "longitude", "elevation_m",
    "wind_N", "wind_NE", "wind_E", "wind_SE", "wind_S", "wind_SW", "wind_W", "wind_NW",
    "slope_azimuth", "slope_angle", "kritischer_foehn", "terrain_type", "analyse_region",
    "bemerkungen_flug", "bemerkungen_sicherheit",
]


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def load_dhv():
    rows = []
    with DHV_PATH.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                rows.append({
                    "region": r["region"],
                    "fluggebiet": r["fluggebiet"],
                    "site_name": r["site_name"],
                    "lat": float(r["latitude"]),
                    "lon": float(r["longitude"]),
                    "kritischer_foehn": r.get("kritischer_foehn", "") or "",
                    "terrain_type": r.get("terrain_type", "") or "",
                    "analyse_region": r.get("analyse_region", "") or "",
                    "slope_azimuth": r.get("slope_azimuth", "") or "",
                    "slope_angle": r.get("slope_angle", "") or "",
                })
            except (KeyError, ValueError):
                continue
    return rows


def load_pge():
    data = json.loads(PGE_PATH.read_text(encoding="utf-8"))
    out = []
    for feat in data["features"]:
        p = feat["properties"]
        lon, lat = feat["geometry"]["coordinates"]
        sectors_raw = {k: int(p.get(k) or 0) for k in SECTOR_KEYS}
        sectors_bin = {k: (1 if v >= 1 else 0) for k, v in sectors_raw.items()}
        n_open = sum(sectors_bin.values())
        try:
            elev = int(float(p.get("takeoff_altitude") or 0))
        except (TypeError, ValueError):
            elev = 0
        out.append({
            "pge_id": feat.get("id"),
            "name": (p.get("name") or "").strip(),
            "lat": lat,
            "lon": lon,
            "elevation_m": elev,
            "sectors": sectors_bin,
            "n_open": n_open,
        })
    return out


def load_regionen():
    """region_id -> {terrain_type, analyse_region, kritischer_foehn}"""
    out = {}
    with REGIONEN_CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rid = (r.get("id") or "").strip()
            if not rid:
                continue
            out[rid] = {
                "terrain_type": (r.get("terrain_type") or "").strip(),
                "analyse_region": (r.get("region_name") or "").strip(),
                "kritischer_foehn": (r.get("kritischer_foehn") or "").strip(),
            }
    return out


def load_polygons():
    """List of (region_id, shapely Polygon)."""
    data = json.loads(REGIONEN_GEOJSON.read_text(encoding="utf-8"))
    polys = []
    for feat in data["features"]:
        rid = feat["properties"].get("id") or feat["properties"].get("region") or ""
        geom = shape(feat["geometry"])
        polys.append((rid, geom))
    return polys


def lookup_region_by_polygon(lat, lon, polygons):
    pt = Point(lon, lat)
    for rid, geom in polygons:
        if geom.contains(pt):
            return rid
    # Fallback: nearest polygon centroid
    best = (1e18, None)
    for rid, geom in polygons:
        c = geom.centroid
        d = haversine_m(lat, lon, c.y, c.x)
        if d < best[0]:
            best = (d, rid)
    return best[1]


def nearest_dhv(lat, lon, dhv_list):
    best_d, best_o = 1e18, None
    for o in dhv_list:
        d = haversine_m(lat, lon, o["lat"], o["lon"])
        if d < best_d:
            best_d, best_o = d, o
    return best_d, best_o


def main():
    pge = load_pge()
    dhv = load_dhv()
    regionen = load_regionen()
    polygons = load_polygons()

    print(f"Loaded: {len(pge)} PGE features, {len(dhv)} DHV rows, "
          f"{len(regionen)} regions, {len(polygons)} polygons")

    # Filter PGE: drop 0-sector spots
    pge_kept = [p for p in pge if p["n_open"] >= 1]
    dropped_zero = len(pge) - len(pge_kept)
    print(f"Dropped (0 sectors freigegeben): {dropped_zero} → kept {len(pge_kept)}")

    rows_out = []
    stats = Counter()
    audit_terrain_mismatch = []
    missing_region_lookup = []

    for p in pge_kept:
        d, match = nearest_dhv(p["lat"], p["lon"], dhv)

        if match is not None and d <= MATCH_RADIUS_M:
            stats["dhv_match"] += 1
            region = match["region"]
            fluggebiet = match["fluggebiet"]
            kritischer_foehn = match["kritischer_foehn"]
            analyse_region = match["analyse_region"]
            terrain_type = match["terrain_type"]
            slope_azimuth = match["slope_azimuth"]
            slope_angle = match["slope_angle"]

            # Polygon lookup als (a) Audit und (b) Fallback fuer leere DHV-Felder
            rid = lookup_region_by_polygon(p["lat"], p["lon"], polygons)
            poly_info = regionen.get(rid, {})
            poly_terrain = poly_info.get("terrain_type", "")
            if not terrain_type:
                terrain_type = poly_terrain
                stats["dhv_fill_terrain"] += 1
            if not analyse_region:
                analyse_region = poly_info.get("analyse_region", "")
                stats["dhv_fill_analyse_region"] += 1
            if not kritischer_foehn:
                kritischer_foehn = poly_info.get("kritischer_foehn", "")
                stats["dhv_fill_foehn"] += 1
            if terrain_type and poly_terrain and terrain_type != poly_terrain:
                audit_terrain_mismatch.append({
                    "name": p["name"], "lat": p["lat"], "lon": p["lon"],
                    "dhv": terrain_type, "polygon": poly_terrain, "polygon_region": rid,
                })
        else:
            stats["pge_only"] += 1
            rid = lookup_region_by_polygon(p["lat"], p["lon"], polygons)
            reg_info = regionen.get(rid)
            if not reg_info:
                missing_region_lookup.append(p["name"])
                terrain_type = ""
                analyse_region = ""
                kritischer_foehn = ""
            else:
                terrain_type = reg_info["terrain_type"]
                analyse_region = reg_info["analyse_region"]
                kritischer_foehn = reg_info["kritischer_foehn"]
            # region, fluggebiet from nearest DHV neighbor (any distance, org label only)
            _, nbr = nearest_dhv(p["lat"], p["lon"], dhv)
            region = nbr["region"] if nbr else ""
            fluggebiet = nbr["fluggebiet"] if nbr else ""
            slope_azimuth = ""
            slope_angle = ""

        row = {
            "region": region,
            "fluggebiet": fluggebiet,
            "site_name": p["name"],
            "latitude": f"{p['lat']:.6f}",
            "longitude": f"{p['lon']:.6f}",
            "elevation_m": str(p["elevation_m"]),
            "slope_azimuth": slope_azimuth,
            "slope_angle": slope_angle,
            "kritischer_foehn": kritischer_foehn,
            "terrain_type": terrain_type,
            "analyse_region": analyse_region,
            "bemerkungen_flug": "",
            "bemerkungen_sicherheit": "",
        }
        for k in SECTOR_KEYS:
            row[f"wind_{k}"] = str(p["sectors"][k])
        rows_out.append(row)

    # Write CSV
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for r in rows_out:
            writer.writerow(r)

    # Stats
    print()
    print(f"Wrote {len(rows_out)} rows -> {OUT_PATH.relative_to(ROOT)}")
    print(f"  DHV-matched (<={MATCH_RADIUS_M}m): {stats['dhv_match']}")
    print(f"  PGE-only (polygon lookup):        {stats['pge_only']}")
    if stats["dhv_fill_terrain"] or stats["dhv_fill_analyse_region"] or stats["dhv_fill_foehn"]:
        print(f"  DHV-Match fallback to polygon (empty DHV fields):")
        print(f"    terrain_type:    {stats['dhv_fill_terrain']}")
        print(f"    analyse_region:  {stats['dhv_fill_analyse_region']}")
        print(f"    kritischer_foehn:{stats['dhv_fill_foehn']}")
    print()

    # Terrain breakdown
    terrain_breakdown = Counter(r["terrain_type"] or "<empty>" for r in rows_out)
    print("terrain_type breakdown:")
    for t, n in terrain_breakdown.most_common():
        print(f"  {t:<12} {n}")
    print()

    # Audit
    if audit_terrain_mismatch:
        print(f"AUDIT — DHV terrain_type vs polygon mismatch ({len(audit_terrain_mismatch)} spots):")
        for m in audit_terrain_mismatch[:30]:
            print(f"  {m['name']:<40} dhv={m['dhv']:<10} polygon={m['polygon']:<10} ({m['polygon_region']})")
        if len(audit_terrain_mismatch) > 30:
            print(f"  ... and {len(audit_terrain_mismatch) - 30} more")
        print()

    if missing_region_lookup:
        print(f"WARNING: {len(missing_region_lookup)} PGE-only spots got no polygon hit and no fallback region:")
        for n in missing_region_lookup[:10]:
            print(f"  - {n}")

    # Sector usage
    sec_counts = Counter()
    for r in rows_out:
        for k in SECTOR_KEYS:
            sec_counts[k] += int(r[f"wind_{k}"])
    print("Sector usage (count of spots with sector open):")
    for k in SECTOR_KEYS:
        print(f"  {k:<3} {sec_counts[k]}")


if __name__ == "__main__":
    main()
