"""List all PGE-only spots that are within 1000m of one of our spots.

These are most likely the same takeoff with a different name. Output
includes PGE sectors so the user can decide whether the PGE entry adds
information or is just a naming variant.
"""

import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def hav(a, b, c, d):
    R = 6371000
    p1, p2 = math.radians(a), math.radians(c)
    dp = math.radians(c - a)
    dl = math.radians(d - b)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def sector_string(p):
    keys = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
    ideal = [k for k in keys if int(p.get(k) or 0) == 2]
    ok = [k for k in keys if int(p.get(k) or 0) == 1]
    parts = []
    if ideal:
        parts.append("IDEAL=" + ",".join(ideal))
    if ok:
        parts.append("ok=" + ",".join(ok))
    return " | ".join(parts) if parts else "—"


ours = []
with (ROOT / "data" / "fluggebiete_dhv.csv").open(encoding="utf-8") as f:
    for r in csv.DictReader(f):
        try:
            ours.append({
                "name": r["site_name"], "region": r["region"], "fluggebiet": r["fluggebiet"],
                "lat": float(r["latitude"]), "lon": float(r["longitude"]),
                "wr": r.get("windrichtung", ""),
            })
        except (KeyError, ValueError):
            continue

pge = json.loads((ROOT / "data" / "_pge_ch_snapshot.json").read_text(encoding="utf-8"))["features"]

# which PGE features are already matched within 500m
matched_pge_idx = set()
for o in ours:
    best = (1e12, -1)
    for i, p in enumerate(pge):
        lon, lat = p["geometry"]["coordinates"]
        d = hav(o["lat"], o["lon"], lat, lon)
        if d < best[0]:
            best = (d, i)
    if best[0] <= 500:
        matched_pge_idx.add(best[1])

# build candidate list: PGE-only spots whose nearest OUR spot is within 1000m
candidates = []
for i, p in enumerate(pge):
    if i in matched_pge_idx:
        continue
    lon, lat = p["geometry"]["coordinates"]
    best_d = 1e12
    best_o = None
    for o in ours:
        d = hav(o["lat"], o["lon"], lat, lon)
        if d < best_d:
            best_d, best_o = d, o
    if best_d <= 1000:
        candidates.append((best_d, p, best_o))

candidates.sort(key=lambda x: x[0])

print(f"# PGE-only spots within 1000m of one of our spots\n")
print(f"Total: {len(candidates)}\n")
print(f"{'dist':>5}  {'PGE name':<40}  {'OUR name':<28}  {'Region':<18}  PGE sectors")
print(f"{'-'*5}  {'-'*40}  {'-'*28}  {'-'*18}  {'-'*40}")
for d, p, o in candidates:
    pn = p["properties"].get("name", "")[:40]
    on = o["name"][:28]
    rg = o["region"][:18]
    sec = sector_string(p["properties"])
    print(f"{int(d):>4}m  {pn:<40}  {on:<28}  {rg:<18}  {sec}")
