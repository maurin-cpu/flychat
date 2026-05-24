"""
Spot-Verwaltung für Gleitcast.

Lädt Fluggebiete aus CSV (PGE-Schema, Mai 2026) und stellt Such-/Filterfunktionen
bereit. CSV-Spalten: wind_N..wind_NW (binaer 0/1), bemerkungen_flug,
bemerkungen_sicherheit, plus Geometrie/Terrain-Metadaten. `windrichtung` wird
aus den Sektor-Spalten in legacy-kompatiblem German-Hyphen-Format synthetisiert
(z.B. `O-SO-S-SW-W` fuer contiguous, `S/N` fuer disjoint).
"""

import csv
import io
import os
import re
import tempfile
from pathlib import Path
import config
from config import CSV_PATH


_URL_UNSAFE_CHARS = re.compile(r"[\\/?#]+")

_PGE_SECTOR_ORDER = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
_PGE_TO_DE = {"N": "N", "NE": "NO", "E": "O", "SE": "SO",
              "S": "S", "SW": "SW", "W": "W", "NW": "NW"}


def _sectors_to_windrichtung(sectors_bin: dict) -> str:
    """Synthetisiert legacy-kompatibles windrichtung-Format aus PGE 8-Sektor-Dict.

    Contiguous Arc → 'NO-O-SO'. Mehrere disjunkte Runs → 'NO-O/W-NW'
    ('-' = contiguous, '/' = disjoint). Wraparound (NW-N-NE) wird korrekt
    behandelt. Leerer String wenn alle Sektoren 0.
    """
    flags = []
    for s in _PGE_SECTOR_ORDER:
        try:
            flags.append(int(sectors_bin.get(s, 0)) >= 1)
        except (TypeError, ValueError):
            flags.append(False)
    if not any(flags):
        return ""
    if all(flags):
        return "-".join(_PGE_TO_DE[s] for s in _PGE_SECTOR_ORDER)
    n = len(_PGE_SECTOR_ORDER)
    # Anker auf False→True-Boundary, damit Wraparound sauber aufloest
    anchor = 0
    for i in range(n):
        if not flags[i] and flags[(i + 1) % n]:
            anchor = (i + 1) % n
            break
    runs: list[list[int]] = []
    k = 0
    while k < n:
        idx = (anchor + k) % n
        if flags[idx]:
            run: list[int] = []
            while k < n and flags[(anchor + k) % n]:
                run.append((anchor + k) % n)
                k += 1
            runs.append(run)
        else:
            k += 1
    parts = ["-".join(_PGE_TO_DE[_PGE_SECTOR_ORDER[i]] for i in r) for r in runs]
    return "/".join(parts)


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
    """Lädt alle Spots aus der PGE-Schema-CSV."""
    path = csv_path or CSV_PATH
    spots = []
    # UTF-8 (mit BOM-Support), Fallback auf Windows-1252 (Excel-Standard)
    try:
        with open(path, encoding="utf-8-sig") as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        with open(path, encoding="cp1252") as f:
            lines = f.readlines()

    reader = csv.DictReader(io.StringIO("".join(lines)))
    default_ideal_wind_max = getattr(config, "WIND_IDEAL_MAX_KMH", 20)

    for row in reader:
        if not row.get("site_name", "").strip():
            continue

        sectors = {k: row.get(f"wind_{k}", "0") for k in _PGE_SECTOR_ORDER}
        windrichtung = _sectors_to_windrichtung(sectors)

        spots.append({
            "region": row["region"].strip(),
            "fluggebiet": row["fluggebiet"].strip(),
            "name": sanitize_spot_name(row["site_name"].strip()),
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "elevation_m": int(float(row["elevation_m"])),
            "windrichtung": windrichtung,
            "bemerkungen_flug": row.get("bemerkungen_flug", "").strip(),
            "bemerkungen_sicherheit": row.get("bemerkungen_sicherheit", "").strip(),
            "ideal_wind_max": default_ideal_wind_max,
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


def make_spot_id(region: str, fluggebiet: str, site_name: str) -> str:
    """Composite-Key fuer einen Spot, eindeutig ueber (region, fluggebiet, site_name)."""
    return f"{region.strip()}|{fluggebiet.strip()}|{site_name.strip()}"


def _read_csv_text(path: Path) -> str:
    try:
        with open(path, encoding="utf-8-sig") as f:
            return f.read()
    except UnicodeDecodeError:
        with open(path, encoding="cp1252") as f:
            return f.read()


def update_spot_coords(spot_id: str, new_lat: float, new_lon: float,
                       csv_path: Path | None = None) -> dict:
    """Schreibt neue lat/lon fuer EINEN Spot atomar zurueck in fluggebiete CSV.

    spot_id = "<region>|<fluggebiet>|<site_name>" (siehe make_spot_id).
    Andere Spalten bleiben unveraendert (inkl. Bemerkungen mit Kommata).

    Returns: dict mit updated row data fuer den Caller.
    Raises: ValueError wenn Spot nicht gefunden, FileNotFoundError wenn CSV fehlt.
    """
    path = Path(csv_path or CSV_PATH)
    if not path.exists():
        raise FileNotFoundError(f"CSV nicht gefunden: {path}")

    try:
        parts = spot_id.split("|")
        if len(parts) != 3:
            raise ValueError(f"Spot-ID muss Format 'region|fluggebiet|site_name' haben: {spot_id}")
        target_region, target_flug, target_site = parts[0].strip(), parts[1].strip(), parts[2].strip()
    except Exception as e:
        raise ValueError(f"Ungueltige Spot-ID: {spot_id} ({e})")

    raw = _read_csv_text(path)
    reader = csv.DictReader(io.StringIO(raw))
    fieldnames = reader.fieldnames
    if not fieldnames or "latitude" not in fieldnames or "longitude" not in fieldnames:
        raise ValueError("CSV-Header fehlt latitude/longitude")
    rows = list(reader)

    matched = None
    for row in rows:
        if (row.get("region", "").strip() == target_region
                and row.get("fluggebiet", "").strip() == target_flug
                and row.get("site_name", "").strip() == target_site):
            matched = row
            break
    if matched is None:
        raise ValueError(f"Spot nicht gefunden: {spot_id}")

    matched["latitude"] = f"{float(new_lat):.4f}"
    matched["longitude"] = f"{float(new_lon):.4f}"

    # Atomar zurueckschreiben: temp-file in selbem Verzeichnis -> os.replace
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=fieldnames,
                quoting=csv.QUOTE_MINIMAL,
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return matched
