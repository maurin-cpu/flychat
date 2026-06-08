"""
Parse DHV Gelaende KML file to extract all Startplaetze with metadata.
Structure: Document > Folder(country) > Folder(kanton) > Folder(gelaende) > Placemark(startplatz)
"""

import xml.etree.ElementTree as ET
import re
import html

KML_FILE = r"C:\Users\user\OneDrive\Projekte\wingcast\data\dhv_gelaende_2026-04-09_16.27.54.kml"
NS = {"kml": "http://www.opengis.net/kml/2.2"}


def parse_description(desc_text):
    """Extract Hoehe, Startrichtung, and Gemeinde from CDATA description text."""
    if not desc_text:
        return None, None, None

    # Decode HTML entities
    text = html.unescape(desc_text)

    # Extract Hoehe NN XXXm (may have spaces, handle encoding variants)
    elevation = None
    m = re.search(r"H[oö\u00f6]he\s+NN\s+(\d+)\s*m", text)
    if not m:
        # Try broader pattern for encoding issues
        m = re.search(r"H.{1,3}he\s+NN\s+(\d+)\s*m", text)
    if m:
        elevation = int(m.group(1))

    # Extract Startrichtung
    startrichtung = None
    m = re.search(r"Startrichtung\s+([A-Za-z\-]+)", text)
    if m:
        startrichtung = m.group(1).strip()

    # Extract Gemeinde
    gemeinde = None
    m = re.search(r"Gemeinde\s+([^,<]+)", text)
    if m:
        gemeinde = m.group(1).strip()

    return elevation, startrichtung, gemeinde


def main():
    tree = ET.parse(KML_FILE)
    root = tree.getroot()

    results = []

    # Find the top-level Document
    doc = root.find("kml:Document", NS)
    if doc is None:
        doc = root

    # Iterate: Country > Kanton > Gelaende > Placemark
    # Top-level folders under Document are countries (e.g., "Schweiz")
    for country_folder in doc.findall("kml:Folder", NS):
        country_name = country_folder.findtext("kml:name", default="", namespaces=NS)

        for kanton_folder in country_folder.findall("kml:Folder", NS):
            kanton_name = kanton_folder.findtext("kml:name", default="", namespaces=NS)

            for gelaende_folder in kanton_folder.findall("kml:Folder", NS):
                gelaende_name = gelaende_folder.findtext("kml:name", default="", namespaces=NS)

                for placemark in gelaende_folder.findall("kml:Placemark", NS):
                    style_url = placemark.findtext("kml:styleUrl", default="", namespaces=NS)

                    # Only Startplaetze
                    if "startplatz" not in style_url.lower():
                        continue

                    site_name = placemark.findtext("kml:name", default="", namespaces=NS)

                    # Get coordinates
                    point = placemark.find("kml:Point", NS)
                    lat, lon = "", ""
                    if point is not None:
                        coords_text = point.findtext("kml:coordinates", default="", namespaces=NS).strip()
                        if coords_text:
                            parts = coords_text.split(",")
                            if len(parts) >= 2:
                                lon = parts[0].strip()
                                lat = parts[1].strip()

                    # Parse description
                    desc = placemark.findtext("kml:description", default="", namespaces=NS)
                    elevation, startrichtung, gemeinde = parse_description(desc)

                    results.append({
                        "kanton": kanton_name,
                        "gelaende": gelaende_name,
                        "site_name": site_name,
                        "lat": lat,
                        "lon": lon,
                        "elevation": elevation,
                        "startrichtung": startrichtung,
                        "gemeinde": gemeinde,
                    })

    # Print header
    header = "Kanton | Gelaende | Site Name | Lat | Lon | Elevation (m) | Startrichtung | Gemeinde"
    print(header)
    print("-" * len(header))

    for r in results:
        print(
            f"{r['kanton']} | "
            f"{r['gelaende']} | "
            f"{r['site_name']} | "
            f"{r['lat']} | "
            f"{r['lon']} | "
            f"{r['elevation'] or 'N/A'} | "
            f"{r['startrichtung'] or 'N/A'} | "
            f"{r['gemeinde'] or 'N/A'}"
        )

    print(f"\n{'='*60}")
    print(f"Total Startplaetze found: {len(results)}")
    print(f"{'='*60}")

    # Summary stats
    kantone = set(r["kanton"] for r in results)
    gelaende = set(r["gelaende"] for r in results)
    print(f"\nUnique Kantone: {len(kantone)}")
    print(f"Unique Gelaende: {len(gelaende)}")

    with_elevation = sum(1 for r in results if r["elevation"] is not None)
    with_direction = sum(1 for r in results if r["startrichtung"] is not None)
    with_gemeinde = sum(1 for r in results if r["gemeinde"] is not None)
    print(f"With elevation: {with_elevation}/{len(results)}")
    print(f"With Startrichtung: {with_direction}/{len(results)}")
    print(f"With Gemeinde: {with_gemeinde}/{len(results)}")


if __name__ == "__main__":
    main()
