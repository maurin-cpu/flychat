"""Tests: Der Pilot MUSS erfahren, wenn die Reichweiten-Suche nicht liefert.

Der Befund vom 25.09.2026 war nicht die Grenze des Kartendienstes, sondern das
Schweigen darueber: Die App bot "try again" an, wo ein zweiter Versuch nie
helfen konnte, und der Pilot ist nicht wiedergekommen
(validation/chat/BEFUNDE.md §7).

Deshalb haengt die Rueckmeldung NICHT am Antworttext des Sprachmodells, sondern
kommt als eigenes Ereignis (`showNotice`) aus dem Backend. Eine Prompt-Regel
wird verletzt, sobald sie unbequem ist — ein Ereignis nicht. Genau das pruefen
diese Tests.

Kein Test spricht mit dem Netz.
"""
import unittest
from unittest.mock import patch

import config
import routing
from engine.chat_orchestrator import ChatOrchestratorMixin


class _Engine(ChatOrchestratorMixin):
    """Nur die Felder, die der Handler anfasst."""

    def __init__(self, spots):
        self.spots = spots
        self.spot_analyses = {}
        self.region_analyses = {}


def _spots(n=3):
    # Dicht beim Startpunkt, damit der Luftlinien-Vorfilter sie alle behaelt.
    return [
        {"name": f"Spot {i}", "fluggebiet": "", "region": "",
         "elevation_m": 1200, "windrichtung": "N",
         "latitude": 47.20 + i * 0.01, "longitude": 7.40 + i * 0.01}
        for i in range(n)
    ]


def _hinweise(ergebnis):
    return [a["payload"]["text"] for a in ergebnis["map_actions"]
            if a.get("action") == "showNotice"]


class TestRueckmeldung(unittest.TestCase):
    def setUp(self):
        routing._MATRIX_CACHE.clear()
        routing._CACHE_DATEI_MTIME = -1.0
        self.engine = _Engine(_spots())
        self.args = {"lat": 47.19, "lon": 7.40, "minutes": 60, "mode": "auto"}

    def _rufen(self, **extra):
        return self.engine._dispatch_tool(
            "find_spots_within_travel_time", {**self.args, **extra}
        )

    def test_dienst_ausgefallen_erzeugt_hinweis_an_den_piloten(self):
        with patch("routing.requests.post",
                   side_effect=routing.requests.exceptions.ConnectTimeout("weg")):
            r = self._rufen()
        hinweise = _hinweise(r)
        self.assertEqual(len(hinweise), 1)
        self.assertTrue(hinweise[0].strip(), "Hinweis darf nicht leer sein")
        # Und die Anweisung ans Modell steht zusaetzlich drin, nicht stattdessen.
        self.assertIn("error", r["content"])

    def test_ausfall_bietet_dem_piloten_keinen_zweiten_versuch_an(self):
        """Der Kernfehler vom 25.09.: ein Retry, der nie helfen kann."""
        with patch("routing.requests.post",
                   side_effect=routing.requests.exceptions.ConnectTimeout("weg")):
            r = self._rufen()
        text = " ".join(_hinweise(r)).lower()
        for lockwort in ("versuch es nochmal", "try again", "in ein paar minuten",
                         "in a few minutes"):
            self.assertNotIn(lockwort, text)

    def test_feste_grenze_sagt_dass_nachfragen_nichts_aendert(self):
        with patch("routing.requests.post",
                   return_value=_Antwort400()):
            r = self._rufen()
        text = " ".join(_hinweise(r)).lower()
        self.assertTrue(text, "feste Grenze ohne Rueckmeldung")
        self.assertTrue(
            "feste grenze" in text or "hard limit" in text,
            f"Grenze nicht als endgueltig benannt: {text}",
        )

    def test_teilergebnis_sagt_dass_nachfragen_hilft(self):
        """Gegenprobe zur festen Grenze: HIER ist Nachfragen die richtige Auskunft.

        Die beiden Faelle duerfen sich im Wortlaut nicht gleichen — sonst
        entsteht wieder das falsche Versprechen vom 25.09. (oder umgekehrt ein
        unnoetiges Aufgeben).
        """
        alt = config.TRAVEL_TIME_CHAT_BUDGET_S
        config.TRAVEL_TIME_CHAT_BUDGET_S = 0.0
        try:
            with patch("routing.requests.post", return_value=_matrix([12, None, None])):
                teil = " ".join(_hinweise(self._rufen())).lower()
        finally:
            config.TRAVEL_TIME_CHAT_BUDGET_S = alt

        routing._MATRIX_CACHE.clear()
        with patch("routing.requests.post", return_value=_Antwort400()):
            grenze = " ".join(_hinweise(self._rufen())).lower()

        self.assertTrue(teil and grenze)
        self.assertNotEqual(teil, grenze)
        # Teilergebnis lädt zum Nachfragen ein …
        self.assertTrue("nochmal" in teil or "again" in teil, teil)
        # … die feste Grenze ausdrücklich nicht.
        self.assertTrue("ändert daran nichts" in grenze or "will not change" in grenze,
                        grenze)

    def test_vollstaendiges_ergebnis_erzeugt_keinen_hinweis(self):
        """Kein Laerm, wenn alles geklappt hat."""
        with patch("routing.requests.post", return_value=_matrix([12, 20, 35])):
            r = self._rufen()
        self.assertEqual(_hinweise(r), [])
        self.assertEqual(r["content"]["count"], 3)
        self.assertEqual([s["travel_minutes"] for s in r["content"]["spots"]],
                         [12, 20, 35])

    def test_budget_null_erzeugt_hinweis_auf_unvollstaendigkeit(self):
        alt = config.TRAVEL_TIME_CHAT_BUDGET_S
        config.TRAVEL_TIME_CHAT_BUDGET_S = 0.0
        try:
            with patch("routing.requests.post", return_value=_matrix([12, None, None])):
                r = self._rufen()
        finally:
            config.TRAVEL_TIME_CHAT_BUDGET_S = alt
        hinweise = _hinweise(r)
        self.assertEqual(len(hinweise), 1, f"erwartet 1 Hinweis, war {hinweise}")
        self.assertEqual(r["content"]["count"], 1)


class _Antwort:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("keine JSON-Antwort")
        return self._payload


def _Antwort400():
    return _Antwort(400, None, "Path distance exceeds the max distance limit: 150000 meters")


def _matrix(minuten_je_ziel):
    return _Antwort(200, {"sources_to_targets": [[
        {"to_index": i, "from_index": 0,
         "time": None if m is None else m * 60,
         "distance": None if m is None else m}
        for i, m in enumerate(minuten_je_ziel)
    ]]})


if __name__ == "__main__":
    unittest.main()
