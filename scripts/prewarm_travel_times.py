#!/usr/bin/env python3
"""Waermt den Fahrzeit-Speicher vor, damit der Chat sofort und vollstaendig antwortet.

Warum es das braucht
--------------------
Der Chat beantwortet "wo kann ich in 4 Stunden hin" ueber die echte Fahrzeit zu
jedem Startplatz. Der kostenlose Kartendienst liefert die aber nur langsam: die
Sammelabfrage laesst rund 60 % unserer Startplaetze leer (Koordinate liegt am
Berg, nicht an der Strasse), und die Luecken einzeln nachzufragen kostet 0.77 s
pro Ziel — parallel gesperrt. Ein kalter Startort dauert damit Minuten.

Fahrzeiten aendern sich aber nicht. Also rechnen wir sie vorher aus: einmal je
Startort, im Hintergrund, und legen sie in `data/travel_times_cache.json` ab.
Der Chat liest dieselbe Datei (mtime-Abgleich in routing.py) und antwortet dann
aus dem Speicher.

Welche Startorte
----------------
Gefragt wird aus dem eigenen Umfeld. Darum in dieser Reihenfolge:
  1. `--subscribers`  die Wohnregion jedes bestaetigten Abonnenten (Regions-
                      Referenzpunkt aus regionen_referenzpunkte.geojson)
  2. `--orte`         die Liste in ORTE unten (groessere Orte + Bahnhoefe)
  3. `--ort "…"`      ein einzelner Ort per Nominatim, fuer Nachzuegler

Aufruf
------
    python scripts/prewarm_travel_times.py --orte              # Standardlauf
    python scripts/prewarm_travel_times.py --subscribers
    python scripts/prewarm_travel_times.py --ort "Grenchen" --minuten 240
    python scripts/prewarm_travel_times.py --orte --trocken    # nur zeigen

Dauer: je Startort wenige Minuten. Der Speicher wird nach JEDEM Startort
geschrieben, ein Abbruch verliert also hoechstens den laufenden Ort.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import routing  # noqa: E402
from spots import load_spots  # noqa: E402
from source_area import get_all_regions  # noqa: E402

# Startorte, aus denen erfahrungsgemaess gefragt wird: grosse Orte und
# Bahnhofsstaedte, verteilt ueber die Landesteile. Bewusst kurz gehalten —
# jeder Ort kostet Rechenzeit, und die Abonnenten-Variante trifft besser.
ORTE = [
    ("Zürich", 47.3769, 8.5417),
    ("Bern", 46.9480, 7.4474),
    ("Basel", 47.5596, 7.5886),
    ("Luzern", 47.0502, 8.3093),
    ("Genève", 46.2044, 6.1432),
    ("Lausanne", 46.5197, 6.6323),
    ("Winterthur", 47.5001, 8.7386),
    ("St. Gallen", 47.4245, 9.3767),
    ("Lugano", 46.0037, 8.9511),
    ("Biel/Bienne", 47.1368, 7.2467),
    ("Thun", 46.7580, 7.6280),
    ("Chur", 46.8508, 9.5320),
    ("Sion", 46.2331, 7.3606),
    ("Fribourg", 46.8065, 7.1615),
    ("Aarau", 47.3925, 8.0442),
    ("Zug", 47.1662, 8.5155),
    ("Solothurn", 47.2088, 7.5323),
    ("Interlaken", 46.6863, 7.8632),
    ("Bellinzona", 46.1944, 9.0175),
    ("Neuchâtel", 46.9925, 6.9310),
]


def abonnenten_startorte() -> list:
    """Regions-Referenzpunkt je bestaetigtem Abonnenten, ohne Doppelte.

    Naeher als das kommen wir dem Wohnort nicht, und das ist gut so: Wir
    speichern hier keine Adressen, nur die Region, die der Nutzer selbst
    abonniert hat.
    """
    pfad = config.SUBSCRIBERS_DB_PATH
    if not os.path.exists(pfad):
        print(f"  keine Abonnenten-DB unter {pfad}")
        return []
    regionen = {}
    for r in get_all_regions():
        rid = r.get("id")
        name = r.get("region") or rid
        lat, lon = r.get("lat"), r.get("lon")
        if rid and lat is not None and lon is not None:
            regionen[rid] = (name, float(lat), float(lon))

    treffer: dict = {}
    con = sqlite3.connect(pfad)
    try:
        for (roh,) in con.execute(
            "SELECT regions FROM subscribers WHERE status = 'confirmed'"
        ):
            for teil in (roh or "").replace(";", ",").split(","):
                rid = teil.strip()
                if rid in regionen:
                    treffer[rid] = regionen[rid]
    except sqlite3.Error as e:
        print(f"  Abonnenten-DB nicht lesbar: {e}")
    finally:
        con.close()
    return list(treffer.values())


def waermen(name: str, lat: float, lon: float, spots: list, minuten: int,
            mode: str, trocken: bool) -> None:
    max_km = routing.max_straight_line_km(minuten)
    ziele = [
        (s["latitude"], s["longitude"]) for s in spots
        if s.get("latitude") is not None and s.get("longitude") is not None
        and routing.haversine_km(lat, lon, s["latitude"], s["longitude"]) <= max_km
    ]
    if trocken:
        print(f"  {name:22s} {len(ziele):4d} Ziele (<= {max_km:.0f} km Luftlinie)")
        return

    t0 = time.time()
    # Kein Budget: Dieses Skript darf dauern, damit der Chat es nicht muss.
    z = routing.travel_times(lat, lon, ziele, mode, budget_seconds=None)
    geschrieben = routing.cache_datei_schreiben()
    mit = sum(1 for e in z if e["minutes"] is not None)
    print(f"  {name:22s} {len(ziele):4d} Ziele | {mit:4d} mit Fahrzeit | "
          f"{time.time() - t0:6.1f}s | Speicher {geschrieben} Eintraege")


# Host des oeffentlichen Gratis-Dienstes. Gegen DEN darf dieses Skript nicht
# laufen — Begruendung in _oeffentlich_pruefen().
_OEFFENTLICH = "valhalla1.openstreetmap.de"


def _oeffentlich_pruefen(erlaubt: bool) -> bool:
    """Bremst das Skript vor dem oeffentlichen Dienst. Gibt True = weitermachen.

    Am 27.09.2026 real passiert: Nach einem Messtag inklusive eines Versuchs mit
    6 parallelen Anfragen hat `valhalla1.openstreetmap.de` diesen Rechner auf
    IP-Ebene ausgesperrt (Connect-Timeout), waehrend derselbe Aufruf vom Server
    in 0.1 s beantwortet wurde. Ein Vorwaermlauf sind pro Startort mehrere
    hundert Einzelanfragen — vom Produktivserver aus gestartet wuerde er
    ziemlich sicher genau den Dienst sperren, den der Chat live braucht.

    Der Lauf gehoert deshalb an eine eigene Valhalla-Instanz
    (docs/pläne/PLAN_routing_eigene_instanz.md). Bis die steht, ist dieses
    Skript absichtlich blockiert.
    """
    if _OEFFENTLICH not in config.VALHALLA_URL:
        return True
    if erlaubt:
        print(f"WARNUNG: Lauf gegen den oeffentlichen Dienst ({_OEFFENTLICH}) "
              f"auf ausdruecklichen Wunsch. Risiko: IP-Sperre, die den Live-Chat trifft.")
        return True
    print(f"ABGEBROCHEN: VALHALLA_URL zeigt auf den oeffentlichen Gratis-Dienst\n"
          f"  ({config.VALHALLA_URL}).\n\n"
          f"Ein Vorwaermlauf sind hunderte Einzelanfragen pro Startort. Der Dienst\n"
          f"sperrt dafuer die IP — am 27.09.2026 diesem Entwicklungsrechner passiert.\n"
          f"Vom Produktivserver aus gestartet wuerde das die Routing-Funktion der\n"
          f"laufenden App lahmlegen.\n\n"
          f"Richtig ist eine eigene Instanz: VALHALLA_URL darauf zeigen lassen\n"
          f"(docs/pläne/PLAN_routing_eigene_instanz.md). Nur wenn du das Risiko\n"
          f"bewusst tragen willst: --trotzdem-oeffentlich")
    return False


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--orte", action="store_true", help="die Ortsliste im Skript")
    p.add_argument("--subscribers", action="store_true",
                   help="Regionen der bestaetigten Abonnenten")
    p.add_argument("--ort", action="append", default=[],
                   help="einzelner Ort (per Nominatim), mehrfach moeglich")
    p.add_argument("--minuten", type=int, default=240,
                   help="maximale Fahrzeit, die vorgewaermt wird (Default 240 = 4 h)")
    p.add_argument("--mode", default="auto", choices=["auto", "bicycle", "pedestrian"])
    p.add_argument("--trocken", action="store_true", help="nur zeigen, nicht rechnen")
    p.add_argument("--trotzdem-oeffentlich", dest="trotzdem", action="store_true",
                   help="gegen den oeffentlichen Gratis-Dienst laufen (Risiko IP-Sperre)")
    a = p.parse_args()

    if not (a.orte or a.subscribers or a.ort):
        p.error("nichts zu tun — waehle --orte, --subscribers oder --ort")

    if not a.trocken and not _oeffentlich_pruefen(a.trotzdem):
        return 2

    spots = load_spots()
    print(f"{len(spots)} Startplaetze · bis {a.minuten} Minuten · Modus {a.mode}")
    print(f"Speicher: {config.TRAVEL_TIME_CACHE_PATH}")

    startorte: list = []
    if a.subscribers:
        gefunden = abonnenten_startorte()
        print(f"\nAbonnenten-Regionen: {len(gefunden)}")
        startorte += gefunden
    if a.orte:
        print(f"\nOrtsliste: {len(ORTE)}")
        startorte += ORTE
    for query in a.ort:
        treffer = routing.geocode(query)
        if not treffer:
            print(f"  '{query}' nicht gefunden — uebersprungen")
            continue
        startorte.append((query, treffer["lat"], treffer["lon"]))

    # Doppelte auf ~100 m zusammenfassen (dasselbe Raster wie der Speicher).
    gesehen, eindeutig = set(), []
    for name, lat, lon in startorte:
        key = (round(lat, 3), round(lon, 3))
        if key in gesehen:
            continue
        gesehen.add(key)
        eindeutig.append((name, lat, lon))

    print(f"\n{len(eindeutig)} Startorte zu waermen:")
    t0 = time.time()
    for i, (name, lat, lon) in enumerate(eindeutig, 1):
        print(f"[{i}/{len(eindeutig)}]", end=" ")
        try:
            waermen(name, lat, lon, spots, a.minuten, a.mode, a.trocken)
        except KeyboardInterrupt:
            routing.cache_datei_schreiben()
            print("\nabgebrochen — bereits Berechnetes ist gespeichert")
            return 130
        except routing.RoutingError as e:
            print(f"  {name:22s} FEHLER: {e}")
    if not a.trocken:
        print(f"\nfertig in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
