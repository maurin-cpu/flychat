"""Generate data/fluggebiete_test.csv as PGE-schema subset.

Picks 28 unique spots from fluggebiete_pge.csv that cover the old test set
(Uetliberg, Weissenstein, Pilatus, Rigi, Engelberg, ...) plus terrain-type
diversity (mittelland/jura/voralpen/alpen/hochalpin).
"""

import csv
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD_TEST = ROOT / "data" / "fluggebiete_test.csv"  # legacy DHV-format
PGE = ROOT / "data" / "fluggebiete_pge.csv"
OUT = OLD_TEST  # in-place

TARGET_COUNT = 28
MATCH_RADIUS_M = 500


def hav(a, b, c, d):
    R = 6371000.0
    p1, p2 = math.radians(a), math.radians(c)
    dp = math.radians(c - a)
    dl = math.radians(d - b)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def main():
    old_test = list(csv.DictReader(open(OLD_TEST, encoding="utf-8")))
    pge_rows = list(csv.DictReader(open(PGE, encoding="utf-8")))
    pge_by_idx = {i: r for i, r in enumerate(pge_rows)}

    # Step 1: for each old test row, find nearest PGE within MATCH_RADIUS_M
    selected_pge_idx = []
    seen = set()
    for o in old_test:
        try:
            olat, olon = float(o["latitude"]), float(o["longitude"])
        except (ValueError, KeyError):
            continue
        best = (1e18, -1)
        for i, p in enumerate(pge_rows):
            d = hav(olat, olon, float(p["latitude"]), float(p["longitude"]))
            if d < best[0]:
                best = (d, i)
        if best[0] <= MATCH_RADIUS_M and best[1] not in seen:
            seen.add(best[1])
            selected_pge_idx.append(best[1])

    # Step 2: fill up to TARGET_COUNT, balancing terrain_type
    from collections import Counter
    have = Counter(pge_rows[i]["terrain_type"] for i in selected_pge_idx)
    print(f"After step 1: {len(selected_pge_idx)} unique PGE matches, terrain: {dict(have)}")

    if len(selected_pge_idx) < TARGET_COUNT:
        all_terrain = sorted(set(p["terrain_type"] for p in pge_rows))
        for tt in all_terrain:
            if len(selected_pge_idx) >= TARGET_COUNT:
                break
            candidates = [i for i, p in enumerate(pge_rows)
                          if p["terrain_type"] == tt and i not in seen]
            for ci in candidates:
                if len(selected_pge_idx) >= TARGET_COUNT:
                    break
                seen.add(ci)
                selected_pge_idx.append(ci)

    # Step 3: write
    selected = [pge_rows[i] for i in selected_pge_idx]
    final_terrain = Counter(r["terrain_type"] for r in selected)
    print(f"Final: {len(selected)} spots, terrain breakdown: {dict(final_terrain)}")
    print()
    print("Selected spots:")
    for r in selected:
        print(f"  - {r['site_name']:<35} ({r['terrain_type']:<10}, {r['analyse_region']})")

    fieldnames = list(pge_rows[0].keys())
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(selected)
    print(f"\nWrote {len(selected)} rows -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
