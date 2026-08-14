"""OGN-Collector — schneidet Gleitschirm-/Delta-Telemetrie aus dem OGN mit.

Warum ein Daemon und kein Cron-Job: Das OpenGliderNetwork hält kein abfragbares
Archiv. Die Daten laufen als kontinuierlicher APRS-Stream vorbei; was nicht
mitgeschnitten wird, ist für immer weg (Archiv-Check 14.08.2026, siehe
docs/pläne/PLAN_ogn_validation.md).

Zweck: Roh-Belege für die Thermik-Kalibrierung — gemessenes Steigen und
erreichte Höhe echter Flüge. Einseitige Quelle: Anwesenheit ist ein Beleg,
Abwesenheit sagt nichts.

Gespeichert wird bewusst nur, was wir auswerten:
  - Luftfahrzeug-Typ 7 (Gleitschirm) und 6 (Delta) — rund 5 % des Stroms.
  - Geräte-Kennung NUR als Hash. Wir brauchen "wie viele verschiedene Geräte",
    nie "welches Gerät". Der Salt liegt in data/ogn_salt.txt und darf NIE
    wechseln — sonst wird dasselbe Gerät zu zwei Geräten und jede
    Geräte-Zählung ist rückwirkend falsch.
  - Stealth-/No-Track-Geräte werden beim Eintreffen verworfen, nicht erst
    in der Anzeige.

Betrieb:
    python ogn_collector.py            # Daemon (systemd: ogn-collector.service)
    python ogn_collector.py --stats    # Tageszahlen aus der DB
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
import socket
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "ogn_tracks.db"
SALT_PATH = ROOT / "data" / "ogn_salt.txt"

APRS_HOST = "aprs.glidernet.org"
APRS_PORT = 14580
# Umkreis-Filter serverseitig: 150 km um die Zentralschweiz deckt die CH ab.
APRS_FILTER = "r/46.8/8.2/150"
APRS_LOGIN = f"user FLYCHAT pass -1 vers flychat-ogn 0.1 filter {APRS_FILTER}\r\n"

# OGN/FLARM-Luftfahrzeugtypen, die uns interessieren.
TYPE_PARAGLIDER = 7
TYPE_HANGGLIDER = 6
KEEP_TYPES = {TYPE_PARAGLIDER, TYPE_HANGGLIDER}

RETENTION_DAYS = 30
SILENCE_TIMEOUT = 120   # ohne Daten -> Verbindung gilt als tot
RECONNECT_WAIT = 10

FPM_TO_MS = 0.00508
FT_TO_M = 0.3048

# 4640.50N/00810.30E — APRS-Position (Grad + Dezimalminuten)
_POS_RE = re.compile(r"(\d{2})(\d{2}\.\d{2})([NS])[/\\](\d{3})(\d{2}\.\d{2})([EW])")
# id + 2 Hex Flags + Geräteadresse. Die Adresse ist meist 6 Hex lang, Naviter
# sendet 8 — ohne die Alternative würde die Kennung abgeschnitten.
_ID_RE = re.compile(r"\sid([0-9A-Fa-f]{2})([0-9A-Fa-f]{6,8})(?![0-9A-Fa-f])")
_ALT_RE = re.compile(r"/A=(\d{6})")
_CLIMB_RE = re.compile(r"\s([+-]\d+)fpm")
_TIME_RE = re.compile(r":/(\d{2})(\d{2})(\d{2})h")
_RECV_RE = re.compile(r",qA[SCRXUo],([\w\-]+):")


def _device_salt() -> str:
    """Einmalig erzeugter, danach unveränderlicher Salt."""
    if SALT_PATH.exists():
        return SALT_PATH.read_text(encoding="utf-8").strip()
    SALT_PATH.parent.mkdir(parents=True, exist_ok=True)
    salt = secrets.token_hex(16)
    SALT_PATH.write_text(salt, encoding="utf-8")
    logger.warning("Neuer Geräte-Salt erzeugt: %s — NIE löschen oder ändern.", SALT_PATH)
    return salt


def _connect() -> sqlite3.Connection:
    """SQLite-Verbindung mit WAL-Modus (Muster wie station_observations.py)."""
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS beacons (
                device_hash TEXT,
                ts TEXT,
                lat REAL,
                lon REAL,
                alt_m INTEGER,
                climb_ms REAL,
                aircraft_type INTEGER,
                receiver TEXT,
                PRIMARY KEY (device_hash, ts)
            );
            CREATE INDEX IF NOT EXISTS idx_beacons_ts ON beacons(ts);
        """)
        conn.commit()
    finally:
        conn.close()


def parse_beacon(line: str, now: datetime) -> dict | None:
    """APRS-Zeile -> Beacon-Dict, oder None wenn irrelevant/unlesbar.

    Verworfen wird alles, was nicht Gleitschirm/Delta ist, sowie Geräte mit
    Stealth- oder No-Track-Flag.
    """
    m_id = _ID_RE.search(line)
    if not m_id:
        return None
    flags = int(m_id.group(1), 16)
    if flags & 0xC0:                      # Stealth (0x80) oder No-Track (0x40)
        return None
    actype = (flags >> 2) & 0x0F
    if actype not in KEEP_TYPES:
        return None

    m_pos = _POS_RE.search(line)
    if not m_pos:
        return None
    lat = int(m_pos.group(1)) + float(m_pos.group(2)) / 60.0
    if m_pos.group(3) == "S":
        lat = -lat
    lon = int(m_pos.group(4)) + float(m_pos.group(5)) / 60.0
    if m_pos.group(6) == "W":
        lon = -lon

    m_alt = _ALT_RE.search(line)
    alt_m = round(int(m_alt.group(1)) * FT_TO_M) if m_alt else None

    m_climb = _CLIMB_RE.search(line)
    climb_ms = round(int(m_climb.group(1)) * FPM_TO_MS, 2) if m_climb else None

    m_recv = _RECV_RE.search(line)
    receiver = m_recv.group(1) if m_recv else None

    return {
        "device_hash": hashlib.sha256(
            (_SALT + m_id.group(2).upper()).encode()).hexdigest()[:16],
        "ts": _beacon_time(line, now).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lat": round(lat, 5),
        "lon": round(lon, 5),
        "alt_m": alt_m,
        "climb_ms": climb_ms,
        "aircraft_type": actype,
        "receiver": receiver,
    }


def _beacon_time(line: str, now: datetime) -> datetime:
    """Beacon-Uhrzeit (UTC) auf ein volles Datum bringen.

    Die Zeile trägt nur HHMMSS. Liegt die Zeit mehr als eine Stunde in der
    Zukunft, stammt sie vom Vortag (Mitternachtswechsel).
    """
    m = _TIME_RE.search(line)
    if not m:
        return now
    h, mi, s = (int(g) for g in m.groups())
    ts = now.replace(hour=h, minute=mi, second=s, microsecond=0)
    if ts - now > timedelta(hours=1):
        ts -= timedelta(days=1)
    return ts


def _store(conn: sqlite3.Connection, batch: list[dict]) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO beacons "
        "(device_hash, ts, lat, lon, alt_m, climb_ms, aircraft_type, receiver) "
        "VALUES (:device_hash, :ts, :lat, :lon, :alt_m, :climb_ms, "
        ":aircraft_type, :receiver)", batch)
    conn.commit()


def _prune(conn: sqlite3.Connection) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
              ).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = conn.execute("DELETE FROM beacons WHERE ts < ?", (cutoff,))
    conn.commit()
    return cur.rowcount


def run() -> None:
    """Endlos mitschneiden, bei Abbruch neu verbinden."""
    _init_db()
    conn = _connect()
    _prune(conn)
    while True:
        try:
            _stream_once(conn, lambda: _maybe_prune(conn))
        except Exception as exc:                      # noqa: BLE001
            logger.warning("Stream abgebrochen (%s) — neuer Versuch in %ds",
                           exc, RECONNECT_WAIT)
            time.sleep(RECONNECT_WAIT)


def _maybe_prune(conn: sqlite3.Connection) -> None:
    global _NEXT_PRUNE
    if time.time() > _NEXT_PRUNE:
        removed = _prune(conn)
        _NEXT_PRUNE = time.time() + 86400
        logger.info("Aufräumen: %d Rohpunkte älter als %d Tage gelöscht",
                    removed, RETENTION_DAYS)


def _stream_once(conn: sqlite3.Connection, housekeeping) -> None:
    sock = socket.create_connection((APRS_HOST, APRS_PORT), timeout=30)
    sock.sendall(APRS_LOGIN.encode())
    sock.settimeout(SILENCE_TIMEOUT)
    logger.info("Verbunden mit %s:%d, Filter %s", APRS_HOST, APRS_PORT, APRS_FILTER)
    buf = b""
    batch: list[dict] = []
    last_flush = time.time()
    try:
        while True:
            chunk = sock.recv(8192)
            if not chunk:
                raise ConnectionError("Gegenstelle hat geschlossen")
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode("utf-8", "replace").strip()
                if not line or line.startswith("#"):
                    continue
                beacon = parse_beacon(line, datetime.now(timezone.utc))
                if beacon:
                    batch.append(beacon)
            if batch and time.time() - last_flush > 10:
                _store(conn, batch)
                batch.clear()
                last_flush = time.time()
                housekeeping()
    finally:
        if batch:
            _store(conn, batch)
        sock.close()


def stats(days: int = 7) -> None:
    """Tageszahlen — die Grundlage für den Verbreitungs-Entscheid."""
    conn = _connect()
    try:
        rows = conn.execute("""
            SELECT substr(ts, 1, 10) AS tag,
                   COUNT(*) AS punkte,
                   COUNT(DISTINCT device_hash) AS geraete,
                   SUM(aircraft_type = 7) AS gs_punkte,
                   MIN(alt_m), MAX(alt_m), MAX(climb_ms)
            FROM beacons GROUP BY tag ORDER BY tag DESC LIMIT ?
        """, (days,)).fetchall()
    finally:
        conn.close()
    if not rows:
        print("Noch keine Daten.")
        return
    print(f"{'Tag':<12}{'Punkte':>9}{'Geräte':>8}{'GS-Anteil':>11}"
          f"{'Höhe min/max':>16}{'max Steigen':>13}")
    for tag, punkte, geraete, gs, amin, amax, cmax in rows:
        anteil = f"{100 * (gs or 0) / punkte:.0f}%" if punkte else "-"
        print(f"{tag:<12}{punkte:>9}{geraete:>8}{anteil:>11}"
              f"{f'{amin}/{amax}':>16}{f'{cmax} m/s':>13}")


_SALT = _device_salt()
_NEXT_PRUNE = time.time() + 86400


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    if "--stats" in sys.argv:
        stats()
    else:
        run()
