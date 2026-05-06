"""
Spot-Verwaltung für Gleitcast.
Lädt Fluggebiete aus CSV und stellt Such-/Filterfunktionen bereit.
"""

import csv
import re
from config import CSV_PATH


_URL_UNSAFE_CHARS = re.compile(r"[\\/?#]+")


def sanitize_spot_name(name: str) -> str:
    """Entfernt URL-gefährliche Zeichen aus Spot-Namen.

    Flask-Routen mit `<string:name>` matchen keine Pfad-Separatoren — ein `/`
    im Spot-Namen (z.B. DHV-Import "Oberrieden Start-/Landeplatz") liefert
    sonst Werkzeugs HTML-404 statt unseres JSON-Handlers.
    """
    if not name:
        return name
    cleaned = _URL_UNSAFE_CHARS.sub("-", name)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip(" -") or name.strip()


def load_spots(csv_path=None):
    """Lädt alle Spots aus der CSV-Datei."""
    path = csv_path or CSV_PATH
    spots = []
    # UTF-8 (mit BOM-Support), Fallback auf Windows-1252 (Excel-Standard)
    try:
        with open(path, encoding="utf-8-sig") as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        with open(path, encoding="cp1252") as f:
            lines = f.readlines()

    import io
    reader = csv.DictReader(io.StringIO("".join(lines)))
    for row in reader:
        if not row.get("site_name", "").strip():
            continue
        spots.append({
            "region": row["region"].strip(),
            "fluggebiet": row["fluggebiet"].strip(),
            "name": sanitize_spot_name(row["site_name"].strip()),
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "elevation_m": int(float(row["elevation_m"])),
            "windrichtung": row["windrichtung"].strip(),
            "bemerkung": row.get("Bemerkungen", "").strip(),
            "ideal_wind_max": int(row["ideal_wind_max_kmh"]) if row.get("ideal_wind_max_kmh") else 30,
            "slope_azimuth": int(row["slope_azimuth"]) if row.get("slope_azimuth") else None,
            "slope_angle": int(row["slope_angle"]) if row.get("slope_angle") else 25,
            "kritischer_foehn": row.get("kritischer_foehn", "Süd").strip() or "Süd",
            "terrain_type": row.get("terrain_type", "").strip() or None,
            "analyse_region": row.get("analyse_region", "").strip() or None,
        })
    return spots


def get_spot_by_name(spots, name):
    """Findet einen Spot nach Name (case-insensitive, Teilmatch)."""
    name_lower = name.lower()
    # Exakter Match
    for spot in spots:
        if spot["name"].lower() == name_lower:
            return spot
    # Teilmatch
    for spot in spots:
        if name_lower in spot["name"].lower() or name_lower in spot["fluggebiet"].lower():
            return spot
    return None


def get_all_spot_names(spots):
    """Gibt alle Spot-Namen zurück."""
    return [s["name"] for s in spots]


def find_spots_by_region(spots, region):
    """Filtert Spots nach Region (case-insensitive, Teilmatch)."""
    region_lower = region.lower()
    return [s for s in spots if region_lower in s["region"].lower()]
