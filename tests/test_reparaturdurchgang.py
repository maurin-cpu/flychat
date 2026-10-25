# -*- coding: utf-8 -*-
"""Reparaturdurchgang im Analyse-Lauf (Vorgabe 16.08.2026, Ausfall 20.10.2026).

Am 20.10.2026 meldete DeepInfra beim Start des Morgenlaufs gut eine Minute
"Model busy". Die Wiederholungen je Call lagen alle in dieser Minute, 40 von
93 Regions-Bewertungen blieben "error" und standen den ganzen Tag grau in der
App. Der Durchgang rechnet solche Eintraege nach — entschieden am Ergebnis,
nicht an der Fehlerursache.
"""
import threading

import pytest

from engine.analyzers import AnalyzersMixin


class _Engine(AnalyzersMixin):
    _REPARATUR_PAUSEN_S = (0, 0, 0)


def _lauf(engine, results, jobs):
    gen = engine._reparaturdurchgang("Test", results, jobs)
    while True:
        try:
            next(gen)
        except StopIteration as stop:
            return stop.value


def _ok(name, d):
    return {"region": name, "date": d, "safety_status": "conditional"}


def _fehler(name, d):
    return {"region": name, "date": d, "safety_status": "error",
            "error": "Error code: 429 - Model busy, retry later"}


def test_gescheiterte_werden_nachgeholt_andere_nicht_angefasst():
    aufrufe = []

    def job(name, d):
        def f():
            aufrufe.append((name, d))
            return _ok(name, d)
        return f

    results = {"a": {"d1": _ok("a", "d1"), "d2": _fehler("a", "d2")},
               "b": {"d1": _fehler("b", "d1"), "d2": _ok("b", "d2")}}
    jobs = {(k, d): job(k, d) for k in "ab" for d in ("d1", "d2")}

    assert _lauf(_Engine(), results, jobs) == 0
    assert sorted(aufrufe) == [("a", "d2"), ("b", "d1")]
    assert results["a"]["d2"]["safety_status"] == "conditional"
    assert results["b"]["d1"]["safety_status"] == "conditional"


def test_anbieter_erholt_sich_erst_in_der_zweiten_runde():
    versuche = {"n": 0}

    def f():
        versuche["n"] += 1
        return _fehler("a", "d1") if versuche["n"] == 1 else _ok("a", "d1")

    results = {"a": {"d1": _fehler("a", "d1")}}
    assert _lauf(_Engine(), results, {("a", "d1"): f}) == 0
    assert versuche["n"] == 2
    assert results["a"]["d1"]["safety_status"] == "conditional"


def test_bleibt_es_kaputt_endet_es_nach_drei_runden():
    versuche = {"n": 0}

    def f():
        versuche["n"] += 1
        return _fehler("a", "d1")

    results = {"a": {"d1": _fehler("a", "d1")}}
    assert _lauf(_Engine(), results, {("a", "d1"): f}) == 1
    assert versuche["n"] == 3


def test_fehlender_eintrag_wird_auch_nachgeholt():
    """Ein Future, das gar kein Ergebnis hinterliess, ist auch eine Luecke."""
    results = {}
    assert _lauf(_Engine(), results, {("a", "d1"): lambda: _ok("a", "d1")}) == 0
    assert results["a"]["d1"]["safety_status"] == "conditional"


def test_gescheiterte_flyability_wird_nachgeholt():
    """Safety ok, Flyability-Call gescheitert: Status steht, Tier fehlt."""
    halb = {"region": "a", "date": "d1", "safety_status": "safe",
            "phase": "flyability", "error": "timeout"}
    results = {"a": {"d1": halb}}
    assert _lauf(_Engine(), results, {("a", "d1"): lambda: _ok("a", "d1")}) == 0
    assert "error" not in results["a"]["d1"]


def test_no_data_ist_kein_fehler():
    """Fehlende Wetterdaten aendert ein zweiter Versuch nicht."""
    aufrufe = []
    results = {"a": {"d1": {"safety_status": "no_data"}}}
    _lauf(_Engine(), results, {("a", "d1"): lambda: aufrufe.append(1)})
    assert aufrufe == []


def test_permanenter_fehler_wartet_nicht():
    """Guthaben leer: jeder Call bricht sofort ab, Nachrechnen sinnlos."""
    eng = _Engine()
    eng._api_abort = threading.Event()
    eng._api_abort.set()
    aufrufe = []
    results = {"a": {"d1": _fehler("a", "d1")}}
    assert _lauf(eng, results, {("a", "d1"): lambda: aufrufe.append(1)}) == 1
    assert aufrufe == []


def test_pausen_liefern_heartbeats(monkeypatch):
    """Die SSE-Verbindung des Admin-Laufs darf in der Pause nicht abreissen."""
    import engine.analyzers as mod
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    eng = _Engine()
    eng._REPARATUR_PAUSEN_S = (30,)
    uhr = iter([0, 0, 15, 30, 30, 30])
    monkeypatch.setattr(mod.time, "monotonic", lambda: next(uhr, 30))
    results = {"a": {"d1": _fehler("a", "d1")}}
    events = list(eng._reparaturdurchgang("Test", results,
                                          {("a", "d1"): lambda: _ok("a", "d1")}))
    assert events and all(e["event"] == "heartbeat" for e in events)
    assert results["a"]["d1"]["safety_status"] == "conditional"
