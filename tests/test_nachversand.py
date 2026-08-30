"""Nachversand ausgefallener Briefing-Mails (scheduler).

Hintergrund: Am 29.08.2026 hat das automatische Ubuntu-Update um 06:03 den
laufenden Morgenlauf abgeschnitten. Der Waechter holte die Datenkette bis
06:47 nach, verschickte aber bewusst keine Mails — mit der Begruendung, ein
Doppelversand sei nicht auszuschliessen und eine "Morgenmail am Mittag"
schlechter als keine. Beides traegt nicht: der Versandstand steht je Abo in
der Datenbank, und 06:47 ist keine Mittagsmail.

Diese Tests halten die zwei Zusagen fest, an denen der Nachversand haengt:
kein Abo bekommt eine zweite Mail, und nach der Zeitgrenze geht keine mehr.
"""
import pytest

import scheduler


class _Mgr:
    """Abo-Verwaltung, so weit _send_briefings_once sie braucht."""

    def __init__(self, aktive, heute_versendet):
        self._aktive = aktive
        self._heute = heute_versendet
        self.mark_sent_ids = []

    def list_active(self):
        return list(self._aktive)

    def ids_sent_today(self):
        return self._heute

    def mark_sent(self, sub_id):
        self.mark_sent_ids.append(sub_id)


def _abo(sub_id):
    return {"id": sub_id, "email": f"a{sub_id}@example.com", "regions": ["Jura"],
            "active_weekdays": [0, 1, 2, 3, 4, 5, 6]}


@pytest.fixture
def versand_stub(monkeypatch):
    """Haelt alles ab, was echte Arbeit machen wuerde (LLM, Netz, Mailversand),
    und protokolliert, an wen versendet wurde."""
    import subscriber
    import email_service
    from engine import synoptic_grid, synoptic_llm

    versendet = []

    monkeypatch.setattr(email_service, "send_briefing_email",
                        lambda sub, data, async_send=False:
                            versendet.append(sub["email"]) or True)
    monkeypatch.setattr(email_service, "briefing_coverage",
                        lambda sub, data: {"state": "voll", "cells": 9,
                                           "cells_rated": 9, "regions": 3,
                                           "days": 3, "missing_regions": []})
    monkeypatch.setattr(synoptic_grid, "refresh_synoptic_grid", lambda: None)
    monkeypatch.setattr(synoptic_llm, "refresh_synoptic_overview",
                        lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "_melde_datenluecke",
                        lambda *a, **k: None)

    def _setze(mgr):
        monkeypatch.setattr(subscriber, "get_manager_from_env", lambda: mgr)
        return versendet

    return _setze


class _Engine:
    synoptic_client = None
    synoptic_model = None

    def build_briefing_data(self):
        return {"days": [{}, {}, {}]}


def test_nachversand_ueberspringt_abos_mit_heutiger_mail(versand_stub):
    """Der Lauf ist mitten im Versand abgebrochen: die ersten zwei Abos haben
    ihre Mail, der Rest nicht. Nur der Rest darf sie noch bekommen."""
    mgr = _Mgr([_abo(1), _abo(2), _abo(3), _abo(4)], heute_versendet={1, 2})
    versendet = versand_stub(mgr)

    stats = scheduler._send_briefings_once(_Engine(), nur_ohne_mail_heute=True)

    assert versendet == ["a3@example.com", "a4@example.com"]
    assert stats["sent"] == 2
    assert mgr.mark_sent_ids == [3, 4]


def test_nachversand_faellt_aus_wenn_versandstand_unbekannt(versand_stub):
    """Ohne verlaesslichen Stand lieber keine Mail als eine doppelte."""
    mgr = _Mgr([_abo(1), _abo(2)], heute_versendet=None)
    versendet = versand_stub(mgr)

    stats = scheduler._send_briefings_once(_Engine(), nur_ohne_mail_heute=True)

    assert versendet == []
    assert stats["sent"] == 0
    assert "nicht feststellbar" in stats["grund"]


def test_regulaerer_lauf_filtert_nicht(versand_stub):
    """Der 06:00-Lauf bedient alle Abos — der Filter gilt nur fuer Reparaturen."""
    mgr = _Mgr([_abo(1), _abo(2)], heute_versendet={1})
    versendet = versand_stub(mgr)

    scheduler._send_briefings_once(_Engine())

    assert versendet == ["a1@example.com", "a2@example.com"]


def test_kein_nachversand_nach_der_zeitgrenze(monkeypatch):
    """Nach der Grenze ist die Morgenmail keine Planungshilfe mehr."""
    monkeypatch.setattr(scheduler, "NACHSENDE_GRENZE_STUNDE", 0)
    gerufen = []
    monkeypatch.setattr(scheduler, "_send_briefings_once",
                        lambda *a, **k: gerufen.append(1))

    ergebnis = scheduler._nachversand_falls_rechtzeitig(_Engine(), {"maengel": []})

    assert gerufen == []
    assert ergebnis["sent"] == 0
    assert "09:00" in ergebnis["grund"] or "Grenze" in ergebnis["grund"]


def test_kein_nachversand_auf_halber_datenlage(monkeypatch):
    """Eine Mail ohne belastbare Analyse liest sich wie 'nichts fliegbar' —
    dann lieber melden statt senden."""
    monkeypatch.setattr(scheduler, "NACHSENDE_GRENZE_STUNDE", 24)
    gerufen = []
    monkeypatch.setattr(scheduler, "_send_briefings_once",
                        lambda *a, **k: gerufen.append(1))

    ergebnis = scheduler._nachversand_falls_rechtzeitig(
        _Engine(), {"maengel": ["keine_regionen"]})

    assert gerufen == []
    assert "keine_regionen" in ergebnis["grund"]


def test_nachversand_laeuft_wenn_daten_stehen_und_zeit_reicht(monkeypatch):
    monkeypatch.setattr(scheduler, "NACHSENDE_GRENZE_STUNDE", 24)
    monkeypatch.setattr(scheduler, "_send_briefings_once",
                        lambda engine, nur_ohne_mail_heute=False:
                            {"sent": 5, "skipped": 0, "failed": 0,
                             "nur": nur_ohne_mail_heute})

    ergebnis = scheduler._nachversand_falls_rechtzeitig(_Engine(), {"maengel": []})

    assert ergebnis["sent"] == 5
    assert ergebnis["nur"] is True          # niemals ungefiltert nachversenden
    assert "zeit" in ergebnis               # fuer die Waechter-Meldung
