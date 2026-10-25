"""Planer im Minutentakt mit Merkzettel (scheduler._takt).

Hintergrund: In der Nacht auf den 25.10.2026 (Umstellung auf Winterzeit)
rechnete der alte Planer um 02:11 "noch 2.8 h bis 05:00" und schlief sie am
Stueck. Die Uhr sprang dazwischen eine Stunde zurueck — er wachte um 04:00
auf, lief, sah 05:00 noch vor sich und lief nochmals. Alle 16 Abos bekamen
ihr Briefing doppelt, die LLM-Analyse lief zweimal.

Diese Tests spielen die Nacht Minute fuer Minute so durch, wie die Wanduhr sie
zeigt, und halten fest: jeder Termin laeuft genau einmal — auch wenn eine
Uhrzeit doppelt vorkommt (Herbst) oder ausfaellt (Fruehling), und auch ueber
Neustarts hinweg.
"""
from datetime import datetime, timedelta

import pytest

import config
import scheduler


@pytest.fixture
def planer(monkeypatch, tmp_path):
    """Tageslauf um 05:00 an jedem Tag, alle Jobs durch Protokoll ersetzt."""
    monkeypatch.setattr(scheduler, "ZUSTAND_DATEI", tmp_path / ".scheduler_zustand.json")
    monkeypatch.setattr(config, "DAILY_RUN_HOUR", 5)
    monkeypatch.setattr(config, "DAILY_RUN_MINUTE", 0)
    monkeypatch.setattr(config, "DAILY_RUN_WEEKDAYS", {0, 1, 2, 3, 4, 5, 6})
    monkeypatch.setattr(scheduler, "_fronten_aktiv", lambda: True)
    # Nachlauf nie "in Produktion" — er soll hier nur sichtbar werden, nicht laufen.
    monkeypatch.setattr(config, "BASE_URL", "http://localhost:5000")

    protokoll = []
    uhr = {"jetzt": None}
    monkeypatch.setattr(scheduler, "_daily_run",
                        lambda engine, nachlauf_vorher=None:
                            protokoll.append(("tageslauf", uhr["jetzt"])) or {})
    monkeypatch.setattr(scheduler, "_run_fronten",
                        lambda: protokoll.append(("fronten", uhr["jetzt"])) or True)
    monkeypatch.setattr(scheduler, "_send_accuracy_once",
                        lambda: protokoll.append(("accuracy", uhr["jetzt"])) or {})

    def ticke(minuten):
        """Ein _takt je Wanduhr-Minute, wie die Schleife im Dienst."""
        for jetzt in minuten:
            uhr["jetzt"] = jetzt
            scheduler._takt(None, jetzt)
        return protokoll

    return ticke


def _minuten(von: datetime, bis: datetime):
    t = von
    while t <= bis:
        yield t
        t += timedelta(minutes=1)


def _ohne_fronten(jobs):
    """Startet ein Test mitten am Tag, holt der Planer den 02:10-Frontenlauf
    zu Recht nach — fuer den Tageslauf zaehlt er nicht."""
    return [j for j in jobs if j != "fronten"]


def _vortag_erledigt(tag: str):
    """Merkzettel, wie er am Vorabend nach normalem Betrieb aussieht."""
    vortag = (datetime.fromisoformat(tag) - timedelta(days=1)).date().isoformat()
    scheduler._vermerke(tageslauf=vortag, tageslauf_fertig=vortag,
                        fronten=f"{vortag}T20:10", accuracy="")


def test_herbst_umstellung_genau_ein_lauf(planer):
    """25.10.2026: 02:00-02:59 kommt zweimal vor. Tageslauf genau einmal um
    05:00, der Fronten-Termin 02:10 genau einmal."""
    _vortag_erledigt("2026-10-25")
    d = datetime(2026, 10, 25)
    wanduhr = (list(_minuten(d, d.replace(hour=2, minute=59)))           # Sommerzeit
               + list(_minuten(d.replace(hour=2), d.replace(hour=9))))   # Winterzeit
    protokoll = planer(wanduhr)

    assert protokoll == [
        ("fronten", d.replace(hour=2, minute=10)),
        ("tageslauf", d.replace(hour=5)),
        ("fronten", d.replace(hour=8, minute=10)),
    ]


def test_fruehling_umstellung_genau_ein_lauf(planer):
    """28.03.2027: 02:00-02:59 gibt es nicht. Tageslauf trotzdem puenktlich um
    05:00; der ausgefallene Fronten-Termin 02:10 laeuft um 03:00, einmal."""
    _vortag_erledigt("2027-03-28")
    d = datetime(2027, 3, 28)
    wanduhr = (list(_minuten(d, d.replace(hour=1, minute=59)))
               + list(_minuten(d.replace(hour=3), d.replace(hour=9))))
    protokoll = planer(wanduhr)

    assert protokoll == [
        ("fronten", d.replace(hour=3)),
        ("tageslauf", d.replace(hour=5)),
        ("fronten", d.replace(hour=8, minute=10)),
    ]


def test_ganze_woche_jeden_tag_einmal(planer):
    _vortag_erledigt("2026-10-20")
    start = datetime(2026, 10, 20)
    protokoll = planer(_minuten(start, start + timedelta(days=7) - timedelta(minutes=1)))
    tageslaeufe = [t for job, t in protokoll if job == "tageslauf"]
    assert tageslaeufe == [start + timedelta(days=i, hours=5) for i in range(7)]


def test_neustart_nach_dem_lauf_loest_keinen_zweiten_aus(planer):
    """Der Merkzettel liegt auf der Platte: ein neuer Prozess (= neue Ticks
    ohne Gedaechtnis im Speicher) sieht den Lauf von heute."""
    _vortag_erledigt("2026-10-26")
    d = datetime(2026, 10, 26)
    planer(_minuten(d.replace(hour=4, minute=58), d.replace(hour=5, minute=2)))
    scheduler._erststart_vermerken(d.replace(hour=5, minute=3))   # Neustart
    protokoll = planer(_minuten(d.replace(hour=5, minute=3), d.replace(hour=7)))
    assert [job for job, _ in protokoll if job != "fronten"] == ["tageslauf"]


def test_zeit_verschoben_nach_dem_lauf_kein_zweiter(planer):
    """Admin stellt nach dem Morgenlauf die Uhrzeit spaeter — heute nicht nochmal."""
    _vortag_erledigt("2026-10-26")
    d = datetime(2026, 10, 26)
    planer(_minuten(d.replace(hour=4, minute=59), d.replace(hour=5, minute=1)))
    config.DAILY_RUN_HOUR = 6          # monkeypatch der Fixture stellt zurueck
    protokoll = planer(_minuten(d.replace(hour=5, minute=2), d.replace(hour=6, minute=30)))
    assert [job for job, _ in protokoll if job != "fronten"] == ["tageslauf"]


def test_abbruch_mitten_im_lauf_wird_nicht_als_normallauf_wiederholt(planer, monkeypatch):
    """Faellt der Lauf aus (Exception, Neustart), ist er laut Merkzettel
    angefangen, aber nicht fertig. Der naechste Blick startet den Nachlauf —
    nie einen zweiten Normallauf mit Mails an alle."""
    _vortag_erledigt("2026-10-26")
    d = datetime(2026, 10, 26)

    def _bricht_ab(engine, nachlauf_vorher=None):
        raise RuntimeError("Neustart mitten im Lauf")

    monkeypatch.setattr(scheduler, "_daily_run", _bricht_ab)
    with pytest.raises(RuntimeError):
        scheduler._takt(None, d.replace(hour=5))

    gesehen = []
    monkeypatch.setattr(scheduler, "_nachlauf",
                        lambda engine, now: gesehen.append(now))
    assert _ohne_fronten(scheduler._takt(None, d.replace(hour=5, minute=1))) == ["nachlauf"]
    assert gesehen == [d.replace(hour=5, minute=1)]


def test_verpasster_termin_wird_nachlauf(planer, monkeypatch):
    """Dienst war um 05:00 weg und ist um 06:30 wieder da: kein Normallauf
    (der wuerde an alle senden), sondern Nachlauf mit seinen Regeln."""
    _vortag_erledigt("2026-10-26")
    d = datetime(2026, 10, 26)
    assert _ohne_fronten(scheduler._takt(None, d.replace(hour=5, minute=10))) == ["regulaer"]   # puenktlich genug
    _vortag_erledigt("2026-10-27")
    assert _ohne_fronten(scheduler._takt(None, datetime(2026, 10, 27, 6, 30))) == ["nachlauf"]


def test_monatsmail_einmal_am_ersten(planer):
    _vortag_erledigt("2026-11-01")
    d = datetime(2026, 11, 1)
    protokoll = planer(_minuten(d.replace(hour=6, minute=58), d.replace(hour=9)))
    assert ("accuracy", d.replace(hour=7)) in protokoll
    assert [job for job, _ in protokoll].count("accuracy") == 1


def test_erster_start_holt_nichts_nach(planer):
    """Erster Start mit Merkzettel am Monatsersten um 09:00: die Monatsmail
    und der 08:10-Frontenlauf gelten als erledigt — der alte Planer hat sie
    gemacht. Sonst bekaemen alle die Monatsmail ein zweites Mal."""
    d = datetime(2026, 11, 1, 9)
    scheduler._erststart_vermerken(d)
    scheduler._vermerke(tageslauf_fertig="2026-11-01")
    protokoll = planer(_minuten(d, d.replace(hour=14, minute=9)))
    assert protokoll == []
    protokoll = planer([d.replace(hour=14, minute=10)])
    assert protokoll == [("fronten", d.replace(hour=14, minute=10))]


def test_kaputter_merkzettel_bleibt_lesbar(planer):
    """Schreiben ist atomar; eine unlesbare Datei gilt als leer statt den
    Planer anzuhalten."""
    scheduler.ZUSTAND_DATEI.write_text("{kaputt", encoding="utf-8")
    assert scheduler._lade_zustand() == {}
    scheduler._vermerke(fronten="2026-10-26T08:10")
    assert scheduler._lade_zustand() == {"fronten": "2026-10-26T08:10"}
