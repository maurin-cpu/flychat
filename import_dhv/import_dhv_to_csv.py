"""
Importiert alle Schweizer Startplätze aus der DHV-Gelände-KML-Datei
und schreibt sie in data/fluggebiete_dhv.csv.

Bestehende CSV-Einträge bleiben erhalten (Proximity-Check 500m).
Neue Einträge werden angehängt.

Usage:
    python import_dhv/import_dhv_to_csv.py
"""

import csv
import io
import math
import os
import re
import xml.etree.ElementTree as ET

# --- Pfade ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
KML_PATH = os.path.join(SCRIPT_DIR, "dhv_gelaende_2026-04-09_16.27.54.kml")
CSV_PATH = os.path.join(PROJECT_ROOT, "data", "fluggebiete_dhv.csv")

NS = {"kml": "http://www.opengis.net/kml/2.2"}

# --- Kanton → Region Mapping ---
KANTON_TO_REGION = {
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
    "Neuenburg": "Neuenburg",
    "Jura": "Jura",
    "Basel-Landschaft": "Nordwestschweiz",
    "Basel-Stadt": "Nordwestschweiz",
    "Aargau": "Aargau",
    "Genf": "Genf",
}

CSV_HEADER = [
    "region", "fluggebiet", "site_name", "latitude", "longitude",
    "elevation_m", "windrichtung", "ideal_wind_max_kmh",
    "slope_azimuth", "slope_angle", "kritischer_foehn", "Bemerkungen",
]


# --- Hilfsfunktionen ---

def haversine_m(lat1, lon1, lat2, lon2):
    R = 6_371_000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def parse_kml(kml_path):
    """Extrahiert alle Startplätze aus der DHV-KML."""
    tree = ET.parse(kml_path)
    root = tree.getroot()
    entries = []

    doc = root.find("kml:Document", NS)
    if doc is None:
        return entries

    # Schweiz-Folder
    for country_folder in doc.findall("kml:Folder", NS):
        country_name = country_folder.findtext("kml:name", "", NS).strip()
        if country_name != "Schweiz":
            continue

        # Kanton-Folder
        for kanton_folder in country_folder.findall("kml:Folder", NS):
            kanton = kanton_folder.findtext("kml:name", "", NS).strip()

            # Gelände-Folder
            for gelaende_folder in kanton_folder.findall("kml:Folder", NS):
                gelaende = gelaende_folder.findtext("kml:name", "", NS).strip()

                for pm in gelaende_folder.findall("kml:Placemark", NS):
                    style = pm.findtext("kml:styleUrl", "", NS)
                    if "startplatz" not in style.lower():
                        continue

                    name = pm.findtext("kml:name", "", NS).strip()
                    desc = pm.findtext("kml:description", "", NS) or ""

                    # Koordinaten (KML: lon,lat)
                    coords_text = ""
                    pt = pm.find("kml:Point", NS)
                    if pt is not None:
                        coords_text = pt.findtext("kml:coordinates", "", NS).strip()
                    if not coords_text:
                        continue
                    parts = coords_text.split(",")
                    lon = float(parts[0])
                    lat = float(parts[1])

                    # Description parsen
                    elev_m = re.search(r"Höhe NN (\d+)m", desc)
                    elev = int(elev_m.group(1)) if elev_m else 0

                    sr_m = re.search(r"Startrichtung\s+([A-ZÄÖÜa-z\-]+)", desc)
                    startrichtung = sr_m.group(1).strip() if sr_m else ""

                    entries.append({
                        "kanton": kanton,
                        "gelaende": gelaende,
                        "raw_name": name,
                        "lat": lat,
                        "lon": lon,
                        "elevation": elev,
                        "startrichtung": startrichtung,
                    })

    return entries


def clean_site_name(raw_name, gelaende):
    """Bereinigt KML-Startplatznamen für die CSV."""
    name = raw_name.strip()

    # "XYZ Startplatz N (Alias)" → Alias verwenden
    paren = re.search(r"\(([^)]+)\)", name)

    # "Startplatz" Suffix entfernen
    # Patterns: "Name Startplatz", "Name Startplatz 3"
    cleaned = re.sub(r"\s+Startplatz\s*(\d+)?\s*(\([^)]*\))?\s*$", "", name).strip()

    if paren:
        alias = paren.group(1).strip()
        # Wenn Alias sinnvoll (nicht nur Zahl), verwenden
        if alias and not alias.isdigit():
            return alias

    # Nummer behalten falls vorhanden
    num_match = re.search(r"Startplatz\s+(\d+)", name)
    if num_match and cleaned == gelaende:
        return f"{gelaende} {num_match.group(1)}"
    if num_match and cleaned:
        return f"{cleaned} {num_match.group(1)}"

    return cleaned if cleaned else name


def kanton_to_region(kanton, lat):
    """Mappt Kanton auf Region."""
    if kanton in KANTON_TO_REGION:
        return KANTON_TO_REGION[kanton]
    if kanton == "Bern":
        return "Berneroberland" if lat < 46.8 else "Bern"
    return kanton


def read_existing_csv(csv_path):
    """Liest bestehende CSV-Einträge."""
    rows = []
    if not os.path.exists(csv_path):
        return rows, []

    with open(csv_path, encoding="utf-8-sig") as f:
        raw_text = f.read()

    raw_lines = raw_text.rstrip("\n").split("\n")

    reader = csv.DictReader(io.StringIO(raw_text))
    for row in reader:
        if not row.get("site_name", "").strip():
            continue
        try:
            lat = float(row["latitude"])
            lon = float(row["longitude"])
        except (ValueError, KeyError):
            continue
        rows.append({"lat": lat, "lon": lon})

    return rows, raw_lines


def is_duplicate(lat, lon, existing_rows, threshold_m=500):
    """Prüft ob Koordinaten bereits in bestehenden Einträgen sind."""
    for ex in existing_rows:
        if haversine_m(lat, lon, ex["lat"], ex["lon"]) < threshold_m:
            return True
    return False


# --- Hauptprogramm ---

def main():
    print(f"KML: {KML_PATH}")
    print(f"CSV: {CSV_PATH}")
    print()

    # 1) KML parsen
    kml_entries = parse_kml(KML_PATH)
    print(f"KML: {len(kml_entries)} Startplätze gefunden")

    # 2) Bestehende CSV lesen
    existing_rows, raw_lines = read_existing_csv(CSV_PATH)
    print(f"CSV: {len(existing_rows)} bestehende Einträge")
    print()

    # 3) Neue Einträge filtern
    new_rows = []
    skipped = 0
    for entry in kml_entries:
        if is_duplicate(entry["lat"], entry["lon"], existing_rows):
            skipped += 1
            continue

        region = kanton_to_region(entry["kanton"], entry["lat"])
        site_name = clean_site_name(entry["raw_name"], entry["gelaende"])

        new_rows.append({
            "region": region,
            "fluggebiet": entry["gelaende"],
            "site_name": site_name,
            "latitude": f"{entry['lat']:.6f}",
            "longitude": f"{entry['lon']:.6f}",
            "elevation_m": str(entry["elevation"]),
            "windrichtung": entry["startrichtung"],
            "ideal_wind_max_kmh": "30",
            "slope_azimuth": "",
            "slope_angle": "",
            "kritischer_foehn": "Süd",
            "Bemerkungen": "",
        })

    # Sortieren: region → fluggebiet → site_name
    new_rows.sort(key=lambda r: (r["region"], r["fluggebiet"], r["site_name"]))

    print(f"Übersprungen (bereits vorhanden): {skipped}")
    print(f"Neue Einträge: {len(new_rows)}")
    print(f"Total nach Import: {len(existing_rows) + len(new_rows)}")
    print()

    # 4) CSV schreiben
    # Bestehende Zeilen beibehalten + neue anhängen
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        # Bestehende Zeilen (inkl. Header) exakt übernehmen
        if raw_lines:
            for line in raw_lines:
                f.write(line + "\n")
        else:
            # Kein bestehendes CSV → Header schreiben
            writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
            writer.writeheader()

        # Neue Zeilen mit csv.writer (korrekte Quoting)
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        for row in new_rows:
            writer.writerow(row)

    # 5) Zusammenfassung nach Region
    region_counts = {}
    for row in new_rows:
        r = row["region"]
        region_counts[r] = region_counts.get(r, 0) + 1

    print("Neue Einträge nach Region:")
    for region in sorted(region_counts.keys()):
        print(f"  {region:20s}: {region_counts[region]:4d}")

    print(f"\nCSV geschrieben: {CSV_PATH}")
    print(f"Total Zeilen (inkl. Header): {len(existing_rows) + len(new_rows) + 1}")


if __name__ == "__main__":
    main()
