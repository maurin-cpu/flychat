#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Baut die persistente Alias-Tabelle XContest-Startplatzname -> unsere Spot-/Region-Ebene.

Hintergrund: 40% der Zeilen in validation/xcontest/observations.csv sind
`coverage_gap` — der XContest-Name liess sich nicht auf einen DB-Spot mappen.
Das hat drei verschiedene Ursachen (I-009), die dieses Skript trennt:

  1. Naming-Drift  — Spot ist in der PGE-DB, heisst dort nur anders
  2. Truncation    — XContest liefert abgeschnittene Namen ("Luegibrue...")
  3. Echte Luecke  — Spot existiert bei uns gar nicht

Fuer 2. und 3. ist Spot-Validierung unmoeglich, **Region-Validierung aber schon**:
sobald wir irgendeine Koordinate zum Namen finden (Alt-DB DHV oder OSM-Gipfel),
liefert Punkt-in-Polygon gegen data/regionen_polygone_mapped.geojson die Region.

Output: validation/xcontest/spot_aliases.csv (ueberschrieben, deterministisch)
"""
from __future__ import annotations

import csv
import glob
import io
import json
import math
import os
import sys
import unicodedata
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from spots import sanitize_spot_name  # noqa: E402  (Schluessel-Konvention der Archive)

OBS = os.path.join(ROOT, "validation/xcontest", "observations.csv")
OUT = os.path.join(ROOT, "validation/xcontest", "spot_aliases.csv")
PGE = os.path.join(ROOT, "data", "fluggebiete_pge.csv")
DHV = os.path.join(ROOT, "data", "fluggebiete_dhv.backup_pre_pge.csv")
POLY = os.path.join(ROOT, "data", "regionen_polygone_mapped.geojson")
PEAKS = [
    os.path.join(ROOT, "data", "osm_peaks_major.geojson"),
    os.path.join(ROOT, "data", "osm_peaks_minor.geojson"),
]
ARCHIVE = os.path.join(ROOT, "data", "weather_archive")

MIN_PREFIX = 5      # kuerzere Fragmente sind zu mehrdeutig zum Prefix-Matchen
FAR_KM = 15.0       # Treffer weiter weg von jedem bekannten Startplatz = verdaechtig


# --------------------------------------------------------------------------
# Normalisierung
# --------------------------------------------------------------------------

UMLAUT = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
          "Ä": "ae", "Ö": "oe", "Ü": "ue"}


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def norm_variants(name: str) -> set:
    """Zwei Lesarten: Akzente weg (Muenchen-Stil 'u') und Umlaut-Expansion ('ue').

    Amisbuehl (DB) und Amisbühl (XContest) matchen nur ueber die zweite.
    """
    base = (name or "").strip().rstrip(".").strip()
    expanded = "".join(UMLAUT.get(c, c) for c in base)
    out = set()
    for cand in (base, expanded):
        folded = _strip_accents(cand).lower()
        out.add("".join(ch for ch in folded if ch.isalnum()))
    return {v for v in out if v}


def is_truncated(name: str) -> bool:
    return name.rstrip().endswith("..")


# --------------------------------------------------------------------------
# Geometrie
# --------------------------------------------------------------------------

def load_regions():
    with io.open(POLY, encoding="utf-8") as fh:
        gj = json.load(fh)
    regions = []
    for feat in gj["features"]:
        geom = feat["geometry"]
        rings = [geom["coordinates"][0]] if geom["type"] == "Polygon" else \
                [p[0] for p in geom["coordinates"]]
        xs = [pt[0] for ring in rings for pt in ring]
        ys = [pt[1] for ring in rings for pt in ring]
        regions.append({
            "name": feat["properties"]["region"],
            "rings": rings,
            "bbox": (min(xs), min(ys), max(xs), max(ys)),
        })
    return regions


def point_in_ring(lon, lat, ring) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


def region_of(lon, lat, regions):
    for r in regions:
        x0, y0, x1, y1 = r["bbox"]
        if not (x0 <= lon <= x1 and y0 <= lat <= y1):
            continue
        if any(point_in_ring(lon, lat, ring) for ring in r["rings"]):
            return r["name"]
    return ""


# --------------------------------------------------------------------------
# Namensquellen
# --------------------------------------------------------------------------

def load_csv_source(path, label):
    """PGE/DHV-CSV -> Liste von Kandidaten mit Koordinate."""
    out = []
    with io.open(path, encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            name = (row.get("site_name") or "").strip()
            if not name:
                continue
            try:
                lat = float(row["latitude"])
                lon = float(row["longitude"])
            except (TypeError, ValueError, KeyError):
                lat = lon = None
            out.append({
                "source": label,
                # Archiv- und Analyse-Keys tragen den sanitisierten Namen
                # ("Riederalp/ Greicheralp" -> "Riederalp- Greicheralp").
                # Roh-vs-sanitisiert-Vergleiche erzeugen sonst Phantom-Luecken.
                "name": sanitize_spot_name(name),
                "raw_name": name,
                "group": (row.get("fluggebiet") or "").strip(),
                "csv_region": (row.get("region") or "").strip(),
                "lat": lat, "lon": lon,
            })
    return out


def load_peaks():
    out = []
    for path in PEAKS:
        if not os.path.exists(path):
            continue
        with io.open(path, encoding="utf-8") as fh:
            gj = json.load(fh)
        for feat in gj["features"]:
            name = (feat.get("properties") or {}).get("name")
            geom = feat.get("geometry") or {}
            if not name or geom.get("type") != "Point":
                continue
            lon, lat = geom["coordinates"][0], geom["coordinates"][1]
            out.append({"source": "osm_peak", "name": name.strip(), "group": "",
                        "csv_region": "", "lat": lat, "lon": lon})
    return out


def build_index(entries):
    idx = defaultdict(list)
    for e in entries:
        for v in norm_variants(e["name"]):
            idx[v].append(e)
    return idx


def lookup(query_variants, idx, truncated):
    """Exakt zuerst, dann Prefix (fuer abgeschnittene Namen), dann Containment."""
    hits, how = [], ""
    for v in query_variants:
        hits.extend(idx.get(v, []))
    if hits:
        return dedupe(hits), "exact"

    usable = [v for v in query_variants if len(v) >= MIN_PREFIX]
    if usable:
        for key, entries in idx.items():
            if any(key.startswith(v) for v in usable):
                hits.extend(entries)
        if hits:
            return dedupe(hits), "prefix"

    if not truncated and usable:
        # DB-Name enthaelt den XContest-Namen als Wortteil
        # (Pizol -> "Wangs -Pizolbahn Endstation")
        for key, entries in idx.items():
            if any(v in key for v in usable):
                hits.extend(entries)
        if hits:
            return dedupe(hits), "contains"
    return [], how


def load_archive_regions():
    """site_name -> analyse_region aus dem juengsten weather_archive-Snapshot.

    Die `region`-Spalte der PGE-CSV ist die DHV-Gebietsbezeichnung ("Schwyz",
    "Berneroberland") und NICHT die Analyse-Region des Modells. Massgeblich fuer
    jede Region-Aussage ist `analyse_region` im Snapshot.
    """
    files = sorted(glob.glob(os.path.join(ARCHIVE, "*.json")))
    if not files:
        return {}
    with io.open(files[-1], encoding="utf-8") as fh:
        snap = json.load(fh)
    out = {}
    for name, spot in (snap.get("spots") or {}).items():
        reg = spot.get("analyse_region")
        if reg:
            out[name] = reg
    return out


def km_between(lat1, lon1, lat2, lon2):
    """Aequirektangulaere Naeherung — auf Schweizer Distanzen genau genug."""
    mlat = math.radians((lat1 + lat2) / 2.0)
    dx = (lon2 - lon1) * 111.32 * math.cos(mlat)
    dy = (lat2 - lat1) * 110.57
    return math.hypot(dx, dy)


def nearest_site(lat, lon, sites):
    best = (None, 1e9)
    for s in sites:
        d = km_between(lat, lon, s["lat"], s["lon"])
        if d < best[1]:
            best = (s, d)
    return best


def confidence_of(source, how, n_cand, far):
    """high  = eindeutiger Treffer in einer Startplatz-DB, Name deckungsgleich
    medium  = Startplatz-DB, aber ueber Prefix/Teilstring erschlossen
    low     = nur ueber OSM-Gipfelnamen aufgeloest, oder mehrdeutig, oder der
              Treffer liegt weit weg von jedem bekannten Startplatz
    """
    if far or n_cand > 1:
        return "low"
    if source in ("pge", "dhv_alt"):
        return "high" if how == "exact" else "medium"
    if source == "osm_peak":
        return "medium" if how == "exact" else "low"
    return ""


def dedupe(entries):
    seen, out = set(), []
    for e in entries:
        key = (e["source"], e["name"])
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


# --------------------------------------------------------------------------
# Hauptlauf
# --------------------------------------------------------------------------

def main():
    regions = load_regions()
    pge = load_csv_source(PGE, "pge")
    dhv = load_csv_source(DHV, "dhv_alt")
    peaks = load_peaks()

    arch_regions = load_archive_regions()
    for e in pge:
        e["analyse_region"] = arch_regions.get(e["name"], "")

    pge_names = {v for e in pge for v in norm_variants(e["name"])}
    dhv_only = [e for e in dhv if not (norm_variants(e["name"]) & pge_names)]

    # Referenzmenge fuer den Plausibilitaetscheck: alle bekannten Startplaetze
    known_sites = [e for e in (pge + dhv)
                   if e["lat"] is not None and e["lon"] is not None]

    idx_pge = build_index(pge)
    idx_dhv = build_index(dhv_only)
    idx_peak = build_index(peaks)

    # XContest-Namen aus den Gap-Zeilen einsammeln (+ Kontext)
    stats = defaultdict(lambda: {"rows": 0, "launches": 0, "best_km": 0.0,
                                 "regions": Counter(), "dates": set()})
    with io.open(OBS, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("finding_type") != "coverage_gap":
                continue
            s = stats[row["spot"].strip()]
            s["rows"] += 1
            s["dates"].add(row.get("date", ""))
            try:
                s["launches"] += int(row.get("launches") or 0)
            except ValueError:
                pass
            try:
                s["best_km"] = max(s["best_km"], float(row.get("best_km") or 0))
            except ValueError:
                pass
            if row.get("region"):
                s["regions"][row["region"]] += 1

    out_rows = []
    for xc_name in sorted(stats, key=lambda n: (-stats[n]["rows"], n)):
        s = stats[xc_name]
        variants = norm_variants(xc_name)
        trunc = is_truncated(xc_name)

        status = "unresolved"
        matched, how, source = [], "", ""
        for idx, src in ((idx_pge, "pge"), (idx_dhv, "dhv_alt"), (idx_peak, "osm_peak")):
            matched, how = lookup(variants, idx, trunc)
            if matched:
                source = src
                break

        cands = [m["name"] for m in matched]
        lat = lon = None
        pip = ""
        near_name, near_km, near_region = "", "", ""
        if matched:
            groups = {m["group"] for m in matched if m["group"]}
            if len(matched) == 1:
                pick = matched[0]
                status = "resolved_spot" if source == "pge" else "region_only"
            elif source == "pge" and len(groups) == 1:
                pick = matched[0]
                status = "ambiguous_variant"   # gleiches Fluggebiet, Startvariante offen
            else:
                pick = matched[0]
                status = "ambiguous"
            lat, lon = pick["lat"], pick["lon"]
            if lat is not None and lon is not None:
                pip = region_of(lon, lat, regions)
                # Bei Mehrdeutigkeit: Region trotzdem eindeutig, wenn alle
                # Kandidaten im selben Polygon liegen.
                if status.startswith("ambiguous"):
                    pips = {region_of(m["lon"], m["lat"], regions)
                            for m in matched
                            if m["lat"] is not None and m["lon"] is not None}
                    pips.discard("")
                    pip = pips.pop() if len(pips) == 1 else ""
                site, dist = nearest_site(lat, lon, known_sites)
                if site is not None:
                    near_name = site["name"]
                    near_km = "%.1f" % dist
                    near_region = site.get("analyse_region") or \
                        arch_regions.get(site["name"], "")

        far = bool(near_km) and float(near_km) > FAR_KM
        conf = confidence_of(source, how, len(matched), far)
        if far and status in ("resolved_spot", "region_only"):
            status = "suspect_match"

        # Bei sicher aufgeloesten DB-Spots ist analyse_region massgeblich,
        # nicht das Polygon (identisch in 476/494 Faellen, siehe PATTERNS).
        if status == "resolved_spot" and matched:
            ar = matched[0].get("analyse_region") or ""
            if ar:
                pip = ar

        rec_region = s["regions"].most_common(1)[0][0] if s["regions"] else ""
        if status == "unresolved":
            region_verdict = "no_coords"
        elif not pip:
            region_verdict = "ambiguous_region"
        elif not rec_region:
            region_verdict = "new"
        elif rec_region == pip:
            region_verdict = "agrees"
        else:
            region_verdict = "CONFLICT"

        out_rows.append({
            "xc_name": xc_name,
            "obs_rows": s["rows"],
            "obs_launches": s["launches"],
            "obs_best_km": "%.2f" % s["best_km"],
            "truncated": "yes" if trunc else "no",
            "status": status,
            "confidence": conf,
            "match_source": source,
            "match_how": how,
            "n_candidates": len(matched),
            "db_name": cands[0] if cands else "",
            "all_candidates": " | ".join(cands[:6]),
            "lat": "" if lat is None else "%.5f" % lat,
            "lon": "" if lon is None else "%.5f" % lon,
            "nearest_site": near_name,
            "nearest_site_km": near_km,
            "nearest_site_region": near_region,
            "region_pip": pip,
            "region_recorded": rec_region,
            "region_verdict": region_verdict,
        })

    cols = list(out_rows[0].keys())
    with io.open(OUT, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(out_rows)

    # ---- Digest ----
    def rows_for(pred):
        sel = [r for r in out_rows if pred(r)]
        return len(sel), sum(r["obs_rows"] for r in sel)

    print("Alias-Tabelle: %s" % OUT)
    print("XContest-Namen ohne Spot-Match: %d (= %d observations-Zeilen)"
          % (len(out_rows), sum(r["obs_rows"] for r in out_rows)))
    print("")
    print("%-20s %8s %8s" % ("status", "namen", "zeilen"))
    for st in ("resolved_spot", "ambiguous_variant", "ambiguous", "region_only",
               "suspect_match", "unresolved"):
        n, rws = rows_for(lambda r, st=st: r["status"] == st)
        print("%-20s %8d %8d" % (st, n, rws))
    print("")
    print("%-20s %8s %8s" % ("confidence", "namen", "zeilen"))
    for c in ("high", "medium", "low"):
        n, rws = rows_for(lambda r, c=c: r["confidence"] == c)
        print("%-20s %8d %8d" % (c, n, rws))
    print("")
    print("%-20s %8s %8s" % ("region_verdict", "namen", "zeilen"))
    for v in ("agrees", "new", "CONFLICT", "ambiguous_region", "no_coords"):
        n, rws = rows_for(lambda r, v=v: r["region_verdict"] == v)
        print("%-20s %8d %8d" % (v, n, rws))
    n_reg, rows_reg = rows_for(lambda r: bool(r["region_pip"]))
    print("\n=> Region-validierbar (Koordinate + eindeutiges Polygon): "
          "%d Namen / %d Zeilen" % (n_reg, rows_reg))
    conflicts = [r for r in out_rows if r["region_verdict"] == "CONFLICT"]
    if conflicts:
        print("\nRegion-Konflikte (bisherige Zuordnung != Polygon), Top 15:")
        for r in sorted(conflicts, key=lambda r: -r["obs_rows"])[:15]:
            print("  %-22s %-28s -> %-28s (%d Zeilen)"
                  % (r["xc_name"][:22], r["region_recorded"][:28],
                     r["region_pip"][:28], r["obs_rows"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
