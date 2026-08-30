# -*- coding: utf-8 -*-
"""Schutz fuer den Archiv-Waechter und das Nachholen (Vorgabe vom 12.08.2026).

Geprueft werden die drei Ausfallbilder, die real passiert sind — jedes hat
Archivtage gekostet und keines hat sich von selbst gemeldet:

  fehlt          Neustart kurz nach 06:00, der Lauf faellt ersatzlos aus
                 (neun Tage zwischen Mai und Juli 2026)
  abgeschnitten  Lauf traf die Wetterdatei halb geschrieben an
                 (23.06.2026: 28 von 494 Startplaetzen)
  keine_regionen Snapshot ohne Regionsebene
                 (01.07.-01.08.2026: 29 Tage, gefunden erst Wochen spaeter)

Dazu die zwei Betriebsregeln, an denen so ein Waechter sonst stirbt: er darf
nicht bei jedem Neustart erneut melden, und er darf nicht bei jedem Neustart
eine volle LLM-Analyse ausloesen.
"""
import json
from datetime import datetime, timedelta

import pytest

from scripts import snapshot_wache as wache


def _tag(archiv, tag, spots=494, regionen=29, spots_bewertet=None,
         regionen_bewertet=None, schema=2):
    """Schreibt einen Archivtag in der Struktur von scripts/snapshot_weather.py."""
    spots_bewertet = spots if spots_bewertet is None else spots_bewertet
    regionen_bewertet = regionen if regionen_bewertet is None else regionen_bewertet
    daten = {
        "_meta": {"forecast_date": tag, "schema_version": schema,
                  "spots_with_analysis": spots_bewertet,
                  "regions_with_analysis": regionen_bewertet},
        "spots": {f"spot_{i}": {"analysis": {"rating": 3} if i < spots_bewertet else None}
                  for i in range(spots)},
        "regions": {f"region_{i}": {"analysis": {"rating": 3} if i < regionen_bewertet else None}
                    for i in range(regionen)},
    }
    (archiv / f"{tag}.json").write_text(json.dumps(daten), encoding="utf-8")


@pytest.fixture
def archiv(tmp_path, monkeypatch):
    """Leeres Archiv plus eigene Zustandsdatei — nie das echte data/ anfassen."""
    d = tmp_path / "weather_archive"
    d.mkdir()
    monkeypatch.setattr(wache, "ARCHIVE_DIR", d)
    monkeypatch.setattr(wache, "ZUSTAND_DATEI", tmp_path / ".snapshot_wache.json")
    return d


# ---------------------------------------------------------------------------
# Befund
# ---------------------------------------------------------------------------

def test_vollstaendiger_tag_ist_still(archiv):
    _tag(archiv, "2026-08-11")
    _tag(archiv, "2026-08-12")
    b = wache.befund("2026-08-12")
    assert b["maengel"] == []
    assert wache.brauchbar("2026-08-12")


def test_fehlender_tag_faellt_auf(archiv):
    _tag(archiv, "2026-08-11")
    assert wache.befund("2026-08-12")["maengel"] == ["fehlt"]


def test_abgeschnittener_tag_faellt_auf(archiv):
    """Der 23.06.2026: Datei da, Groesse plausibel, Inhalt 6 Prozent."""
    _tag(archiv, "2026-06-22", spots=494)
    _tag(archiv, "2026-06-23", spots=28)
    b = wache.befund("2026-06-23")
    assert "abgeschnitten" in b["maengel"]
    assert b["referenz_spots"] == 494


def test_wachsender_bestand_ist_kein_mangel(archiv):
    """487 -> 494 ist Zuwachs an Startplaetzen, kein Ausfall.

    Eine feste Erwartungszahl waere seit Mai zweimal falsch gewesen; darum
    Referenz = juengster aelterer Tag mit 10 Prozent Toleranz.
    """
    _tag(archiv, "2026-05-22", spots=487)
    _tag(archiv, "2026-05-23", spots=488)
    assert wache.befund("2026-05-23")["maengel"] == []


def test_referenz_ueberspringt_luecken(archiv):
    """Fehlt der Vortag, zaehlt der naechste vorhandene Tag davor."""
    _tag(archiv, "2026-06-30", spots=494)
    _tag(archiv, "2026-07-10", spots=100)
    b = wache.befund("2026-07-10")
    assert b["referenz_spots"] == 494
    assert "abgeschnitten" in b["maengel"]


def test_ohne_referenz_nur_leerer_tag_faellt_auf(archiv):
    """Erster Tag ueberhaupt: ohne Vergleich wird nicht geraten."""
    _tag(archiv, "2026-05-18", spots=487)
    assert wache.befund("2026-05-18")["maengel"] == []


def test_fehlende_regionsebene_faellt_auf(archiv):
    """Der Juli-Ausfall: 494 Spots wie immer, Regionsebene leer."""
    _tag(archiv, "2026-06-30")
    _tag(archiv, "2026-07-01", regionen=0)
    assert "keine_regionen" in wache.befund("2026-07-01")["maengel"]


def test_fehlende_bewertung_faellt_auf(archiv):
    """Wetterwerte ohne LLM-Analyse: sieht vollstaendig aus, ist nicht validierbar."""
    _tag(archiv, "2026-08-11")
    _tag(archiv, "2026-08-12", spots_bewertet=0, regionen_bewertet=0)
    assert "keine_spot_bewertung" in wache.befund("2026-08-12")["maengel"]


def test_fehlende_regionsurteile_erst_ab_schema_2(archiv):
    """Vor schema 2 trug KEIN Tag Regionsurteile — das als Mangel zu werten
    haette die halbe Historie rot gefaerbt und den Waechter entwertet."""
    _tag(archiv, "2026-05-20", schema=1, regionen_bewertet=0)
    _tag(archiv, "2026-05-21", schema=1, regionen_bewertet=0)
    assert wache.befund("2026-05-21")["maengel"] == []

    _tag(archiv, "2026-08-12", schema=2, regionen_bewertet=0)
    assert "keine_regions_bewertung" in wache.befund("2026-08-12")["maengel"]


def test_unlesbare_datei_faellt_auf(archiv):
    (archiv / "2026-08-12.json").write_text("{kaputt", encoding="utf-8")
    assert wache.befund("2026-08-12")["maengel"] == ["unlesbar"]


def test_alter_snapshot_ohne_zaehler_wird_gezaehlt(archiv):
    """schema_version 1 fuehrt spots_with_analysis nicht — dann selbst zaehlen."""
    daten = {"_meta": {"schema_version": 1},
             "spots": {"a": {"analysis": {"r": 1}}, "b": {"analysis": None}},
             "regions": {"r1": {"analysis": {"r": 1}}}}
    (archiv / "2026-05-18.json").write_text(json.dumps(daten), encoding="utf-8")
    b = wache.befund("2026-05-18")
    assert b["spots_bewertet"] == 1
    assert b["regionen_bewertet"] == 1


def test_luecken_findet_fehlende_und_unvollstaendige(archiv):
    _tag(archiv, "2026-08-08")
    _tag(archiv, "2026-08-09", regionen=0)      # unvollstaendig
    #    2026-08-10 fehlt ganz
    _tag(archiv, "2026-08-11")
    offen = wache.luecken()
    assert [b["tag"] for b in offen] == ["2026-08-09", "2026-08-10"]
    assert offen[1]["maengel"] == ["fehlt"]


# ---------------------------------------------------------------------------
# Meldung
# ---------------------------------------------------------------------------

@pytest.fixture
def postfach(monkeypatch):
    raus = []
    monkeypatch.setattr(wache, "_sende",
                        lambda betreff, text, versand=True: raus.append(betreff))
    return raus


def test_meldung_nur_einmal_pro_tag(archiv, postfach):
    """Der Waechter laeuft bei jedem Neustart. Ein taeglich gleicher Alarm
    wird ignoriert — dann ist er wertlos."""
    _tag(archiv, "2026-08-11")
    b = wache.befund("2026-08-12")
    assert "gemeldet" in wache.melde(b)
    assert wache.melde(b).startswith("schon gemeldet")
    assert len(postfach) == 1


def test_neuer_tag_meldet_wieder(archiv, postfach):
    _tag(archiv, "2026-08-11")
    wache.melde(wache.befund("2026-08-12"))
    wache.melde(wache.befund("2026-08-13"))
    assert len(postfach) == 2


def test_heiler_tag_meldet_nicht(archiv, postfach):
    _tag(archiv, "2026-08-11")
    _tag(archiv, "2026-08-12")
    assert wache.pruefe_und_melde("2026-08-12")["maengel"] == []
    assert postfach == []


def test_nachlauf_meldet_auch_bei_erfolg(archiv, postfach):
    """Dass ein Lauf ueberhaupt ausgefallen ist, gehoert gesehen — sonst
    faellt ein schleichendes Problem (jeder Deploy am Morgen) nie auf."""
    vorher = {"tag": "2026-08-12", "maengel": ["fehlt"]}
    nachher = {"tag": "2026-08-12", "maengel": [], "spots": 494,
               "spots_bewertet": 494, "regionen": 29, "regionen_bewertet": 29}
    assert "ok" in wache.melde_nachlauf(vorher, nachher)
    assert len(postfach) == 1
    assert "nachgeholt" in postfach[0]
    # zweiter Start am selben Tag meldet nicht erneut
    wache.melde_nachlauf(vorher, nachher)
    assert len(postfach) == 1


def test_nachlauf_meldet_misserfolg_deutlich(archiv, postfach):
    vorher = {"tag": "2026-08-12", "maengel": ["fehlt"]}
    nachher = {"tag": "2026-08-12", "maengel": ["keine_spot_bewertung"]}
    wache.melde_nachlauf(vorher, nachher)
    assert "NICHT gerettet" in postfach[0]


def test_meldung_unterscheidet_snapshot_von_briefing_ausfall(archiv, monkeypatch):
    """Der Kern der Unterscheidung: nur weil der Snapshot fehlt, ist der
    Versand nicht ausgefallen. Beides sind getrennte Schritte im Daily-Run.
    Die Mail sagt, was gemessen wurde, statt es zu unterstellen."""
    briefe = []
    monkeypatch.setattr(wache, "_sende",
                        lambda betreff, text, versand=True: briefe.append(text))
    vorher = {"tag": "2026-08-12", "maengel": ["keine_spot_bewertung"]}
    nachher = {"tag": "2026-08-12", "maengel": [], "spots": 494,
               "spots_bewertet": 494, "regionen": 29, "regionen_bewertet": 29}

    # Fall A: Versand lief, nur das Archiv war kaputt
    wache.melde_nachlauf(vorher, nachher, briefings_heute=37)
    assert "37 Abo(s)" in briefe[0]
    assert "NUR das Archiv" in briefe[0]

    # Fall B: gar keine Mail raus -> der ganze Morgenlauf ist ausgefallen
    monkeypatch.setattr(wache, "_lade_zustand", lambda: {})   # Sperre loesen
    wache.melde_nachlauf(vorher, nachher, briefings_heute=0)
    assert "KEINE Mail aus dem Morgenlauf" in briefe[1]
    assert "ganze" in briefe[1]

    # Fall C: Datenbank nicht erreichbar -> nichts behaupten
    wache.melde_nachlauf(vorher, nachher, briefings_heute=None)
    assert "nicht feststellbar" in briefe[2]


def test_meldung_sagt_ob_nachversendet_wurde(archiv, monkeypatch):
    """Ohne Mail aus dem Morgenlauf sind drei Ausgaenge moeglich, und die
    Meldung muss sie unterscheiden: nachversendet, bewusst unterlassen
    (Zeitgrenze), oder gar nicht erst versucht. Frueher stand hier pauschal
    'nachgesendet wird bewusst nicht' — das war ab dem Nachversand falsch."""
    briefe = []
    monkeypatch.setattr(wache, "_sende",
                        lambda betreff, text, versand=True: briefe.append(text))
    monkeypatch.setattr(wache, "_lade_zustand", lambda: {})   # Sperre je Fall loesen
    vorher = {"tag": "2026-08-12", "maengel": ["keine_spot_bewertung"]}
    nachher = {"tag": "2026-08-12", "maengel": [], "spots": 494,
               "spots_bewertet": 494, "regionen": 29, "regionen_bewertet": 29}

    # Nachversendet
    wache.melde_nachlauf(vorher, nachher, briefings_heute=0,
                         nachversand={"sent": 12, "zeit": "06:47", "failed": 0})
    assert "12 Abo(s) um 06:47 nachversendet" in briefe[0]
    assert "Doppelversand ausgeschlossen" in briefe[0]

    # Unterlassen — die Zeitgrenze gehoert benannt, nicht verschwiegen
    wache.melde_nachlauf(vorher, nachher, briefings_heute=0,
                         nachversand={"sent": 0, "grund": "Grenze ist 09:00"})
    assert "unterblieben — Grenze ist 09:00" in briefe[1]

    # Nicht versucht
    wache.melde_nachlauf(vorher, nachher, briefings_heute=0)
    assert "nicht versucht" in briefe[2]


def test_nachhol_versuch_wird_vermerkt(archiv):
    assert wache.nachhol_versuch_offen("2026-08-12")
    wache.vermerke_nachhol_versuch("2026-08-12")
    assert not wache.nachhol_versuch_offen("2026-08-12")
    assert wache.nachhol_versuch_offen("2026-08-13")


def test_versandstand_wird_aus_der_abo_db_gelesen(tmp_path):
    """Die Meldung stuetzt sich auf eine Zahl aus der Abo-Datenbank —
    hier der Beleg, dass die Zahl stimmt."""
    import sqlite3

    from subscriber import SubscriberManager

    pfad = tmp_path / "subscribers.db"
    mgr = SubscriberManager(pfad)
    conn = sqlite3.connect(pfad)
    for i, gesendet in enumerate(["datetime('now')", "datetime('now', '-1 day')",
                                  "NULL"], start=1):
        conn.execute(
            f"INSERT INTO subscribers (email, regions, action_token, last_sent_at) "
            f"VALUES (?, '[]', ?, {gesendet})", (f"p{i}@example.ch", f"t{i}"))
    conn.commit()
    conn.close()
    assert mgr.count_sent_today() == 1


# ---------------------------------------------------------------------------
# Nachholen im Scheduler — der teure Pfad, darum eng gepruft
# ---------------------------------------------------------------------------

class _Engine:
    def __init__(self):
        self.refreshed = False

    def refresh_weather(self):
        self.refreshed = True


@pytest.fixture
def nachlauf(monkeypatch, archiv):
    """Scheduler mit abgeklemmter LLM-Analyse und Snapshot."""
    import config
    import scheduler
    # Der Nachlauf laeuft nur in Produktion (config.ops_produktion(), seit
    # 23.08.2026). Auf einem Entwicklungsrechner zeigt BASE_URL auf localhost,
    # sonst wuerden diese Tests je nach .env des Rechners gar nichts pruefen.
    monkeypatch.setattr(config, "BASE_URL", "https://app.wingcast.ch")
    monkeypatch.setattr(config, "OPS_PRODUKTION_HOST", "app.wingcast.ch")
    protokoll = []
    monkeypatch.setattr(scheduler, "_run_llm_analysis",
                        lambda engine: protokoll.append("analyse") or True)
    monkeypatch.setattr(scheduler, "_run_snapshot",
                        lambda: protokoll.append("snapshot") or True)
    monkeypatch.setattr(scheduler, "_snapshot_pruefen",
                        lambda nachgeholt=None: protokoll.append(f"wache:{nachgeholt}"))
    # Abo-Datenbank bleibt aussen vor — hier geht es um den Ablauf, nicht um
    # den Versandstand.
    monkeypatch.setattr(scheduler, "_briefings_heute", lambda: 0)
    monkeypatch.setattr(wache, "_sende",
                        lambda betreff, text, versand=True: protokoll.append("mail"))
    return scheduler, protokoll


def _zeit(monkeypatch, scheduler, stunde, minute=0, tag="2026-08-12"):
    """Friert datetime.now() im Scheduler ein."""
    fix = datetime.fromisoformat(f"{tag}T{stunde:02d}:{minute:02d}:00")

    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return fix

    monkeypatch.setattr(scheduler, "datetime", _DT)
    return fix


def test_nachlauf_holt_ausgefallenen_morgenlauf(nachlauf, monkeypatch, archiv):
    """06:03 Neustart, Archivtag fehlt -> Wetter, Analyse und Snapshot laufen."""
    scheduler, protokoll = nachlauf
    _zeit(monkeypatch, scheduler, 6, 3)
    _tag(archiv, "2026-08-11")
    eng = _Engine()
    scheduler._nachholen_falls_noetig(eng)
    assert eng.refreshed
    assert protokoll[:2] == ["analyse", "snapshot"]
    assert "mail" in protokoll


def test_kein_nachlauf_wenn_tag_schon_da(nachlauf, monkeypatch, archiv):
    """Der haeufigste Fall: Neustart am Nachmittag, alles laengst gelaufen."""
    scheduler, protokoll = nachlauf
    _zeit(monkeypatch, scheduler, 15)
    _tag(archiv, "2026-08-11")
    _tag(archiv, "2026-08-12")
    eng = _Engine()
    scheduler._nachholen_falls_noetig(eng)
    assert not eng.refreshed
    assert protokoll == []


def test_kein_nachlauf_vor_dem_slot(nachlauf, monkeypatch, archiv):
    """05:58: der regulaere Lauf kommt gleich, nichts vorwegnehmen."""
    scheduler, protokoll = nachlauf
    _zeit(monkeypatch, scheduler, 5, 58)
    _tag(archiv, "2026-08-11")
    eng = _Engine()
    scheduler._nachholen_falls_noetig(eng)
    assert not eng.refreshed
    assert protokoll == []


def test_kein_nachlauf_nach_mittag(nachlauf, monkeypatch, archiv):
    """Ein Snapshot um 14:00 waere ein Nowcast auf einen fast abgelaufenen Tag —
    als Prognose-Beleg wertlos. Dann lieber melden statt rechnen."""
    scheduler, protokoll = nachlauf
    _zeit(monkeypatch, scheduler, 14)
    _tag(archiv, "2026-08-11")
    eng = _Engine()
    scheduler._nachholen_falls_noetig(eng)
    assert not eng.refreshed
    assert protokoll == ["wache:False"]


def test_zweiter_neustart_loest_keinen_zweiten_lauf_aus(nachlauf, monkeypatch, archiv):
    """Neustart-Schleife darf nicht jedes Mal eine LLM-Analyse kosten."""
    scheduler, protokoll = nachlauf
    _zeit(monkeypatch, scheduler, 6, 3)
    _tag(archiv, "2026-08-11")
    scheduler._nachholen_falls_noetig(_Engine())
    protokoll.clear()
    eng2 = _Engine()
    scheduler._nachholen_falls_noetig(eng2)
    assert not eng2.refreshed
    assert protokoll == []


def test_kein_nachlauf_an_nicht_konfiguriertem_wochentag(nachlauf, monkeypatch, archiv):
    import config
    scheduler, protokoll = nachlauf
    _zeit(monkeypatch, scheduler, 9)                      # 12.08.2026 = Mittwoch
    monkeypatch.setattr(config, "DAILY_RUN_WEEKDAYS", {5, 6})
    _tag(archiv, "2026-08-11")
    eng = _Engine()
    scheduler._nachholen_falls_noetig(eng)
    assert not eng.refreshed
    assert protokoll == []
