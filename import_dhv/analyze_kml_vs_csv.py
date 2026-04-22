#!/usr/bin/env python3
import csv, math, re, xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

KML_PATH = Path(r"C:/Users/user/OneDrive/Projekte/gleitcast/data/dhv_gelaende_2026-04-09_16.27.54.kml")
CSV_PATH = Path(r"C:/Users/user/OneDrive/Projekte/gleitcast/data/fluggebiete_complete.csv")
KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}

def haversine_m(lat1, lon1, lat2, lon2):
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def parse_description(desc_text):
    startrichtung = ""
    elevation = ""
    if not desc_text:
        return startrichtung, elevation
    m = re.search(r"Startrichtung\s+([\w\-]+)", desc_text)
    if m:
        startrichtung = m.group(1)
    m = re.search(r"[Hh].{0,4}he\s+NN\s+(\d+)\s*m", desc_text)
    if m:
        elevation = int(m.group(1))
    return startrichtung, elevation

def parse_kml(path):
    tree = ET.parse(path)
    root = tree.getroot()
    doc = root.find("kml:Document", KML_NS)
    startplaetze = []
    for schweiz_folder in doc.findall("kml:Folder", KML_NS):
        for kanton_folder in schweiz_folder.findall("kml:Folder", KML_NS):
            kanton = kanton_folder.find("kml:name", KML_NS).text.strip()
            for gelaende_folder in kanton_folder.findall("kml:Folder", KML_NS):
                gelaende = gelaende_folder.find("kml:name", KML_NS).text.strip()
                for pm in gelaende_folder.findall("kml:Placemark", KML_NS):
                    style_el = pm.find("kml:styleUrl", KML_NS)
                    if style_el is None or "startplatz" not in style_el.text:
                        continue
                    name = pm.find("kml:name", KML_NS).text.strip()
                    coords_el = pm.find(".//kml:coordinates", KML_NS)
                    if coords_el is None:
                        continue
                    parts = coords_el.text.strip().split(",")
                    lon, lat = float(parts[0]), float(parts[1])
                    desc_el = pm.find("kml:description", KML_NS)
                    desc_text = desc_el.text if desc_el is not None else ""
                    startrichtung, elevation = parse_description(desc_text)
                    startplaetze.append({
                        "kanton": kanton, "gelaende": gelaende, "site_name": name,
                        "lat": lat, "lon": lon, "elevation": elevation,
                        "startrichtung": startrichtung,
                    })
    return startplaetze

def read_csv(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            r["latitude"] = float(r["latitude"])
            r["longitude"] = float(r["longitude"])
            r["elevation_m"] = float(r["elevation_m"]) if r.get("elevation_m") else 0
            rows.append(r)
    return rows

def normalize(s):
    s = s.lower().strip()
    for suffix in [" startplatz", " start", " landeplatz"]:
        s = s.replace(suffix, "")
    s = re.sub(r"\s+\d+$", "", s)
    return s

def gelaende_matches_fluggebiet(gelaende, fluggebiet):
    g = normalize(gelaende)
    f = normalize(fluggebiet)
    if g == f:
        return True
    if g in f or f in g:
        return True
    g_words = g.split()
    f_words = f.split()
    if g_words and f_words and len(g_words[0]) >= 3 and g_words[0] == f_words[0]:
        return True
    if " / " in f:
        for part in f.split(" / "):
            part = part.strip()
            if part == g or part in g or g in part:
                return True
    return False

def site_already_in_csv(kml_entry, csv_rows):
    for csv_row in csv_rows:
        dist = haversine_m(kml_entry["lat"], kml_entry["lon"],
                           csv_row["latitude"], csv_row["longitude"])
        if dist < 500:
            return True, csv_row, dist
        kml_norm = normalize(kml_entry["site_name"])
        csv_norm = normalize(csv_row["site_name"])
        if kml_norm and csv_norm and (kml_norm in csv_norm or csv_norm in kml_norm):
            return True, csv_row, dist
    return False, None, None

def gelaende_has_proximity_match(gelaende_entries, csv_rows, threshold_m=2000):
    best_dist = float("inf")
    best_fg = None
    for kml_entry in gelaende_entries:
        for csv_row in csv_rows:
            dist = haversine_m(kml_entry["lat"], kml_entry["lon"],
                               csv_row["latitude"], csv_row["longitude"])
            if dist < best_dist:
                best_dist = dist
                best_fg = csv_row["fluggebiet"]
    if best_dist < threshold_m:
        return True, best_fg, best_dist
    return False, None, None


def main():
    SEP = "=" * 80
    print(SEP)
    print("DHV KML Startplatz-Analyse vs. fluggebiete_complete.csv")
    print(SEP)
    kml_entries = parse_kml(KML_PATH)
    csv_rows = read_csv(CSV_PATH)
    csv_fluggebiete = sorted(set(r["fluggebiet"] for r in csv_rows))
    print()
    print("KML: %d Startplaetze gefunden" % len(kml_entries))
    print("CSV: %d Eintraege in %d Fluggebieten" % (len(csv_rows), len(csv_fluggebiete)))
    gelaende_groups = defaultdict(list)
    for entry in kml_entries:
        gelaende_groups[entry["gelaende"]].append(entry)
    section_a = defaultdict(list)
    section_b = defaultdict(lambda: defaultdict(list))
    matched_gelaende = {}
    for gelaende, entries in gelaende_groups.items():
        matched_fg = None
        match_type = None
        for fg in csv_fluggebiete:
            if gelaende_matches_fluggebiet(gelaende, fg):
                matched_fg = fg
                match_type = "name"
                break
        if matched_fg is None:
            has_prox, prox_fg, prox_dist = gelaende_has_proximity_match(entries, csv_rows, 2000)
            if has_prox:
                matched_fg = prox_fg
                match_type = "proximity (%dm)" % int(prox_dist)
        if matched_fg:
            matched_gelaende[gelaende] = (matched_fg, match_type)
            for entry in entries:
                already_exists, csv_match, dist = site_already_in_csv(entry, csv_rows)
                if not already_exists:
                    entry["_matched_fluggebiet"] = matched_fg
                    section_a[matched_fg].append(entry)
        else:
            kanton = entries[0]["kanton"]
            section_b[kanton][gelaende] = entries
    print()
    print()
    print(SEP)
    print("SECTION A: Zusaetzliche Startplaetze bei bestehenden Fluggebieten")
    print(SEP)
    total_a = 0
    for fg in sorted(section_a.keys()):
        entries = section_a[fg]
        total_a += len(entries)
        print()
        print("--- Fluggebiet: %s (%d neue Startplaetze) ---" % (fg, len(entries)))
        gelaende_names = sorted(set(e["gelaende"] for e in entries))
        gn_str = ", ".join(gelaende_names)
        print("    KML-Gelaende: %s" % gn_str)
        for e in entries:
            elev_str = str(e["elevation"]) + "m" if e["elevation"] else "?"
            print("    %-45s  lat=%.4f  lon=%.4f  elev=%6s  richtung=%s" % (
                e["site_name"], e["lat"], e["lon"], elev_str, e["startrichtung"]))
    print()
    print(">>> Section A Total: %d neue Startplaetze bei %d bestehenden Fluggebieten" % (total_a, len(section_a)))
    print()
    print()
    print(SEP)
    print("SECTION B: Komplett neue Fluggebiete (nicht in CSV)")
    print(SEP)
    total_b_gelaende = 0
    total_b_starts = 0
    for kanton in sorted(section_b.keys()):
        gelaende_dict = section_b[kanton]
        kanton_starts = sum(len(v) for v in gelaende_dict.values())
        total_b_gelaende += len(gelaende_dict)
        total_b_starts += kanton_starts
        print()
        print("=== Kanton: %s (%d Gelaende, %d Startplaetze) ===" % (kanton, len(gelaende_dict), kanton_starts))
        for gelaende in sorted(gelaende_dict.keys()):
            entries = gelaende_dict[gelaende]
            print()
            print("  Gelaende: %s (%d Startplaetze)" % (gelaende, len(entries)))
            for e in entries:
                elev_str = str(e["elevation"]) + "m" if e["elevation"] else "?"
                print("    %-45s  lat=%.4f  lon=%.4f  elev=%6s  richtung=%s" % (
                    e["site_name"], e["lat"], e["lon"], elev_str, e["startrichtung"]))
    print()
    print(">>> Section B Total: %d Startplaetze in %d neuen Gelaenden" % (total_b_starts, total_b_gelaende))
    print()
    print()
    print(SEP)
    print("ZUSAMMENFASSUNG")
    print(SEP)
    already_in = len(kml_entries) - total_a - total_b_starts
    print("KML Startplaetze gesamt:           %d" % len(kml_entries))
    print("Bereits in CSV (uebersprungen):    %d" % already_in)
    print("Section A (neue bei bestehenden):  %d Startplaetze bei %d Fluggebieten" % (total_a, len(section_a)))
    print("Section B (komplett neue):         %d Startplaetze in %d Gelaenden" % (total_b_starts, total_b_gelaende))
    print()
    print("--- Gelaende-zu-Fluggebiet Zuordnungen (%d) ---" % len(matched_gelaende))
    for g in sorted(matched_gelaende.keys()):
        fg, mt = matched_gelaende[g]
        print("  %-35s -> %-30s [%s]" % (g, fg, mt))

if __name__ == "__main__":
    main()
