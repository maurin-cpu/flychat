"""OGN-Sessionizer — verdichtet Rohpunkte zu Fluegen (Phase 2).

Der Collector (ogn_collector.py) schreibt nur Rohpunkte. Hier entstehen daraus
Fluege mit den Groessen, um die es eigentlich geht: **gemessenes Steigen und
erreichte Hoehe**, je Region. Sie treffen den bekannten offenen Defekt — die
systematische regionale Schieflage der Thermik-Bewertung, die bis heute an nur
16 XContest-Topouts haengt. Ein einziger starker Flugtag liefert hier rund
1500 Fluege.

Einseitigkeit bleibt (docs/pläne/PLAN_ogn_validation.md): Anwesenheit ist ein
Beleg, Abwesenheit sagt nichts.

Die beiden Schwellenwerte sind an echten Daten abgelesen, nicht geraten
(Messung am 15.08.2026, 1414 Geraete / 1.12 Mio. Punkte):

  * SESSION_GAP_S = 300 — 99.85 % aller Punktabstaende desselben Geraets liegen
    darunter. Mit 60 s zerfaellt ein Flug an jeder Empfangsluecke (9.4 Sessions
    je Geraet, Median 9 min); ab 600 s werden echte Zweitfluege zusammengeklebt.
  * Boden vs. Luft ueber ein Bewegungsfenster. Ein eingeschaltetes Geraet heisst
    nicht "fliegt": am Startplatz stehen Instrumente im P90 noch 10 Minuten
    herum, im P99 fast 50. Ohne Trimmen ist jede Airtime-Zahl Unsinn.

Betrieb:
    python ogn_sessions.py                  # gestern verdichten
    python ogn_sessions.py --date 2026-08-15
    python ogn_sessions.py --backfill       # alle Tage, die Rohpunkte haben
    python ogn_sessions.py --report         # Stand zeigen
"""

from __future__ import annotations

import argparse
import logging
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "ogn_tracks.db"
SPOT_CSV = ROOT / "data" / "fluggebiete_dhv.csv"

# --- abgelesene Schwellenwerte (Begruendung im Modul-Docstring) -------------
SESSION_GAP_S = 300        # Sendepause, ab der ein Flug als beendet gilt
MOVE_WINDOW_S = 60         # Fenster fuer die Bewegungspruefung (+-)
MOVE_MIN_DIST_M = 60       # ... bewegt, wenn darin so weit gefahren ...
MOVE_MIN_DALT_M = 15       # ... oder die Hoehe so stark wechselt
MIN_DURATION_MIN = 5       # kuerzeres zaehlt nicht als Flug
MIN_ALT_SPAN_M = 100       # Groundhandling am Startplatz aussortieren
MIN_BEACONS = 3
MIN_CLIMB_SAMPLES = 10     # darunter sind climb_p75/climb_max nicht belastbar

# Rohpunkte, die physikalisch nicht sein koennen (0.02 % der Rohdaten, aber sie
# verderben jedes Maximum: gemessen wurden 38 216 m und 50.79 m/s).
ALT_MIN_M, ALT_MAX_M = 1, 6000
CLIMB_ABS_MAX_MS = 15.0

# Positionssprung: im ersten Lauf ergab ein "Flug" 911 km in 56 min (~975 km/h).
# Einzelne Beacons sitzen weit neben der Bahn; ungefiltert verdirbt das Strecke
# und Startpunkt (und damit die Regionszuordnung).
MAX_GROUND_SPEED_KMH = 150.0
MAX_JUMP_SKIP = 3          # danach neu verankern, sonst kappt ein Sprung den Rest

# Ein Geraet, das den Tag am Boden liegt, erzeugt genug Hoehen-Rauschen, um die
# Spannen-Schwelle zu reissen (real: 364 min, 3.8 km, 1 m ueber Grund).
# Zwei unabhaengige Merkmale entlarven es:
#   - Es kommt nicht vom Boden weg.
MIN_MAX_AGL_M = 50
#   - Es legt keine Bahn zurueck. Das ist das robustere Merkmal, weil es nicht
#     am Gelaenderaster haengt: ein Schirm fliegt rund 30 km/h durch die Luft,
#     auch beim Soaring am Hang, wo die Netto-Versetzung fast null ist. Ein
#     liegendes Instrument kam auf 0.6 km/h (GPS-Wandern).
MIN_MEAN_SPEED_KMH = 5.0

# Ein Schirm kann nicht unter dem Boden fliegen. Kleine negative Werte sind
# Rasterfehler des Gelaendes im Steilhang; alles darunter ist Messmuell und
# wird als "unbekannt" gefuehrt, nicht als Zahl. Sonst speist es die
# Empfangs-Kennzahl, an der die regionale Vergleichbarkeit haengt.
AGL_MIN_PLAUSIBLE_M = -200

SPOT_MATCH_KM = 2.0        # Startpunkt -> Startplatz
TERRAIN_GRID = 0.001       # ~100 m; Rasterung des Gelaende-Caches

# Rohpunkte kosten rund 222 MB je starkem Sommertag (gemessen, nicht geschaetzt).
# 7 Tage = gut 1.5 GB im schlimmsten Fall; 30 Tage waeren bis 6.7 GB gewesen und
# damit ein Drittel des freien Plattenplatzes.
# Weggeworfen wird NUR, was verdichtet ist (siehe prune_beacons) — flights und
# coverage bleiben dauerhaft, sie sind das Produkt.
RETENTION_DAYS = 7


# --------------------------------------------------------------------------
# Datenbank
# --------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS flights (
            device_hash TEXT,
            date TEXT,
            takeoff_ts TEXT,
            landing_ts TEXT,
            duration_min REAL,
            launch_lat REAL,
            launch_lon REAL,
            launch_spot TEXT,
            region TEXT,
            -- Landepunkt. Brauchbar nur, wenn landing_agl_m klein ist: sonst
            -- ist es die Stelle, an der der Empfang abriss, nicht die Landung.
            -- Eigene Region, weil ein Flug haeufig anderswo landet als er
            -- startet — bei 12 % liegt schon der Hochpunkt in einer anderen.
            landing_lat REAL,
            landing_lon REAL,
            landing_region TEXT,
            max_alt_m INTEGER,
            max_height_agl_m INTEGER,
            min_height_agl_m INTEGER,
            -- Hoehe ueber Grund am ERSTEN und LETZTEN empfangenen Punkt.
            -- Der Unterschied zu min_height_agl_m ist entscheidend fuer die
            -- Frage "wo wurde gestartet": ein Flug kann in der Luft beginnen
            -- (Empfang setzte spaet ein) und trotzdem am Boden landen. Dann ist
            -- min_height_agl_m klein, launch_lat/lon aber trotzdem falsch.
            -- Nur bei kleinem takeoff_agl_m ist der Startpunkt ein echter Start.
            takeoff_agl_m INTEGER,
            landing_agl_m INTEGER,
            alt_span_m INTEGER,
            climb_p75 REAL,
            climb_max REAL,
            climb_samples INTEGER,
            distance_km REAL,
            n_beacons INTEGER,
            aircraft_type INTEGER,
            PRIMARY KEY (device_hash, takeoff_ts)
        );
        CREATE INDEX IF NOT EXISTS idx_flights_date   ON flights(date);
        CREATE INDEX IF NOT EXISTS idx_flights_region ON flights(date, region);

        -- Die Rechengrundlage gegen den Empfangs-Bias. Ohne sie waeren
        -- regionale Steig-/Hoehenvergleiche wertlos: hoeren wir in einer Region
        -- nur die hohen Fluege, sieht sie besser aus, als sie war.
        CREATE TABLE IF NOT EXISTS coverage (
            date TEXT,
            region TEXT,
            receivers INTEGER,
            devices INTEGER,
            flights INTEGER,
            beacons INTEGER,
            min_agl_m INTEGER,
            p05_agl_m INTEGER,
            median_agl_m INTEGER,
            PRIMARY KEY (date, region)
        );

        -- Welche Tage sind verdichtet? Einzige Freigabe zum Wegwerfen der
        -- Rohpunkte. Ohne diesen Nachweis wuerde eine still ausgefallene
        -- Verdichtung die Rohdaten nach der Aufbewahrungsfrist mitloeschen —
        -- bei 7 Tagen Frist waere das eine Woche, bevor es jemandem auffaellt.
        CREATE TABLE IF NOT EXISTS rollup_log (
            date TEXT PRIMARY KEY,
            processed_at TEXT,
            flights INTEGER,
            regions INTEGER
        );

        -- Gelaendehoehe, gerastert gecacht. Open-Meteo wird so nur einmal je
        -- Rasterzelle gefragt; Startplaetze wiederholen sich stark.
        CREATE TABLE IF NOT EXISTS terrain (
            lat_key INTEGER,
            lon_key INTEGER,
            elev_m REAL,
            PRIMARY KEY (lat_key, lon_key)
        );
    """)
    _migrate(conn)
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """Fehlende Spalten nachziehen.

    CREATE TABLE IF NOT EXISTS laesst eine bestehende Tabelle unveraendert —
    ohne das hier haetten aeltere Datenbanken die neuen Spalten stumm nicht.
    Die Werte fuellt ein `--backfill`.
    """
    have = {r[1] for r in conn.execute("PRAGMA table_info(flights)")}
    for spalte, typ in (("takeoff_agl_m", "INTEGER"),
                        ("landing_agl_m", "INTEGER"),
                        ("landing_lat", "REAL"),
                        ("landing_lon", "REAL"),
                        ("landing_region", "TEXT")):
        if spalte not in have:
            conn.execute(f"ALTER TABLE flights ADD COLUMN {spalte} {typ}")
            logger.info("Datenbank erweitert: flights.%s", spalte)


# --------------------------------------------------------------------------
# Geometrie / Zuordnung
# --------------------------------------------------------------------------

def _dist_km(lat1, lon1, lat2, lon2) -> float:
    dlat = (lat2 - lat1) * 111.32
    dlon = (lon2 - lon1) * 111.32 * math.cos(math.radians(lat1))
    return math.hypot(dlat, dlon)


def _load_regions():
    """Regionspolygone. Zuordnung NUR per Punkt-in-Polygon — nie per Distanz
    zum Regions-Zentrum (Fehlalarm-Lehre, siehe CLAUDE.md)."""
    sys.path.insert(0, str(ROOT))
    from scripts import validation_common as vc
    return vc.load_region_polygons(), vc._point_in_poly


def _load_spots() -> list[tuple[str, str, float, float]]:
    """(site_name, analyse_region, lat, lon) aus der Spot-CSV.

    Wichtig: die Region kommt aus `analyse_region`, nicht aus `region` — dort
    steht die grobe DHV-Herkunft, nicht unsere Region.
    """
    import csv
    out = []
    with SPOT_CSV.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                lat = float(row["latitude"])
                lon = float(row["longitude"])
            except (TypeError, ValueError, KeyError):
                continue
            out.append((row.get("site_name") or "", row.get("analyse_region") or "",
                        lat, lon))
    return out


REGION_GRID = 0.005        # ~500 m; Rasterung des Regions-Memos


class RegionLookup:
    """Punkt -> Region, gerastert gemerkt.

    Der Ray-Cast selbst ist billig, aber ein starker Tag bringt ueber eine
    Million Rohpunkte — ungepuffert liefe die Empfangsmessung stundenlang.
    Gerastert wird auf rund 500 m; das verschiebt hoechstens Punkte direkt auf
    einer Regionsgrenze, und die Empfangslage ist ohnehin eine Aggregatgroesse.
    """

    def __init__(self):
        self._polys, self._pip = _load_regions()
        self._memo: dict[tuple[int, int], str | None] = {}

    def __call__(self, lat: float, lon: float) -> str | None:
        key = (round(lat / REGION_GRID), round(lon / REGION_GRID))
        try:
            return self._memo[key]
        except KeyError:
            pass
        found = None
        for name, multip in self._polys:
            if any(self._pip(lat, lon, rings) for rings in multip):
                found = name
                break
        self._memo[key] = found
        return found


def _nearest_spot(lat, lon, spots):
    best, best_d = None, 1e9
    for name, _region, slat, slon in spots:
        d = _dist_km(lat, lon, slat, slon)
        if d < best_d:
            best, best_d = name, d
    return (best, best_d) if best_d <= SPOT_MATCH_KM else (None, best_d)


# --------------------------------------------------------------------------
# Gelaendehoehe (AGL)
# --------------------------------------------------------------------------

def _grid_key(lat, lon) -> tuple[int, int]:
    return (round(lat / TERRAIN_GRID), round(lon / TERRAIN_GRID))


def terrain_lookup(conn: sqlite3.Connection, points: list[tuple[float, float]]
                   ) -> dict[tuple[int, int], float]:
    """Gelaendehoehe je Rasterzelle, gecacht. Fehlt sie, wird sie geholt.

    Ohne Gelaende gibt es keine Hoehe ueber Grund — und ohne die ist die
    Empfangslage nicht messbar, weil "wie tief hoeren wir noch?" die Frage ist,
    an der die regionale Vergleichbarkeit haengt.
    """
    keys = {_grid_key(la, lo) for la, lo in points}
    have = {}
    cur = conn.execute("SELECT lat_key, lon_key, elev_m FROM terrain")
    for lk, ok, e in cur:
        if (lk, ok) in keys:
            have[(lk, ok)] = e
    missing = sorted(keys - set(have))
    if not missing:
        return have

    import requests
    import config
    url = config.API_URL.replace("/v1/forecast", "/v1/elevation")
    logger.info("Gelaende: %d neue Rasterzellen holen", len(missing))
    for i in range(0, len(missing), 100):
        chunk = missing[i:i + 100]
        params = config.with_api_key({
            "latitude": ",".join(str(round(lk * TERRAIN_GRID, 5)) for lk, _ in chunk),
            "longitude": ",".join(str(round(ok * TERRAIN_GRID, 5)) for _, ok in chunk),
        })
        try:
            r = requests.get(url, params=params,
                             timeout=getattr(config, "API_TIMEOUT", 60))
            r.raise_for_status()
            elev = r.json().get("elevation") or []
        except Exception as e:                                    # noqa: BLE001
            logger.warning("Gelaende-Abfrage fehlgeschlagen (%s) — AGL bleibt leer", e)
            break
        rows = [(lk, ok, float(e)) for (lk, ok), e in zip(chunk, elev)
                if e is not None]
        conn.executemany("INSERT OR REPLACE INTO terrain (lat_key, lon_key, elev_m) "
                         "VALUES (?,?,?)", rows)
        conn.commit()
        have.update({(lk, ok): e for lk, ok, e in rows})
    return have


# --------------------------------------------------------------------------
# Sessionizing
# --------------------------------------------------------------------------

def _drop_jumps(pts: list[tuple]) -> list[tuple]:
    """Positionssprünge entfernen.

    Verworfen wird ein Punkt, der vom letzten *angenommenen* Punkt aus eine
    unmoegliche Geschwindigkeit verlangt. Nach MAX_JUMP_SKIP Verwerfungen in
    Folge ist nicht der neue Punkt falsch, sondern der Anker — dann wird neu
    verankert, statt den Rest des Flugs wegzuwerfen.
    """
    if len(pts) < 2:
        return pts
    out = [pts[0]]
    skipped = 0
    for q in pts[1:]:
        dt = (q[0] - out[-1][0]).total_seconds()
        if dt <= 0:
            continue
        speed = _dist_km(out[-1][1], out[-1][2], q[1], q[2]) / (dt / 3600.0)
        if speed > MAX_GROUND_SPEED_KMH and skipped < MAX_JUMP_SKIP:
            skipped += 1
            continue
        out.append(q)
        skipped = 0
    return out


def _split_sessions(pts: list[tuple], gap_s: int = SESSION_GAP_S) -> list[list]:
    """Punkte eines Geraets an Sendepausen in Sessions zerlegen."""
    out, cur = [], [pts[0]]
    for prev, nxt in zip(pts, pts[1:]):
        if (nxt[0] - prev[0]).total_seconds() > gap_s:
            out.append(cur)
            cur = []
        cur.append(nxt)
    out.append(cur)
    return out


def _moving_flags(s: list[tuple]) -> list[bool]:
    """Je Punkt: bewegt sich das Geraet in einem Fenster von +-MOVE_WINDOW_S?

    Zwei Wege, weil beide allein taeuschen: Soaring am Hang bewegt sich kaum
    horizontal, ein Transport im Auto kaum vertikal.
    """
    n = len(s)
    flags = []
    j0 = j1 = 0
    for i in range(n):
        while (s[i][0] - s[j0][0]).total_seconds() > MOVE_WINDOW_S:
            j0 += 1
        if j1 < i:
            j1 = i
        while j1 < n - 1 and (s[j1 + 1][0] - s[i][0]).total_seconds() <= MOVE_WINDOW_S:
            j1 += 1
        w = s[j0:j1 + 1]
        far = any(_dist_km(w[0][1], w[0][2], q[1], q[2]) * 1000 >= MOVE_MIN_DIST_M
                  for q in w)
        alts = [q[3] for q in w]
        flags.append(far or (max(alts) - min(alts)) >= MOVE_MIN_DALT_M)
    return flags


def _trim_ground(s: list[tuple]) -> list[tuple] | None:
    """Stand-Phasen vor dem Start und nach der Landung abschneiden."""
    flags = _moving_flags(s)
    if not any(flags):
        return None
    a = flags.index(True)
    b = len(flags) - 1 - flags[::-1].index(True)
    return s[a:b + 1]


def _climb_aggregates(seg: list[tuple]) -> tuple[float | None, float | None, int]:
    """P75 und Maximum des Steigens, nur ueber positive Werte.

    Roh-Beacons enthalten auch das Sinken zwischen den Baerten; wer alles
    mittelt, misst den Gleitwinkel statt die Thermik. Grobe Ausreisser fliegen
    vorher raus (siehe CLIMB_ABS_MAX_MS).
    """
    pos = sorted(q[4] for q in seg
                 if q[4] is not None and 0 < q[4] <= CLIMB_ABS_MAX_MS)
    if len(pos) < MIN_CLIMB_SAMPLES:
        return None, None, len(pos)
    return pos[int(0.75 * (len(pos) - 1))], pos[-1], len(pos)


def build_flights(conn: sqlite3.Connection, day: str) -> int:
    """Einen Tag verdichten. Idempotent — der Tag wird vorher geleert."""
    region_of = RegionLookup()
    spots = _load_spots()

    tracks: dict[str, list] = defaultdict(list)
    for dev, ts, lat, lon, alt, climb, actype in conn.execute("""
            SELECT device_hash, ts, lat, lon, alt_m, climb_ms, aircraft_type
            FROM beacons
            WHERE substr(ts,1,10)=? AND alt_m IS NOT NULL
              AND alt_m BETWEEN ? AND ?
            ORDER BY device_hash, ts""", (day, ALT_MIN_M, ALT_MAX_M)):
        tracks[dev].append((datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"),
                            lat, lon, alt, climb, actype))
    if not tracks:
        logger.info("%s: keine Rohpunkte", day)
        return 0

    # 1. Sessions bilden und auf echte Fluege eindampfen.
    flights = []
    for dev, pts in tracks.items():
        for sess in _split_sessions(_drop_jumps(pts)):
            if len(sess) < MIN_BEACONS:
                continue
            seg = _trim_ground(sess)
            if not seg or len(seg) < MIN_BEACONS:
                continue
            dur = (seg[-1][0] - seg[0][0]).total_seconds() / 60.0
            alts = [q[3] for q in seg]
            span = max(alts) - min(alts)
            if dur < MIN_DURATION_MIN or span < MIN_ALT_SPAN_M:
                continue
            dist = sum(_dist_km(seg[i - 1][1], seg[i - 1][2], seg[i][1], seg[i][2])
                       for i in range(1, len(seg)))
            if dist / (dur / 60.0) < MIN_MEAN_SPEED_KMH:
                continue
            flights.append((dev, seg, dist))

    if not flights:
        logger.info("%s: keine Fluege aus %d Geraeten", day, len(tracks))
        return 0

    # 2. Gelaende fuer Start- und Tiefpunkt jedes Flugs (gecacht).
    need = []
    for _dev, seg, _dist in flights:
        need.append((seg[0][1], seg[0][2]))         # Start (bzw. Empfangsbeginn)
        need.append((seg[-1][1], seg[-1][2]))       # Landung (bzw. Empfangsende)
        lowest = min(seg, key=lambda q: q[3])
        need.append((lowest[1], lowest[2]))
        highest = max(seg, key=lambda q: q[3])
        need.append((highest[1], highest[2]))
    terrain = terrain_lookup(conn, need)

    def agl(pt) -> int | None:
        """Hoehe ueber Grund — oder None, wenn der Wert unmoeglich ist.

        Lieber eine fehlende Messung als eine erfundene: diese Zahl traegt die
        Empfangs-Kennzahl, und eine geschoente Empfangslage laesst eine Region
        beim Steigvergleich besser aussehen, als sie war.
        """
        e = terrain.get(_grid_key(pt[1], pt[2]))
        if e is None:
            return None
        v = int(round(pt[3] - e))
        return None if v < AGL_MIN_PLAUSIBLE_M else v

    # 3. Zeilen bauen. Geraete, die nie vom Boden weggekommen sind, fallen hier
    #    heraus — vor dem Gelaende-Abruf war das nicht entscheidbar.
    rows = []
    verworfen_boden = 0
    for dev, seg, dist in flights:
        alts = [q[3] for q in seg]
        lowest = min(seg, key=lambda q: q[3])
        highest = max(seg, key=lambda q: q[3])
        top_agl = agl(highest)
        if top_agl is not None and top_agl < MIN_MAX_AGL_M:
            verworfen_boden += 1
            continue
        p75, cmax, nclimb = _climb_aggregates(seg)
        lat0, lon0 = seg[0][1], seg[0][2]
        lat1, lon1 = seg[-1][1], seg[-1][2]
        spot, _d = _nearest_spot(lat0, lon0, spots)
        rows.append((
            dev, day,
            seg[0][0].strftime("%Y-%m-%dT%H:%M:%SZ"),
            seg[-1][0].strftime("%Y-%m-%dT%H:%M:%SZ"),
            round((seg[-1][0] - seg[0][0]).total_seconds() / 60.0, 1),
            round(lat0, 5), round(lon0, 5), spot,
            region_of(lat0, lon0),
            round(lat1, 5), round(lon1, 5), region_of(lat1, lon1),
            max(alts), top_agl, agl(lowest), agl(seg[0]), agl(seg[-1]),
            max(alts) - min(alts),
            p75, cmax, nclimb, round(dist, 2), len(seg), seg[0][5],
        ))

    conn.execute("DELETE FROM flights WHERE date=?", (day,))
    conn.executemany("""
        INSERT OR REPLACE INTO flights
        (device_hash, date, takeoff_ts, landing_ts, duration_min,
         launch_lat, launch_lon, launch_spot, region,
         landing_lat, landing_lon, landing_region, max_alt_m,
         max_height_agl_m, min_height_agl_m, takeoff_agl_m, landing_agl_m,
         alt_span_m, climb_p75, climb_max, climb_samples, distance_km,
         n_beacons, aircraft_type)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    conn.commit()
    logger.info("%s: %d Fluege aus %d Geraeten (%d am Boden verworfen)",
                day, len(rows), len(tracks), verworfen_boden)
    return len(rows)


def build_coverage(conn: sqlite3.Connection, day: str) -> int:
    """Empfangslage je Region fortschreiben.

    Nicht nachtraeglich, sondern ab Tag 1: eine regional strukturierte
    Empfangsluecke kann genau das Muster erzeugen, das wir zu finden hoffen —
    wir wuerden einen Defekt "bestaetigen", der im Messgeraet sitzt.
    """
    region_of = RegionLookup()

    agg = defaultdict(lambda: {"recv": set(), "dev": set(), "beacons": 0})
    for lat, lon, recv, dev in conn.execute("""
            SELECT lat, lon, receiver, device_hash FROM beacons
            WHERE substr(ts,1,10)=?""", (day,)):
        reg = region_of(lat, lon)
        if reg is None:
            continue
        a = agg[reg]
        a["beacons"] += 1
        if recv:
            a["recv"].add(recv)
        a["dev"].add(dev)

    agl_by_region = defaultdict(list)
    for reg, lo in conn.execute("""
            SELECT region, min_height_agl_m FROM flights
            WHERE date=? AND region IS NOT NULL AND min_height_agl_m IS NOT NULL""",
            (day,)):
        agl_by_region[reg].append(lo)
    n_flights = defaultdict(int)
    for reg, n in conn.execute("""
            SELECT region, COUNT(*) FROM flights WHERE date=? GROUP BY region""",
            (day,)):
        n_flights[reg] = n

    rows = []
    for reg, a in agg.items():
        vals = sorted(agl_by_region.get(reg, []))
        rows.append((
            day, reg, len(a["recv"]), len(a["dev"]), n_flights.get(reg, 0),
            a["beacons"],
            vals[0] if vals else None,
            vals[int(0.05 * (len(vals) - 1))] if vals else None,
            vals[len(vals) // 2] if vals else None,
        ))
    conn.execute("DELETE FROM coverage WHERE date=?", (day,))
    conn.executemany("""
        INSERT OR REPLACE INTO coverage
        (date, region, receivers, devices, flights, beacons,
         min_agl_m, p05_agl_m, median_agl_m)
        VALUES (?,?,?,?,?,?,?,?,?)""", rows)
    conn.commit()
    logger.info("%s: Empfangslage fuer %d Regionen", day, len(rows))
    return len(rows)


def prune_beacons(conn: sqlite3.Connection) -> int:
    """Rohpunkte wegwerfen — aber nur verdichtete Tage.

    Zwei Bedingungen, beide noetig:
      * aelter als die Aufbewahrungsfrist, UND
      * im rollup_log, also nachweislich zu Fluegen verarbeitet.

    Die zweite ist der Grund, warum 7 Tage Frist gefahrlos sind: faellt die
    Verdichtung aus, wachsen die Rohpunkte weiter, statt still zu verschwinden.
    Der Collector zieht dann irgendwann seine Notbremse (dort dokumentiert) —
    aber erst weit spaeter und sichtbar.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
              ).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = conn.execute(
        "DELETE FROM beacons WHERE ts < ? "
        "AND substr(ts,1,10) IN (SELECT date FROM rollup_log)", (cutoff,))
    conn.commit()
    return cur.rowcount


def unverdichtete_tage(conn: sqlite3.Connection) -> list[str]:
    """Tage mit Rohpunkten, die noch nicht verdichtet sind.

    Bei kurzer Aufbewahrung ist das die Zahl, auf die man schaut: was hier
    steht, blockiert das Aufraeumen — und geht verloren, sobald der Collector
    seine Notbremse zieht.
    """
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT substr(ts,1,10) FROM beacons "
        "WHERE substr(ts,1,10) NOT IN (SELECT date FROM rollup_log) "
        "ORDER BY 1")]


def days_with_beacons(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT substr(ts,1,10) FROM beacons ORDER BY 1")]


def run_day(conn: sqlite3.Connection, day: str) -> dict:
    """Einen Tag verdichten und als verarbeitet vermerken.

    Der Eintrag im rollup_log entsteht erst, wenn beide Schritte durch sind —
    er ist die Freigabe zum Wegwerfen der Rohpunkte. Ein Abbruch dazwischen
    laesst den Tag also lieber unverdichtet stehen, als ihn preiszugeben.
    """
    n = build_flights(conn, day)
    r = build_coverage(conn, day)
    conn.execute(
        "INSERT OR REPLACE INTO rollup_log (date, processed_at, flights, regions) "
        "VALUES (?,?,?,?)",
        (day, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), n, r))
    conn.commit()
    return {"tag": day, "fluege": n, "regionen": r}


def report(conn: sqlite3.Connection) -> None:
    print(f"{'Tag':<12}{'Fluege':>8}{'Geraete':>9}{'Regionen':>10}"
          f"{'Dauer P50':>11}{'Steig P75':>11}{'max Hoehe':>11}")
    for row in conn.execute("""
            SELECT date, COUNT(*), COUNT(DISTINCT device_hash),
                   COUNT(DISTINCT region), MAX(max_alt_m)
            FROM flights GROUP BY date ORDER BY date"""):
        day, n, dev, regs, maxalt = row
        durs = [r[0] for r in conn.execute(
            "SELECT duration_min FROM flights WHERE date=? ORDER BY duration_min",
            (day,))]
        cl = [r[0] for r in conn.execute(
            "SELECT climb_p75 FROM flights WHERE date=? AND climb_p75 IS NOT NULL "
            "ORDER BY climb_p75", (day,))]
        print(f"{day:<12}{n:>8}{dev:>9}{regs:>10}"
              f"{(durs[len(durs)//2] if durs else 0):>11.0f}"
              f"{(cl[len(cl)//2] if cl else 0):>11.2f}{maxalt or 0:>11}")

    offen = unverdichtete_tage(conn)
    roh = conn.execute("SELECT COUNT(*) FROM beacons").fetchone()[0]
    print(f"\nRohpunkte in der Datenbank: {roh} "
          f"(Aufbewahrung {RETENTION_DAYS} Tage, nur verdichtete Tage)")
    if offen:
        print(f"NOCH NICHT VERDICHTET: {', '.join(offen)} — diese Tage "
              f"blockieren das Aufraeumen und gehen verloren, sobald der "
              f"Collector seine Notbremse zieht.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="OGN-Rohpunkte zu Fluegen verdichten")
    ap.add_argument("--date", help="Tag YYYY-MM-DD (Vorgabe: gestern)")
    ap.add_argument("--backfill", action="store_true",
                    help="alle Tage verdichten, die Rohpunkte haben")
    ap.add_argument("--report", action="store_true", help="Stand zeigen")
    ap.add_argument("--prune", action="store_true",
                    help="Rohpunkte aelter als die Aufbewahrung loeschen")
    args = ap.parse_args(argv)

    if not DB_PATH.exists():
        print(f"Keine Datenbank: {DB_PATH}", file=sys.stderr)
        return 1
    conn = _connect()
    try:
        init_db(conn)
        if args.report:
            report(conn)
            return 0
        if args.backfill:
            tage = days_with_beacons(conn)
        elif args.date:
            tage = [args.date]
        else:
            tage = [(date.today() - timedelta(days=1)).isoformat()]
        for tag in tage:
            run_day(conn, tag)
        if args.prune:
            print(f"{prune_beacons(conn)} Rohpunkte geloescht")
        report(conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    raise SystemExit(main())
