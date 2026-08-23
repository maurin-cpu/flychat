# -*- coding: utf-8 -*-
"""Betriebsalarme nur vom Server (Vorgabe vom 23.08.2026).

Am 21. und 23.08.2026 kamen zwei Alarmmails "Archivtag verloren", beide vom
Entwicklungsrechner: dort fehlen Archiv und Abo-Datenbank, also findet der
Waechter zwangslaeufig einen Ausfall. Auf dem Server lief an beiden Tagen
alles. Ein Alarm, der oft grundlos kommt, wird ignoriert — und dann sieht
niemand mehr den echten.

Erkannt wird POSITIV am Hostnamen der App-Adresse. Diese Tests halten genau
das fest, was an einer Ausschlussliste ("alles ausser localhost") kaputt
gegangen waere: anderer Port, IP-Adresse, Adresse ohne Schema.
"""
import pytest

import config


@pytest.fixture(autouse=True)
def _kein_force(monkeypatch):
    """Der Notausgang darf keinen anderen Test verfaelschen."""
    monkeypatch.setattr(config, "OPS_ALERT_FORCE", False)
    monkeypatch.setattr(config, "OPS_PRODUKTION_HOST", "app.wingcast.ch")


@pytest.mark.parametrize("url", [
    "https://app.wingcast.ch",
    "https://app.wingcast.ch/",
    "https://app.wingcast.ch:8443",       # Port spielt keine Rolle
    "http://app.wingcast.ch",             # Schema spielt keine Rolle
    "APP.WINGCAST.CH",                    # Gross/klein, ohne Schema
])
def test_produktion_wird_erkannt(monkeypatch, url):
    monkeypatch.setattr(config, "BASE_URL", url)
    erlaubt, grund = config.ops_produktion()
    assert erlaubt, grund


@pytest.mark.parametrize("url", [
    "http://localhost:5000",
    "http://localhost:8080",              # anderer Port — der Fall, an dem
    "localhost:5000",                     # eine Portpruefung scheitern wuerde
    "http://127.0.0.1:5000",
    "http://192.168.1.42:5000",           # LAN-IP eines Testrechners
    "http://178.105.39.152:5000",         # Server ueber die IP statt die Domain
    "https://staging.wingcast.ch",
    "https://wingcast.ch",                # Marketing-Seite ist nicht die App
    "",                                   # gar nichts gesetzt
])
def test_entwicklungsumgebung_wird_erkannt(monkeypatch, url):
    monkeypatch.setattr(config, "BASE_URL", url)
    erlaubt, grund = config.ops_produktion()
    assert not erlaubt
    assert "app.wingcast.ch" in grund      # sagt, was Produktion waere


def test_force_oeffnet_den_weg_zum_testen(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://localhost:5000")
    monkeypatch.setattr(config, "OPS_ALERT_FORCE", True)
    erlaubt, grund = config.ops_produktion()
    assert erlaubt
    assert "erzwungen" in grund


def test_umzug_der_domain_ist_konfigurierbar(monkeypatch):
    """Restrisiko der Positivpruefung: zieht die App um, muss die Variable
    mit. Dass das ohne Codeaenderung geht, ist der halbe Schutz — die andere
    Haelfte ist die Protokollzeile beim Start (main.py)."""
    monkeypatch.setattr(config, "BASE_URL", "https://app.neuedomain.ch")
    assert not config.ops_produktion()[0]
    monkeypatch.setattr(config, "OPS_PRODUKTION_HOST", "app.neuedomain.ch")
    assert config.ops_produktion()[0]


def test_betreff_markiert_nur_fremde_herkunft(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "https://app.wingcast.ch")
    assert config.ops_betreff("[Wingcast] Test") == "[Wingcast] Test"

    monkeypatch.setattr(config, "BASE_URL", "http://localhost:5000")
    markiert = config.ops_betreff("[Wingcast] Test")
    assert markiert.startswith("[NICHT PRODUKTION:")
    assert "[Wingcast] Test" in markiert


# ---------------------------------------------------------------------------
# Die drei Alarmwege
# ---------------------------------------------------------------------------

def test_wache_sendet_nicht_vom_entwicklungsrechner(monkeypatch, capsys):
    from scripts import snapshot_wache as wache
    import email_service

    gesendet = []
    monkeypatch.setattr(email_service, "send_email",
                        lambda *a, **k: gesendet.append(a) or True)

    monkeypatch.setattr(config, "BASE_URL", "http://localhost:5000")
    wache._sende("[Wingcast] Archivtag kaputt", "Text")
    assert gesendet == []
    assert "kein Versand" in capsys.readouterr().out

    monkeypatch.setattr(config, "BASE_URL", "https://app.wingcast.ch")
    wache._sende("[Wingcast] Archivtag kaputt", "Text")
    assert len(gesendet) == 1


def test_frontenalarm_sendet_nicht_vom_entwicklungsrechner(monkeypatch):
    from scripts import fronten_alarm
    import email_service

    gesendet = []
    monkeypatch.setattr(email_service, "send_email",
                        lambda *a, **k: gesendet.append(a) or True)
    monkeypatch.setattr(config, "BASE_URL", "http://localhost:5000")

    fronten_alarm.Alarm(versand=True)._sende(
        "[Wingcast] Frontenkette steht", "Text")
    assert gesendet == []


def test_nachlauf_startet_nicht_vom_entwicklungsrechner(monkeypatch):
    """Der teuerste Teil: ein Vormittagsstart auf dem Laptop wuerde sonst
    Wetter neu ziehen und eine volle LLM-Analyse ausloesen."""
    import scheduler
    from scripts import snapshot_wache as wache

    def _nie(*a, **k):
        raise AssertionError("Nachlauf haette auf dem Laptop nicht laufen duerfen")

    monkeypatch.setattr(wache, "befund", _nie)
    monkeypatch.setattr(config, "BASE_URL", "http://localhost:5000")

    scheduler._nachholen_falls_noetig(object())     # darf nur protokollieren
