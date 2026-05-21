"""Holt benannte Berge/Hügel/Pässe/Sättel aus OpenStreetMap (via Overpass-API)
für die Schweizer Bbox und speichert sie als GeoJSON für die Frontend-Karten.

Einmaliger / seltener Lauf (Berge bewegen sich nicht):
    python scripts/fetch_osm_peaks.py

Schreibt zwei Files:
  - data/osm_peaks_major.geojson  — Peaks >=2500m + alle Paesse + Saettel >=2000m
                                    (klein, Default-Layer fuer alle Zoomstufen)
  - data/osm_peaks_minor.geojson  — Rest (Peaks <2500m, Saettel <2000m, ohne ele)
                                    (groesser, lazy-load erst bei Zoom >=12)

Tags die wir holen:
  - natural=peak       (Gipfel)
  - natural=saddle     (Sattel/Pass-Senke)
  - mountain_pass=yes  (befahrbare Pässe)

Gefiltert: Nur Features mit `name`-Tag. Ohne Höhenfilter — der Tile-Renderer
entscheidet anhand Zoom-Level, ab wann welche Features sichtbar werden.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests


# CH-Bbox (etwas grosszuegig, inkl. Grenzgebiete fuer Cross-Border-Spots)
BBOX = (45.75, 5.90, 47.85, 10.55)  # south, west, north, east

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]

QUERY = f"""
[out:json][timeout:180];
(
  node["natural"="peak"]["name"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  node["natural"="saddle"]["name"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  node["mountain_pass"="yes"]["name"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
);
out body;
"""


def _fetch() -> dict:
    """Probiert die Overpass-Mirrors der Reihe nach."""
    last_err = None
    for url in OVERPASS_ENDPOINTS:
        try:
            print(f"[fetch] {url} ...", flush=True)
            r = requests.post(url, data={"data": QUERY}, timeout=240)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            print(f"  -> Fehler: {exc}", flush=True)
            last_err = exc
            time.sleep(2)
    raise RuntimeError(f"Alle Overpass-Mirrors fehlgeschlagen: {last_err}")


def _parse_ele(raw) -> float | None:
    """Open-Meteo OSM ele kommt als String, manchmal mit Einheit/Komma."""
    if raw is None:
        return None
    try:
        s = str(raw).strip().replace(",", ".")
        # ele-Tags koennen "1234 m", "1234m", "1234" enthalten
        for suf in (" m", "m"):
            if s.endswith(suf):
                s = s[: -len(suf)].strip()
        return float(s)
    except (ValueError, TypeError):
        return None


def _classify(tags: dict) -> str:
    if tags.get("mountain_pass") == "yes":
        return "pass"
    nat = tags.get("natural")
    if nat == "saddle":
        return "saddle"
    if nat == "peak":
        return "peak"
    return "other"


def _to_geojson(osm: dict) -> dict:
    features = []
    elements = osm.get("elements", [])
    for el in elements:
        if el.get("type") != "node":
            continue
        tags = el.get("tags") or {}
        name = tags.get("name")
        if not name:
            continue
        lat = el.get("lat")
        lon = el.get("lon")
        if lat is None or lon is None:
            continue

        ele = _parse_ele(tags.get("ele"))
        kind = _classify(tags)

        props = {
            "name": name,
            "kind": kind,  # peak | saddle | pass
        }
        if ele is not None:
            props["ele"] = round(ele, 1)
        # Optionale Zusatz-Tags fuer spaetere Verwendung
        for k in ("wikipedia", "wikidata", "prominence", "alt_name", "summit:cross"):
            if tags.get(k):
                props[k] = tags[k]

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [round(lon, 6), round(lat, 6)],
            },
            "properties": props,
        })

    # Sortiert nach Höhe absteigend (nice-to-have fuer Debugging)
    features.sort(key=lambda f: f["properties"].get("ele") or 0, reverse=True)

    return {
        "type": "FeatureCollection",
        "metadata": {
            "source": "OpenStreetMap (Overpass API)",
            "license": "ODbL — https://www.openstreetmap.org/copyright",
            "bbox": list(BBOX),
            "feature_count": len(features),
        },
        "features": features,
    }


def _is_major(props: dict) -> bool:
    """Major-Tier: Peaks >=2500m + alle Paesse + Saettel >=2000m."""
    kind = props.get("kind")
    ele = props.get("ele")
    if kind == "pass":
        return True
    if kind == "peak" and ele is not None and ele >= 2500:
        return True
    if kind == "saddle" and ele is not None and ele >= 2000:
        return True
    return False


def _split_fc(fc: dict) -> tuple[dict, dict]:
    major, minor = [], []
    for f in fc["features"]:
        (major if _is_major(f["properties"]) else minor).append(f)

    def _wrap(feats: list, tier: str) -> dict:
        meta = dict(fc["metadata"])
        meta["tier"] = tier
        meta["feature_count"] = len(feats)
        return {"type": "FeatureCollection", "metadata": meta, "features": feats}

    return _wrap(major, "major"), _wrap(minor, "minor")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    out_major = repo_root / "data" / "osm_peaks_major.geojson"
    out_minor = repo_root / "data" / "osm_peaks_minor.geojson"

    osm = _fetch()
    fc = _to_geojson(osm)
    major, minor = _split_fc(fc)

    # Beide kompakt — Files werden vom Browser geladen
    out_major.write_text(
        json.dumps(major, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    out_minor.write_text(
        json.dumps(minor, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    def _kinds(feats):
        counts: dict[str, int] = {}
        for f in feats:
            k = f["properties"].get("kind", "other")
            counts[k] = counts.get(k, 0) + 1
        return counts

    print(f"[ok] {len(major['features'])} Major  -> {out_major}")
    for k, c in sorted(_kinds(major["features"]).items(), key=lambda x: -x[1]):
        print(f"        {k:8s} {c}")
    print(f"[ok] {len(minor['features'])} Minor  -> {out_minor}")
    for k, c in sorted(_kinds(minor["features"]).items(), key=lambda x: -x[1]):
        print(f"        {k:8s} {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
