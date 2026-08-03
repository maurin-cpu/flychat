"""Traegt die Aussage-Schnappschuesse in validation/fronten/observations.csv ein.

Die Vorhersage-Seite der Tabelle entsteht damit automatisch. Die
Verifikations-Seite (was eingetreten ist) bleibt leer, bis der Abgleich gegen
die spaetere Handanalyse laeuft (Plan §6 Schritt 5) — leer heisst NICHT
GEPRUEFT, nicht "kein Befund".

Idempotent ueber den Schluessel (lauf, stand, zone, typ, median_utc): ein
erneuter Lauf ergaenzt nur, was fehlt, und ueberschreibt keine von Hand
gefuellte Verifikations-Spalte.

Kopiert zugleich die Schnappschuesse nach validation/fronten/aussagen/, damit
der Beleg versioniert ist — die Rohkarten bleiben ausserhalb von Git.

Run:  python scripts/build_fronten_observations.py
"""
import csv
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCHIV = ROOT / "data" / "dwd_fronten_archiv" / "aussagen"
VALID = ROOT / "validation/fronten"
OBS = VALID / "observations.csv"

COLS = [
    # Vorhersage-Seite
    "lauf", "stand", "zone", "typ", "art", "median_utc",
    "fenster_von_utc", "fenster_bis_utc", "spots_betroffen", "spots_zone",
    "anteil", "seitlich_km", "stuetzweite_h", "randwert", "vorlauf_h",
    # Verifikations-Seite (bleibt leer bis zum Abgleich)
    "ana_gueltig_utc", "ana_front_da", "ana_median_utc", "delta_h",
    "bulletin", "verdict", "finding_type", "notes",
]
KEY = ("lauf", "stand", "zone", "typ", "median_utc")


def _vorlauf_fuer(snap: dict, median_utc: str):
    """Vorlaufzeit der Karte, aus der die Aussage stammt.

    Zugeordnet wird der letzte Stuetzpunkt VOR dem Durchgang — er begrenzt das
    Intervall, in dem interpoliert wurde.
    """
    davor = [s for s in snap["stuetzpunkte"] if s["gueltig_utc"] <= median_utc]
    return (davor[-1] if davor else snap["stuetzpunkte"][0])["vorlauf_h"]


def main() -> int:
    VALID.mkdir(parents=True, exist_ok=True)
    (VALID / "aussagen").mkdir(exist_ok=True)
    if not ARCHIV.exists():
        print(f"Kein Archiv unter {ARCHIV.relative_to(ROOT)} — erst "
              f"scripts/archive_dwd_fronten.py laufen lassen.")
        return 2

    rows, seen = [], set()
    if OBS.exists():
        with open(OBS, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                rows.append(r)
                seen.add(tuple(r.get(k, "") for k in KEY))

    neu = 0
    for p in sorted(ARCHIV.glob("passagen_*_stand_*.json")):
        m = re.match(r"passagen_(\d{12})_stand_(\d{8})\.json", p.name)
        if not m:
            continue
        lauf, stand = m.groups()
        shutil.copyfile(p, VALID / "aussagen" / p.name)   # Beleg versionieren
        snap = json.loads(p.read_text(encoding="utf-8"))
        for a in snap["aussagen"]:
            med = a["durchgang_median_utc"]
            key = (lauf, stand, a["zone"], a["typ"], med)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "lauf": lauf, "stand": stand, "zone": a["zone"],
                "typ": a["typ"], "art": a["art"], "median_utc": med,
                "fenster_von_utc": a["fenster_von_utc"],
                "fenster_bis_utc": a["fenster_bis_utc"],
                "spots_betroffen": a["spots_betroffen"],
                "spots_zone": a["spots_zone"], "anteil": a["anteil"],
                "seitlich_km": a["seitlich_km"],
                "stuetzweite_h": a["stuetzweite_h"],
                "randwert": 1 if a["randwert"] else 0,
                "vorlauf_h": _vorlauf_fuer(snap, med),
                **{c: "" for c in COLS[15:]},
            })
            neu += 1

    rows.sort(key=lambda r: (r["median_utc"], r["zone"], r["typ"]))
    with open(OBS, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    offen = sum(1 for r in rows if not r.get("verdict"))
    print(f"{neu} neue Zeile(n), {len(rows)} gesamt -> "
          f"{OBS.relative_to(ROOT)}")
    print(f"  davon {offen} ohne Urteil (= noch nicht geprueft, nicht "
          f"'kein Befund')")
    print(f"  {len(list((VALID / 'aussagen').glob('*.json')))} "
          f"Aussage-Schnappschuesse versioniert")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
