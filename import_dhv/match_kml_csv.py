
#\!/usr/bin/env python
# -*- coding: utf-8 -*-
# match_kml_csv.py - Match CSV with DHV KML Gelaende-Datenbank.

import sys, io, os, csv, re, math
import xml.etree.ElementTree as ET
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KML_PATH = os.path.join(BASE_DIR, "dhv_gelaende_2026-04-09_16.27.54.kml")
CSV_PATH = os.path.join(BASE_DIR, "fluggebiete_complete.csv")
NS = {"kml": "http://www.opengis.net/kml/2.2"}
CSV_COLUMNS = ["region", "fluggebiet", "site_name", "latitude", "longitude",
    "elevation_m", "windrichtung", "ideal_wind_max_kmh", "slope_azimuth",
    "slope_angle", "kritischer_foehn", "Bemerkungen"]



def haversine_m(lat1, lon1, lat2, lon2):
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def trigrams(s):
    s = s.lower().strip()
    return set(s[i:i+3] for i in range(max(0, len(s)-2)))


def name_similarity(a, b):
    ta, tb = trigrams(a), trigrams(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def parse_kml(path):
    tree = ET.parse(path)
    root = tree.getroot()
    entries = []
    doc = root.find("kml:Document", NS)
    schweiz = doc.find("kml:Folder", NS)
    if schweiz is None:
        print("ERROR: Could not find Schweiz folder in KML")
        return entries
    for kanton_folder in schweiz.findall("kml:Folder", NS):
        kanton_name = kanton_folder.find("kml:name", NS).text or ""
        for gelaende_folder in kanton_folder.findall("kml:Folder", NS):
            gelaende_name = gelaende_folder.find("kml:name", NS).text or ""
            for pm in gelaende_folder.findall("kml:Placemark", NS):
                pm_name_el = pm.find("kml:name", NS)
                pm_name = pm_name_el.text if pm_name_el is not None else ""
                style_url = pm.find("kml:styleUrl", NS)
                is_start = ("Startplatz" in pm_name or
                            (style_url is not None and
                             "startplatz" in (style_url.text or "").lower()))
                if not is_start:
                    continue
                coords_el = pm.find(".//kml:coordinates", NS)
                if coords_el is None or not coords_el.text:
                    continue
                parts = coords_el.text.strip().split(",")
                try:
                    lon = float(parts[0])
                    lat = float(parts[1])
                except (ValueError, IndexError):
                    continue
                desc_el = pm.find("kml:description", NS)
                desc = desc_el.text if desc_el is not None else ""
                elevation_m = None
                startrichtung = ""
                gemeinde = ""
                elev_match = re.search(r"H\S*he\s+NN\s+(\d+)\s*m", desc)
                if elev_match:
                    elevation_m = int(elev_match.group(1))
                sr_match = re.search(r"Startrichtung\s+([\w\-]+)", desc)
                if sr_match:
                    startrichtung = sr_match.group(1)
                gem_match = re.search(r"Gemeinde\s+([^,<]+)", desc)
                if gem_match:
                    gemeinde = gem_match.group(1).strip()
                entries.append({
                    "name": pm_name, "lat": lat, "lon": lon,
                    "elevation_m": elevation_m, "startrichtung": startrichtung,
                    "gemeinde": gemeinde, "gelaende_name": gelaende_name,
                    "kanton": kanton_name,
                })
    return entries


def parse_csv(path):
    rows = []
    raw_lines = None
    for enc in ["utf-8", "latin-1", "cp1252"]:
        try:
            with open(path, "r", encoding=enc, errors="replace") as f:
                raw_lines = f.readlines()
            break
        except Exception:
            continue
    if not raw_lines:
        print("ERROR: Could not read CSV file")
        return rows
    for line_num, line in enumerate(raw_lines[1:], start=1):
        line = line.strip()
        if not line:
            continue
        try:
            reader = csv.reader(io.StringIO(line))
            fields = next(reader)
        except Exception:
            fields = line.split(",")
        row = {}
        for i, col in enumerate(CSV_COLUMNS):
            if i < len(fields):
                row[col] = fields[i].strip()
            else:
                row[col] = ""
        row["_line_num"] = line_num
        rows.append(row)
    return rows


def find_best_match(csv_row, kml_entries):
    csv_name = csv_row.get("site_name", "")
    csv_fluggebiet = csv_row.get("fluggebiet", "")
    csv_lat = csv_lon = None
    try:
        csv_lat = float(csv_row.get("latitude", ""))
        csv_lon = float(csv_row.get("longitude", ""))
    except (ValueError, TypeError):
        pass
    coord_broken = False
    if csv_lon is not None and (csv_lon > 180 or csv_lon < -180):
        coord_broken = True
    if csv_lat is not None and (csv_lat > 90 or csv_lat < -90):
        coord_broken = True

    # Pass 1: Name matching
    best_nm = None
    best_ns = 0.0
    for kml in kml_entries:
        kn_clean = re.sub(r"\s*Startplatz\s*\d*$", "", kml["name"]).strip()
        s1 = name_similarity(csv_name, kn_clean)
        s2 = name_similarity(csv_name, kml["gelaende_name"])
        s3 = name_similarity(csv_fluggebiet, kml["gelaende_name"])
        cl = csv_name.lower()
        kl = kn_clean.lower()
        gl = kml["gelaende_name"].lower()
        bonus = 0.0
        if cl and kl:
            if cl in kl or kl in cl: bonus = max(bonus, 0.3)
            if cl == kl: bonus = max(bonus, 0.5)
        if cl and gl:
            if cl in gl or gl in cl: bonus = max(bonus, 0.2)
        fl = csv_fluggebiet.lower()
        if fl and gl:
            if fl in gl or gl in fl: bonus = max(bonus, 0.15)
        score = max(s1, s2) + bonus
        if s3 > 0.5: score += 0.1
        if score > best_ns:
            best_ns = score
            best_nm = kml
    if best_ns >= 0.45 and best_nm:
        return best_nm, "NAME", best_ns

    # Pass 2: Proximity (within 500m)
    if csv_lat is not None and csv_lon is not None and not coord_broken:
        best_p = None
        best_d = float("inf")
        for kml in kml_entries:
            d = haversine_m(csv_lat, csv_lon, kml["lat"], kml["lon"])
            if d < best_d:
                best_d = d
                best_p = kml
        if best_d <= 500 and best_p:
            return best_p, "PROXIMITY", best_d

    # Pass 3: Combined
    if csv_lat is not None and csv_lon is not None and not coord_broken:
        best_c = None
        best_cs = 0.0
        for kml in kml_entries:
            kn_clean = re.sub(r"\s*Startplatz\s*\d*$", "", kml["name"]).strip()
            ns = max(name_similarity(csv_name, kn_clean),
                     name_similarity(csv_name, kml["gelaende_name"]),
                     name_similarity(csv_fluggebiet, kml["gelaende_name"]))
            d = haversine_m(csv_lat, csv_lon, kml["lat"], kml["lon"])
            if d < 2000 and ns > 0.2:
                cs = ns + max(0, (2000 - d) / 2000) * 0.3
                if cs > best_cs:
                    best_cs = cs
                    best_c = kml
        if best_c and best_cs >= 0.4:
            return best_c, "COMBINED", best_cs

    return None, None, None


def check_data_quality(csv_row):
    issues = []
    try:
        lon = float(csv_row.get("longitude", "") or "0")
        if lon > 180 or lon < -180:
            if 700000 < lon < 800000:
                issues.append(
                    "BROKEN longitude=%s (likely missing decimal, should be ~%.5f)"
                    % (lon, lon / 100000))
            else:
                issues.append("BROKEN longitude=%s (out of range)" % lon)
    except ValueError:
        if csv_row.get("longitude", ""):
            issues.append("Non-numeric longitude")
    try:
        lat = float(csv_row.get("latitude", "") or "0")
        if lat != 0 and (lat < 45.5 or lat > 48.0):
            issues.append("Latitude %s outside Swiss range (45.5-48.0)" % lat)
    except ValueError:
        if csv_row.get("latitude", ""):
            issues.append("Non-numeric latitude")
    try:
        elev = float(csv_row.get("elevation_m", "") or "0")
        if elev != 0 and (elev < 200 or elev > 4500):
            issues.append("Elevation %sm outside plausible range" % elev)
    except ValueError:
        pass
    return issues


def main():
    SEP = "=" * 90
    DASH = "-" * 90
    SQ = chr(39)
    print(SEP)
    print("  KML <-> CSV Matching Report")
    print(SEP)
    print()

    print("Reading KML: %s" % KML_PATH)
    kml_entries = parse_kml(KML_PATH)
    print("  Found %d Startplatz entries in KML" % len(kml_entries))
    print()

    print("Reading CSV: %s" % CSV_PATH)
    csv_rows = parse_csv(CSV_PATH)
    print("  Found %d data rows in CSV" % len(csv_rows))
    print()

    matched = 0
    unmatched = 0
    match_types = defaultdict(int)
    missing_by_col = defaultdict(int)
    quality_issues = []
    all_results = []

    print(DASH)
    print("  DETAILED COMPARISON")
    print(DASH)

    for csv_row in csv_rows:
        line = csv_row["_line_num"]
        site = csv_row.get("site_name", "(empty)")
        flug = csv_row.get("fluggebiet", "(empty)")
        region = csv_row.get("region", "(empty)")

        kml_match, match_type, match_score = find_best_match(csv_row, kml_entries)

        empty_cols = []
        for col in CSV_COLUMNS:
            val = csv_row.get(col, "")
            if val == "" or val is None:
                empty_cols.append(col)
                missing_by_col[col] += 1

        dq_issues = check_data_quality(csv_row)
        if dq_issues:
            quality_issues.append((line, site, dq_issues))

        print()
        print("  CSV Row %2d: %s / %s / %s" % (line, region, flug, site))

        if kml_match:
            matched += 1
            match_types[match_type] += 1

            kn = kml_match["name"]
            kg = kml_match["gelaende_name"]
            kk = kml_match["kanton"]
            klat = kml_match["lat"]
            klon = kml_match["lon"]
            ke = kml_match["elevation_m"]
            ksr = kml_match["startrichtung"]
            kgm = kml_match["gemeinde"]

            if match_type == "NAME":
                ss = "name similarity=%.2f" % match_score
            elif match_type == "PROXIMITY":
                ss = "distance=%.0fm" % match_score
            else:
                ss = "combined score=%.2f" % match_score

            print("  KML Match: %s  [%s, %s]" % (kn, match_type, ss))
            print("             Gelaende: %s, Kanton: %s" % (kg, kk))

            # Coordinate comparison
            try:
                clat = float(csv_row.get("latitude", "") or "0")
                clon = float(csv_row.get("longitude", "") or "0")
                if clat != 0 and clon != 0 and clon < 180:
                    dist = haversine_m(clat, clon, klat, klon)
                    if dist > 50:
                        print("  COORD DIFF: CSV (%.5f, %.5f) vs KML (%.6f, %.6f) = %.0fm apart"
                              % (clat, clon, klat, klon, dist))
                    else:
                        print("  Coordinates: match within %.0fm (OK)" % dist)
                else:
                    print("  CSV coords: (%s, %s) -- broken or zero" % (clat, clon))
                    print("  KML coords: (%.6f, %.6f)" % (klat, klon))
            except (ValueError, TypeError):
                print("  CSV coords: unparseable")
                print("  KML coords: (%.6f, %.6f)" % (klat, klon))

            # Elevation comparison
            ce = csv_row.get("elevation_m", "")
            if ce and ke is not None:
                try:
                    diff = abs(float(ce) - ke)
                    if diff > 20:
                        print("  ELEV DIFF:  CSV %sm vs KML %sm (diff=%.0fm)" % (ce, ke, diff))
                    else:
                        print("  Elevation:  CSV %sm vs KML %sm (OK, diff=%.0fm)" % (ce, ke, diff))
                except ValueError:
                    pass
            elif not ce and ke is not None:
                print("  ELEV MISSING in CSV -- KML has: %sm" % ke)
            elif ce and ke is None:
                print("  Elevation: CSV %sm, KML has no elevation data" % ce)

            # Windrichtung comparison
            cw = csv_row.get("windrichtung", "")
            if cw and ksr:
                if cw.lower().replace(" ", "") != ksr.lower().replace(" ", ""):
                    print("  WIND DIR:   CSV %s%s%s vs KML Startrichtung %s%s%s" % (SQ, cw, SQ, SQ, ksr, SQ))
                else:
                    print("  Wind dir:   %s%s%s matches KML (OK)" % (SQ, cw, SQ))
            elif not cw and ksr:
                print("  WIND MISSING in CSV -- KML Startrichtung: %s%s%s" % (SQ, ksr, SQ))

            if kgm:
                print("  KML extra:  Gemeinde=%s" % kgm)

            if empty_cols:
                print("  EMPTY CSV cols: %s" % ", ".join(empty_cols))

            fillable = []
            if "elevation_m" in empty_cols and ke is not None:
                fillable.append("elevation_m=%s" % ke)
            if "windrichtung" in empty_cols and ksr:
                fillable.append("windrichtung=%s%s%s" % (SQ, ksr, SQ))
            if "latitude" in empty_cols:
                fillable.append("latitude=%.6f" % klat)
            if "longitude" in empty_cols:
                fillable.append("longitude=%.6f" % klon)
            if fillable:
                print("  KML CAN FILL: %s" % ", ".join(fillable))

        else:
            unmatched += 1
            print("  *** NO KML MATCH FOUND ***")
            if empty_cols:
                print("  EMPTY CSV cols: %s" % ", ".join(empty_cols))

        if dq_issues:
            for issue in dq_issues:
                print("  !! DATA QUALITY: %s" % issue)

        all_results.append({
            "line": line, "csv_name": site, "kml_match": kml_match,
            "match_type": match_type, "empty_cols": empty_cols,
        })

    # Summary
    print()
    print(SEP)
    print("  SUMMARY")
    print(SEP)
    print()
    print("  Total CSV rows:          %d" % len(csv_rows))
    print("  Matched to KML:          %d" % matched)
    print("  Unmatched:               %d" % unmatched)
    print()
    print("  Match breakdown:")
    for mt, count in sorted(match_types.items()):
        print("    %-12s: %d" % (mt, count))
    print()

    print("  Missing data by column (out of %d rows):" % len(csv_rows))
    for col in CSV_COLUMNS:
        count = missing_by_col.get(col, 0)
        if count > 0:
            pct = count / len(csv_rows) * 100
            bar = "#" * int(pct / 2)
            print("    %-25s: %3d missing (%5.1f%%) %s" % (col, count, pct, bar))

    if quality_issues:
        print()
        print("  DATA QUALITY ISSUES (%d rows):" % len(quality_issues))
        for line, site, issues in quality_issues:
            for issue in issues:
                print("    Row %2d (%s): %s" % (line, site, issue))

    unmatched_rows = [r for r in all_results if r["kml_match"] is None]
    if unmatched_rows:
        print()
        print("  UNMATCHED CSV ROWS (%d):" % len(unmatched_rows))
        for r in unmatched_rows:
            print("    Row %2d: %s" % (r["line"], r["csv_name"]))

    print()
    print(SEP)
    print("  Done.")
    print(SEP)


if __name__ == "__main__":
    main()
