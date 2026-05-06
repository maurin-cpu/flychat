"""Enrich fluggebiete_complete.csv with analyse_region, terrain_type, and
overwrite kritischer_foehn from the matched analysis region.

Spots whose lat/lon does not fall into any region polygon get empty values.

Run:  python scripts/enrich_spots_with_region.py            (writes file)
      python scripts/enrich_spots_with_region.py --dry-run  (stats only)
"""
import argparse
import csv
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from source_area import find_region_for_point  # noqa: E402

CSV_PATH = ROOT / "data" / "fluggebiete_complete.csv"

NEW_COLUMNS = ["terrain_type", "analyse_region"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        with open(CSV_PATH, encoding="utf-8-sig") as f:
            raw = f.read()
    except UnicodeDecodeError:
        with open(CSV_PATH, encoding="cp1252") as f:
            raw = f.read()

    reader = csv.DictReader(io.StringIO(raw))
    fieldnames = list(reader.fieldnames or [])

    # Insert new columns before 'Bemerkungen' if present, else append
    insert_idx = fieldnames.index("Bemerkungen") if "Bemerkungen" in fieldnames else len(fieldnames)
    for col in NEW_COLUMNS:
        if col not in fieldnames:
            fieldnames.insert(insert_idx, col)
            insert_idx += 1

    rows = list(reader)
    matched = 0
    unmatched = []
    foehn_changed = 0

    for row in rows:
        site = row.get("site_name", "").strip()
        try:
            lat = float(row["latitude"])
            lon = float(row["longitude"])
        except (KeyError, ValueError):
            row["terrain_type"] = ""
            row["analyse_region"] = ""
            row["kritischer_foehn"] = ""
            unmatched.append((site, "no coords"))
            continue

        region = find_region_for_point(lat, lon)
        if region is None:
            row["terrain_type"] = ""
            row["analyse_region"] = ""
            row["kritischer_foehn"] = ""
            unmatched.append((site, f"{lat},{lon}"))
            continue

        new_foehn = (region.get("kritischer_foehn") or "").strip()
        old_foehn = (row.get("kritischer_foehn") or "").strip()
        if old_foehn != new_foehn:
            foehn_changed += 1

        row["terrain_type"] = region.get("terrain_type") or ""
        row["analyse_region"] = region.get("region") or ""
        row["kritischer_foehn"] = new_foehn
        matched += 1

    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)

    if args.dry_run:
        print("[DRY-RUN] No file written.")
    else:
        CSV_PATH.write_text(out.getvalue(), encoding="utf-8")
        print(f"[OK] Wrote {CSV_PATH}")

    print(f"Matched:           {matched}")
    print(f"Unmatched:         {len(unmatched)}")
    print(f"kritischer_foehn   changed for {foehn_changed} spots")
    if unmatched:
        print("\nUnmatched spots:")
        for site, info in unmatched:
            print(f"  - {site}  ({info})")


if __name__ == "__main__":
    main()
