# -*- coding: utf-8 -*-
"""Schutz fuer den OGN-Sessionizer (Phase 2, gebaut 17.08.2026).

Geprueft werden genau die Fehlbilder, die im ersten Lauf ueber echten Daten
real auftraten — jedes htte stille Falschzahlen erzeugt, keines wre beim
Draufschauen aufgefallen:

  Positionssprung   ein "Flug" ergab 911 km in 56 min (~975 km/h), weil
                    einzelne Beacons weit neben der Bahn sitzen
  Geraet am Boden   364 min "Flug" mit 3.8 km und 1 m ueber Grund: ein
                    Instrument, das den Tag am Startplatz lag; das
                    Hoehen-Rauschen allein riss die Spannen-Schwelle
  AGL unter Grund   Tiefpunkte bis 1214 m unter dem Boden — und genau die
                    speisen die Empfangs-Kennzahl, an der die regionale
                    Vergleichbarkeit haengt

Dazu die beiden abgelesenen Schwellenwerte (Sendepause, Boden-vs-Luft) und
die Regel, dass Steigen nur ueber positive Segmente aggregiert wird.
"""
from datetime import datetime, timedelta, timezone

import pytest

import ogn_sessions as og


def _pt(t0, sek, lat=46.5, lon=8.0, alt=1500, climb=1.0, actype=7):
    """Ein Rohpunkt in der Form, die build_flights intern benutzt."""
    return (t0 + timedelta(seconds=sek), lat, lon, alt, climb, actype)


T0 = datetime(2026, 8, 15, 10, 0, 0)


# --------------------------------------------------------------------------
# Sendepause = Flugende
# --------------------------------------------------------------------------

def test_sessions_trennen_erst_ab_der_schwelle():
    """Unter SESSION_GAP_S bleibt ein Flug ein Flug.

    Mit 60 s zerfielen echte Fluege an jeder Empfangsluecke (gemessen:
    9.4 Sessions je Geraet, Median 9 min).
    """
    pts = [_pt(T0, 0), _pt(T0, og.SESSION_GAP_S - 10), _pt(T0, og.SESSION_GAP_S + 100)]
    assert len(og._split_sessions(pts)) == 1


def test_lange_sendepause_trennt():
    pts = [_pt(T0, 0), _pt(T0, og.SESSION_GAP_S + 10), _pt(T0, og.SESSION_GAP_S + 20)]
    sessions = og._split_sessions(pts)
    assert len(sessions) == 2
    assert len(sessions[0]) == 1 and len(sessions[1]) == 2


# --------------------------------------------------------------------------
# Positionssprung
# --------------------------------------------------------------------------

def test_positionssprung_wird_verworfen():
    """Ein Ausreisser weit neben der Bahn darf die Strecke nicht aufblaehen."""
    pts = [_pt(T0, 0, lat=46.50), _pt(T0, 10, lat=46.501),
           _pt(T0, 20, lat=52.0),            # 600 km in 10 s
           _pt(T0, 30, lat=46.502)]
    out = og._drop_jumps(pts)
    assert len(out) == 3
    assert all(q[1] < 47 for q in out)


def test_anker_wird_neu_gesetzt_wenn_der_sprung_bleibt():
    """Wandert das Geraet wirklich, darf nicht der ganze Rest wegfallen.

    Sonst kappt ein einziger falscher Ankerpunkt den kompletten Flug.
    """
    pts = [_pt(T0, 0, lat=46.5)]
    pts += [_pt(T0, 10 * i, lat=48.0 + 0.001 * i) for i in range(1, 8)]
    out = og._drop_jumps(pts)
    assert len(out) > og.MAX_JUMP_SKIP + 1


def test_gleiche_zeitstempel_erzeugen_keine_division_durch_null():
    pts = [_pt(T0, 0), _pt(T0, 0, lat=46.6), _pt(T0, 10)]
    assert og._drop_jumps(pts)


# --------------------------------------------------------------------------
# Boden vs. Luft
# --------------------------------------------------------------------------

def test_stehendes_geraet_gilt_nicht_als_bewegt():
    """Ein eingeschaltetes Instrument am Startplatz ist kein Flug."""
    pts = [_pt(T0, 10 * i, alt=1500) for i in range(30)]
    assert og._trim_ground(pts) is None


def test_standzeit_vor_dem_start_wird_abgeschnitten():
    """Sonst zaehlt die Wartezeit am Startplatz als Airtime."""
    steht = [_pt(T0, 10 * i, alt=1500) for i in range(30)]
    fliegt = [_pt(T0, 300 + 10 * i, alt=1500 + 30 * i, lat=46.5 + 0.002 * i)
              for i in range(30)]
    seg = og._trim_ground(steht + fliegt)
    assert seg is not None
    assert seg[0][0] >= steht[-1][0] - timedelta(seconds=og.MOVE_WINDOW_S)
    assert len(seg) < len(steht) + len(fliegt)


def test_soaring_ohne_streckenzuwachs_zaehlt_als_bewegung():
    """Am Hang bewegt sich ein Schirm kaum horizontal — die Hoehe verraet ihn."""
    pts = [_pt(T0, 10 * i, alt=1500 + (40 if i % 2 else 0)) for i in range(20)]
    assert og._trim_ground(pts) is not None


# --------------------------------------------------------------------------
# Steigwerte
# --------------------------------------------------------------------------

def test_steigen_nur_ueber_positive_werte():
    """Wer Sinken mitmittelt, misst den Gleitwinkel statt die Thermik."""
    seg = [_pt(T0, 10 * i, climb=(2.0 if i % 2 else -3.0)) for i in range(40)]
    p75, cmax, n = og._climb_aggregates(seg)
    assert p75 == 2.0 and cmax == 2.0
    assert n == 20


def test_grobe_steig_ausreisser_fliegen_raus():
    """50.79 m/s (10 000 fpm) kam real vor und verdirbt jedes Maximum."""
    seg = [_pt(T0, 10 * i, climb=2.0) for i in range(20)]
    seg.append(_pt(T0, 999, climb=50.79))
    _p75, cmax, _n = og._climb_aggregates(seg)
    assert cmax == 2.0


def test_zu_wenige_messwerte_ergeben_keine_zahl():
    """Lieber keine Angabe als eine aus drei Punkten."""
    seg = [_pt(T0, 10 * i, climb=2.0) for i in range(og.MIN_CLIMB_SAMPLES - 1)]
    p75, cmax, n = og._climb_aggregates(seg)
    assert p75 is None and cmax is None
    assert n == og.MIN_CLIMB_SAMPLES - 1


# --------------------------------------------------------------------------
# Ende zu Ende gegen eine echte SQLite-Datei
# --------------------------------------------------------------------------

def _db(tmp_path, monkeypatch, beacons):
    """Baut eine Mini-Datenbank und haengt Gelaende/Regionen ab."""
    import sqlite3
    p = tmp_path / "ogn_tracks.db"
    monkeypatch.setattr(og, "DB_PATH", p)
    conn = sqlite3.connect(str(p))
    conn.execute("""CREATE TABLE beacons (device_hash TEXT, ts TEXT, lat REAL,
                    lon REAL, alt_m INTEGER, climb_ms REAL,
                    aircraft_type INTEGER, receiver TEXT)""")
    conn.executemany("INSERT INTO beacons VALUES (?,?,?,?,?,?,?,?)", beacons)
    conn.commit()
    og.init_db(conn)
    # Gelaende: flache 1000 m, ohne Netzabfrage.
    monkeypatch.setattr(og, "terrain_lookup",
                        lambda c, pts: {og._grid_key(la, lo): 1000.0
                                        for la, lo in pts})
    monkeypatch.setattr(og, "_load_spots", lambda: [("Testberg", "Testregion",
                                                     46.5, 8.0)])

    class _Reg:
        def __call__(self, lat, lon):
            return "Testregion"
    monkeypatch.setattr(og, "RegionLookup", _Reg)
    return conn


def _row(dev, t0, sek, lat, lon, alt, climb=1.5):
    ts = (t0 + timedelta(seconds=sek)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (dev, ts, lat, lon, alt, climb, 7, "TESTRECV")


def test_echter_flug_wird_erkannt(tmp_path, monkeypatch):
    beacons = [_row("dev1", T0, 10 * i, 46.5 + 0.001 * i, 8.0, 1600 + 20 * i)
               for i in range(60)]
    conn = _db(tmp_path, monkeypatch, beacons)
    try:
        assert og.build_flights(conn, "2026-08-15") == 1
        r = conn.execute("SELECT duration_min, max_alt_m, max_height_agl_m, "
                         "region, launch_spot FROM flights").fetchone()
        assert r[0] == pytest.approx(9.8, abs=0.2)
        assert r[1] == 1600 + 20 * 59
        assert r[2] == r[1] - 1000
        assert r[3] == "Testregion"
        assert r[4] == "Testberg"
    finally:
        conn.close()


def test_geraet_am_boden_wird_nicht_als_flug_gezaehlt(tmp_path, monkeypatch):
    """Der 364-min-Fall: viel Zeit, kaum Strecke, praktisch kein Abstand zum Grund.

    Das Hoehen-Rauschen allein reicht ueber MIN_ALT_SPAN_M — erst die Hoehe
    ueber Grund entlarvt es.
    """
    beacons = []
    for i in range(400):
        alt = 1000 + (120 if i % 7 == 0 else 0)      # Rauschen ueber der Spanne
        beacons.append(_row("dev1", T0, 30 * i, 46.5 + 0.00002 * i, 8.0, alt))
    conn = _db(tmp_path, monkeypatch, beacons)
    try:
        assert og.build_flights(conn, "2026-08-15") == 0
    finally:
        conn.close()


def test_agl_unter_grund_wird_nicht_als_zahl_gefuehrt(tmp_path, monkeypatch):
    """Lieber eine fehlende Messung als eine erfundene.

    Unplausible AGL-Werte wuerden sonst die Empfangs-Kennzahl speisen und eine
    Region beim Steigvergleich besser aussehen lassen, als sie war.
    """
    beacons = [_row("dev1", T0, 10 * i, 46.5 + 0.001 * i, 8.0, 1600 + 20 * i)
               for i in range(60)]
    # Ein Tiefpunkt weit unter dem Gelaende (1000 m).
    beacons.append(_row("dev1", T0, 605, 46.56, 8.0, 400))
    conn = _db(tmp_path, monkeypatch, beacons)
    try:
        og.build_flights(conn, "2026-08-15")
        lo = conn.execute("SELECT min_height_agl_m FROM flights").fetchone()[0]
        assert lo is None
    finally:
        conn.close()


def test_zweiter_lauf_verdoppelt_nichts(tmp_path, monkeypatch):
    """Der Scheduler-Hook darf gefahrlos zweimal laufen."""
    beacons = [_row("dev1", T0, 10 * i, 46.5 + 0.001 * i, 8.0, 1600 + 20 * i)
               for i in range(60)]
    conn = _db(tmp_path, monkeypatch, beacons)
    try:
        og.build_flights(conn, "2026-08-15")
        og.build_flights(conn, "2026-08-15")
        assert conn.execute("SELECT COUNT(*) FROM flights").fetchone()[0] == 1
    finally:
        conn.close()


def test_startpunkt_in_der_luft_ist_als_solcher_erkennbar(tmp_path, monkeypatch):
    """Der Unterschied, an dem die Frage "wo wird gestartet" haengt.

    Zwei Drittel der echten Fluege beruehren den Boden nie am Anfang — ihr
    "Start" ist bloss der Moment, in dem der Empfang einsetzte. Ein solcher
    Flug kann trotzdem am Boden LANDEN. Dann ist der tiefste Punkt klein und
    sieht harmlos aus, waehrend launch_lat/lon in Wahrheit mitten in der Luft
    liegt. Nur takeoff_agl_m trennt die beiden Faelle.
    """
    # Beginnt 900 m ueber Grund (Gelaende 1000 m), sinkt bis auf Grundniveau.
    beacons = [_row("dev1", T0, 10 * i, 46.5 + 0.001 * i, 8.0, 1900 - 15 * i)
               for i in range(60)]
    conn = _db(tmp_path, monkeypatch, beacons)
    try:
        og.build_flights(conn, "2026-08-15")
        r = conn.execute("SELECT takeoff_agl_m, landing_agl_m, "
                         "min_height_agl_m FROM flights").fetchone()
        assert r[0] == 900          # Start hoch in der Luft -> kein echter Start
        assert r[1] == 15           # Landung praktisch am Boden
        assert r[2] == 15           # der tiefste Punkt allein verriete es NICHT
    finally:
        conn.close()


def test_echter_startpunkt_wird_als_bodennah_gefuehrt(tmp_path, monkeypatch):
    """Umgekehrt: startet der Flug am Boden, ist die Koordinate brauchbar."""
    beacons = [_row("dev1", T0, 10 * i, 46.5 + 0.001 * i, 8.0, 1005 + 20 * i)
               for i in range(60)]
    conn = _db(tmp_path, monkeypatch, beacons)
    try:
        og.build_flights(conn, "2026-08-15")
        r = conn.execute("SELECT takeoff_agl_m, launch_spot FROM flights"
                         ).fetchone()
        assert r[0] == 5
        assert r[1] == "Testberg"
    finally:
        conn.close()


def test_landepunkt_wird_mitgeschrieben(tmp_path, monkeypatch):
    """Start UND Landung — die Landung war anfangs nur als Hoehe erfasst.

    Ohne Koordinate weiss man, wie hoch ueber Grund ein Flug endete, aber nicht
    wo. Fuer Landeplaetze ist genau das die Frage.
    """
    beacons = [_row("dev1", T0, 10 * i, 46.5 + 0.001 * i, 8.0 + 0.002 * i,
                    1005 + 20 * i) for i in range(60)]
    conn = _db(tmp_path, monkeypatch, beacons)
    try:
        og.build_flights(conn, "2026-08-15")
        r = conn.execute("SELECT launch_lat, launch_lon, landing_lat, "
                         "landing_lon, landing_region FROM flights").fetchone()
        assert (r[0], r[1]) == (46.5, 8.0)
        assert r[2] == pytest.approx(46.559, abs=.001)
        assert r[3] == pytest.approx(8.118, abs=.001)
        assert r[4] == "Testregion"
        assert (r[0], r[1]) != (r[2], r[3])
    finally:
        conn.close()


def test_migration_ergaenzt_fehlende_spalten(tmp_path, monkeypatch):
    """Bestehende Datenbanken duerfen die neuen Spalten nicht stumm vermissen."""
    import sqlite3
    p = tmp_path / "alt.db"
    monkeypatch.setattr(og, "DB_PATH", p)
    conn = sqlite3.connect(str(p))
    # Schema vom 17.08. vormittags — vor takeoff_agl_m / landing_agl_m.
    conn.execute("""CREATE TABLE flights (
        device_hash TEXT, date TEXT, takeoff_ts TEXT, landing_ts TEXT,
        duration_min REAL, launch_lat REAL, launch_lon REAL, launch_spot TEXT,
        region TEXT, max_alt_m INTEGER, max_height_agl_m INTEGER,
        min_height_agl_m INTEGER, alt_span_m INTEGER, climb_p75 REAL,
        climb_max REAL, climb_samples INTEGER, distance_km REAL,
        n_beacons INTEGER, aircraft_type INTEGER,
        PRIMARY KEY (device_hash, takeoff_ts))""")
    conn.commit()
    try:
        og.init_db(conn)
        have = {r[1] for r in conn.execute("PRAGMA table_info(flights)")}
        assert {"takeoff_agl_m", "landing_agl_m",
                "landing_lat", "landing_lon", "landing_region"} <= have
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Aufbewahrung: 7 Tage sind nur gefahrlos, wenn nichts Unverdichtetes faellt
# --------------------------------------------------------------------------

def _alter_tag(conn, tage_alt, n=5):
    """Legt Rohpunkte, die aelter sind als die Aufbewahrungsfrist."""
    t = datetime.now(timezone.utc) - timedelta(days=tage_alt)
    tag = t.strftime("%Y-%m-%d")
    conn.executemany(
        "INSERT INTO beacons VALUES (?,?,?,?,?,?,?,?)",
        [("dev1", (t + timedelta(seconds=10 * i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
          46.5, 8.0, 1500, 1.0, 7, "TESTRECV") for i in range(n)])
    conn.commit()
    return tag


def test_unverdichtete_tage_werden_nicht_geloescht(tmp_path, monkeypatch):
    """Der eigentliche Schutz: alt genug allein reicht nicht.

    Ohne ihn haette eine still ausgefallene Verdichtung die Rohdaten nach
    einer Woche mitgenommen — und niemand haette es gemerkt.
    """
    conn = _db(tmp_path, monkeypatch, [])
    try:
        _alter_tag(conn, og.RETENTION_DAYS + 3)
        assert og.prune_beacons(conn) == 0
        assert conn.execute("SELECT COUNT(*) FROM beacons").fetchone()[0] == 5
    finally:
        conn.close()


def test_verdichtete_tage_werden_geloescht(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch, [])
    try:
        tag = _alter_tag(conn, og.RETENTION_DAYS + 3)
        conn.execute("INSERT INTO rollup_log (date, processed_at, flights, "
                     "regions) VALUES (?,?,?,?)", (tag, "x", 0, 0))
        conn.commit()
        assert og.prune_beacons(conn) == 5
        assert conn.execute("SELECT COUNT(*) FROM beacons").fetchone()[0] == 0
    finally:
        conn.close()


def test_junge_tage_bleiben_auch_wenn_verdichtet(tmp_path, monkeypatch):
    """Innerhalb der Frist wird nichts weggeworfen, auch Verdichtetes nicht."""
    conn = _db(tmp_path, monkeypatch, [])
    try:
        tag = _alter_tag(conn, 1)
        conn.execute("INSERT INTO rollup_log (date, processed_at, flights, "
                     "regions) VALUES (?,?,?,?)", (tag, "x", 0, 0))
        conn.commit()
        assert og.prune_beacons(conn) == 0
    finally:
        conn.close()


def test_run_day_vermerkt_den_tag_als_verdichtet(tmp_path, monkeypatch):
    """Erst der Vermerk gibt die Rohpunkte zum Wegwerfen frei."""
    beacons = [_row("dev1", T0, 10 * i, 46.5 + 0.001 * i, 8.0, 1600 + 20 * i)
               for i in range(60)]
    conn = _db(tmp_path, monkeypatch, beacons)
    try:
        og.run_day(conn, "2026-08-15")
        r = conn.execute("SELECT date, flights FROM rollup_log").fetchone()
        assert r[0] == "2026-08-15" and r[1] == 1
    finally:
        conn.close()


def test_unverdichtete_tage_werden_gemeldet(tmp_path, monkeypatch):
    """Bei kurzer Aufbewahrung ist das die Zahl, auf die man schaut."""
    conn = _db(tmp_path, monkeypatch, [])
    try:
        tag = _alter_tag(conn, 2)
        assert og.unverdichtete_tage(conn) == [tag]
        conn.execute("INSERT INTO rollup_log (date, processed_at, flights, "
                     "regions) VALUES (?,?,?,?)", (tag, "x", 0, 0))
        conn.commit()
        assert og.unverdichtete_tage(conn) == []
    finally:
        conn.close()


def test_empfangslage_wird_je_region_geschrieben(tmp_path, monkeypatch):
    beacons = [_row("dev1", T0, 10 * i, 46.5 + 0.001 * i, 8.0, 1600 + 20 * i)
               for i in range(60)]
    conn = _db(tmp_path, monkeypatch, beacons)
    try:
        og.build_flights(conn, "2026-08-15")
        assert og.build_coverage(conn, "2026-08-15") == 1
        r = conn.execute("SELECT region, receivers, devices, flights, beacons "
                         "FROM coverage").fetchone()
        assert r[0] == "Testregion"
        assert r[1] == 1 and r[2] == 1 and r[3] == 1 and r[4] == 60
    finally:
        conn.close()
