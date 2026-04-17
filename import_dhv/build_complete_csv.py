#!/usr/bin/env python3
"""Build complete fluggebiete CSV from existing CSV + DHV KML."""

import csv
import io
import math
import os
import re
import xml.etree.ElementTree as ET
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KML_PATH = os.path.join(SCRIPT_DIR, "dhv_gelaende_2026-04-09_16.27.54.kml")
CSV_PATH = os.path.join(SCRIPT_DIR, "fluggebiete_complete.csv")
OUTPUT_PATH = CSV_PATH

KML_NS = {"k": "http://www.opengis.net/kml/2.2"}

KANTON_REGION = {
    "Appenzell Ausserrhoden": "Ostschweiz",
    "Appenzell Innerrhoden": "Ostschweiz",
    "St. Gallen": "Ostschweiz",
    "Glarus": "Ostschweiz",
    "Thurgau": "Ostschweiz",
    "Schaffhausen": "Ostschweiz",
    "Obwalden": "Zentralschweiz",
    "Nidwalden": "Zentralschweiz",
    "Luzern": "Zentralschweiz",
    "Uri": "Zentralschweiz",
    "Zug": "Zentralschweiz",
    "Schwyz": "Schwyz",
    "Zürich": "Zürich",
    "Solothurn": "Solothurn",
    "Wallis": "Wallis",
    "Graubünden": "Graubünden",
    "Tessin": "Tessin",
    "Waadt": "Waadt",
    "Freiburg": "Freiburg",
    "Fribourg": "Freiburg",
    "Neuenburg": "Neuenburg",
    "Jura": "Jura",
    "Basel-Landschaft": "Nordwestschweiz",
    "Basel-Stadt": "Nordwestschweiz",
    "Aargau": "Aargau",
}

EXCLUDE_GELAENDE = {"Bündner Rigi"}


def haversine_m(lat1, lon1, lat2, lon2):
    """Return distance in metres between two lat/lon points."""
    R = 6_371_000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def parse_description(desc_text):
    """Extract startrichtung and elevation from description CDATA."""
    startrichtung = ""
    elevation = ""
    gemeinde = ""
    if not desc_text:
        return startrichtung, elevation, gemeinde
    m = re.search(r"Startrichtung\s+([^<]+)", desc_text)
    if m:
        startrichtung = m.group(1).strip()
    m = re.search(r"H.{1,2}he\s+NN\s+(\d+)\s*m", desc_text)
    if m:
        elevation = m.group(1)
    m = re.search(r"Gemeinde\s+([^,<]+)", desc_text)
    if m:
        gemeinde = m.group(1).strip()
    return startrichtung, elevation, gemeinde


def clean_site_name(raw_name):
    """Clean site name per naming rules."""
    name = raw_name.strip()
    m = re.match(r"(.+?)\s+Startplatz\s+\d+\s+\(([^)]+)\)", name)
    if m:
        return m.group(2).strip()
    name = re.sub(r"\s+Start-/Landeplatz$", "", name)
    m = re.match(r"(.+?)\s+Startplatz\s+(\d+.*)$", name)
    if m:
        return f"{m.group(1).strip()} {m.group(2).strip()}"
    name = re.sub(r"\s+Startplatz$", "", name)
    m = re.match(r"^Startplatz\s+(.+)$", name)
    if m:
        return m.group(1).strip()
    return name.strip()


def get_region(kanton, lat):
    """Map Kanton to region, with special Bern latitude rule."""
    if kanton == "Bern":
        return "Berneroberland" if lat < 46.8 else "Bern"
    return KANTON_REGION.get(kanton, kanton)


def parse_kml(kml_path):
    """Parse all Startplatz entries from KML."""
    tree = ET.parse(kml_path)
    root = tree.getroot()
    doc = root.find("k:Document", KML_NS)
    schweiz_folder = doc.find("k:Folder", KML_NS)
    entries = []
    for kanton_folder in schweiz_folder.findall("k:Folder", KML_NS):
        kanton = kanton_folder.find("k:name", KML_NS).text.strip()
        for gelaende_folder in kanton_folder.findall("k:Folder", KML_NS):
            gelaende_name = gelaende_folder.find("k:name", KML_NS).text.strip()
            if gelaende_name in EXCLUDE_GELAENDE:
                continue
            for pm in gelaende_folder.findall("k:Placemark", KML_NS):
                style_el = pm.find("k:styleUrl", KML_NS)
                if style_el is None:
                    continue
                if "startplatz" not in style_el.text:
                    continue
                raw_name = pm.find("k:name", KML_NS).text.strip()
                coords_el = pm.find(".//k:coordinates", KML_NS)
                if coords_el is None:
                    continue
                coord_parts = coords_el.text.strip().split(",")
                lon = float(coord_parts[0])
                lat = float(coord_parts[1])
                desc_el = pm.find("k:description", KML_NS)
                desc_text = desc_el.text if desc_el is not None else ""
                startrichtung, elevation_str, gemeinde = parse_description(desc_text)
                elevation = int(elevation_str) if elevation_str else 0
                site_name = clean_site_name(raw_name)
                entries.append({
                    "kanton": kanton,
                    "gelaende_name": gelaende_name,
                    "raw_name": raw_name,
                    "site_name": site_name,
                    "lat": lat,
                    "lon": lon,
                    "elevation": elevation,
                    "startrichtung": startrichtung,
                })
    return entries


def read_existing_csv(csv_path):
    """Read existing CSV, return header, raw data lines, and parsed rows."""
    with open(csv_path, "r", encoding="utf-8") as f:
        raw_content = f.read()
    lines = raw_content.splitlines(keepends=False)
    header_line = lines[0] if lines else ""
    data_lines = lines[1:] if len(lines) > 1 else []
    while data_lines and not data_lines[-1].strip():
        data_lines.pop()
    parsed_rows = []
    reader = csv.DictReader(io.StringIO(raw_content))
    for row in reader:
        parsed_rows.append({
            "lat": float(row["latitude"]),
            "lon": float(row["longitude"]),
            "site_name": row["site_name"],
            "region": row["region"],
            "fluggebiet": row["fluggebiet"],
        })
    return header_line, data_lines, parsed_rows


def main():
    print("=" * 70)
    print("Building complete fluggebiete CSV")
    print("=" * 70)

    kml_entries = parse_kml(KML_PATH)
    print(f"
Parsed {len(kml_entries)} Startplatz entries from KML")

    header_line, data_lines, existing_rows = read_existing_csv(CSV_PATH)
    print(f"Read {len(data_lines)} existing rows from CSV")

    existing_coords = [(r["lat"], r["lon"], r["site_name"], r["fluggebiet"]) for r in existing_rows]

    new_entries = []
    skipped = []
    for entry in kml_entries:
        is_duplicate = False
        for ex_lat, ex_lon, ex_name, ex_gebiet in existing_coords:
            dist = haversine_m(entry["lat"], entry["lon"], ex_lat, ex_lon)
            if dist < 500:
                skipped.append({
                    "kml_name": entry["raw_name"],
                    "kml_site": entry["site_name"],
                    "csv_name": ex_name,
                    "csv_gebiet": ex_gebiet,
                    "dist_m": round(dist, 1),
                })
                is_duplicate = True
                break
        if not is_duplicate:
            new_entries.append(entry)

    print(f"Skipped {len(skipped)} entries (already in CSV within 500m)")
    print(f"New entries to add: {len(new_entries)}")

    new_rows = []
    for entry in new_entries:
        region = get_region(entry["kanton"], entry["lat"])
        new_rows.append({
            "region": region,
            "fluggebiet": entry["gelaende_name"],
            "site_name": entry["site_name"],
            "latitude": round(entry["lat"], 6),
            "longitude": round(entry["lon"], 6),
            "elevation_m": entry["elevation"],
            "windrichtung": entry["startrichtung"],
            "ideal_wind_max_kmh": 30,
            "slope_azimuth": "",
            "slope_angle": "",
            "kritischer_foehn": "Süd",
            "Bemerkungen": "",
        })

    new_rows.sort(key=lambda r: (r["region"], r["fluggebiet"], r["site_name"]))

    fieldnames = [
        "region", "fluggebiet", "site_name", "latitude", "longitude",
        "elevation_m", "windrichtung", "ideal_wind_max_kmh",
        "slope_azimuth", "slope_angle", "kritischer_foehn", "Bemerkungen",
    ]

    new_csv_lines = []
    for row in new_rows:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="")
        writer.writerow(row)
        new_csv_lines.append(buf.getvalue())

    with open(OUTPUT_PATH, "w", encoding="utf-8", newline="") as f:
        f.write(header_line + "
")
        for line in data_lines:
            f.write(line + "
")
        for line in new_csv_lines:
            f.write(line + "
")

    total_rows = len(data_lines) + len(new_rows)
    print(f"
Wrote {total_rows} total rows to {OUTPUT_PATH}")

    print("
" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Existing rows kept:  {len(data_lines)}")
    print(f"  New rows added:      {len(new_rows)}")
    print(f"  Total rows in output: {total_rows}")

    print("
  Region breakdown (existing + new):")
    region_existing = defaultdict(int)
    region_new = defaultdict(int)
    for r in existing_rows:
        region_existing[r["region"]] += 1
    for r in new_rows:
        region_new[r["region"]] += 1

    all_regions = sorted(set(list(region_existing.keys()) + list(region_new.keys())))
    for region in all_regions:
        ex = region_existing.get(region, 0)
        nw = region_new.get(region, 0)
        print(f"    {region:25s}  existing: {ex:3d}  new: {nw:3d}  total: {ex+nw:3d}")

    if skipped:
        print(f"
  Skipped entries (already in CSV, {len(skipped)} total):")
        for s in skipped:
            kn = s["kml_name"]
            cn = s["csv_name"]
            cg = s["csv_gebiet"]
            dm = s["dist_m"]
            print(f"    KML: {kn:40s} -> CSV: {cn:25s} ({cg}) dist={dm}m")

    print("
Done.")


if __name__ == "__main__":
    main()
