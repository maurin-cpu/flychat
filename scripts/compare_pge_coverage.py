"""Compare our fluggebiete CSV against the Paragliding Earth CH snapshot.

Output:
 - How many of OUR spots find a PGE match within N meters
 - How many PGE spots have NO match in our CSV (potential additions)
 - Sector-coverage stats (degenerate vs. broad sector definitions)
"""

import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "fluggebiete_dhv.csv"
PGE_PATH = ROOT / "data" / "_pge_ch_snapshot.json"

MATCH_RADIUS_M = 500  # how close counts as the same takeoff


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def load_ours():
    rows = []
    with CSV_PATH.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                rows.append({
                    "name": r["site_name"],
                    "region": r["region"],
                    "fluggebiet": r["fluggebiet"],
                    "lat": float(r["latitude"]),
                    "lon": float(r["longitude"]),
                    "windrichtung": r.get("windrichtung", ""),
                })
            except (KeyError, ValueError):
                continue
    return rows


def load_pge():
    data = json.loads(PGE_PATH.read_text(encoding="utf-8"))
    pts = []
    for feat in data["features"]:
        p = feat["properties"]
        lon, lat = feat["geometry"]["coordinates"]
        sectors = {k: int(p.get(k) or 0) for k in ("N", "NE", "E", "SE", "S", "SW", "W", "NW")}
        pts.append({"name": p.get("name", ""), "lat": lat, "lon": lon, "sectors": sectors,
                    "alt": p.get("takeoff_altitude", "")})
    return pts


def main():
    ours = load_ours()
    pge = load_pge()
    print(f"Our CSV:           {len(ours)} spots")
    print(f"PGE CH snapshot:   {len(pge)} spots")
    print(f"Match radius:      {MATCH_RADIUS_M} m\n")

    # For each of our spots: nearest PGE
    matched_ours = 0
    no_match_ours = []
    used_pge = set()
    for o in ours:
        best_d, best_i = 1e12, -1
        for i, p in enumerate(pge):
            d = haversine_m(o["lat"], o["lon"], p["lat"], p["lon"])
            if d < best_d:
                best_d, best_i = d, i
        if best_d <= MATCH_RADIUS_M:
            matched_ours += 1
            used_pge.add(best_i)
            o["_pge"] = pge[best_i]
            o["_d"] = best_d
        else:
            no_match_ours.append((o, best_d))

    pge_only = [p for i, p in enumerate(pge) if i not in used_pge]

    pct = 100 * matched_ours / len(ours)
    print(f"OUR spots with a PGE match (≤{MATCH_RADIUS_M}m): {matched_ours}/{len(ours)} ({pct:.1f} %)")
    print(f"OUR spots with NO PGE match:                  {len(no_match_ours)}")
    print(f"PGE spots NOT in our CSV (potential adds):    {len(pge_only)}\n")

    # Sector coverage of PGE
    sector_widths = []
    for p in pge:
        n = sum(1 for v in p["sectors"].values() if v >= 1)
        sector_widths.append(n)
    from collections import Counter
    c = Counter(sector_widths)
    print("PGE sector breadth (count of sectors with value ≥1):")
    for k in sorted(c):
        print(f"  {k} sectors freigegeben:  {c[k]} spots")
    print()

    # Sample non-matches from our side
    print("Sample of OUR spots WITHOUT a PGE match (top 10 by closest distance):")
    no_match_ours.sort(key=lambda x: x[1])
    for o, d in no_match_ours[:10]:
        print(f"  - {o['region']:<22} {o['name']:<30} (nearest PGE {d/1000:.1f} km)")
    print()

    # Sample PGE-only
    print("Sample of PGE spots NOT in our CSV (random 10):")
    import random
    random.seed(42)
    for p in random.sample(pge_only, min(10, len(pge_only))):
        sectors_on = ",".join(k for k, v in p["sectors"].items() if v >= 1) or "—"
        print(f"  - {p['name']:<35} ({p['lat']:.4f},{p['lon']:.4f}) alt={p['alt']:<5} sectors={sectors_on}")


if __name__ == "__main__":
    main()
