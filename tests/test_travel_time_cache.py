"""Tests fuer den Fahrzeit-Speicher auf Platte und den Einzelweg-Lueckenfueller.

Der Speicher liegt auf der Platte und nicht im Prozess, weil sonst das
Vorwaermen per Skript dem Chat-Server nichts brächte: Es sind zwei Prozesse.
Genau das pruefen diese Tests — inklusive der Lehre, dass eine Zeitnot
("budget") NICHT gespeichert werden darf, sonst friert ein halbes Ergebnis fuer
30 Tage ein.

Kein Test spricht mit dem Netz.
"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import config
import routing


class _Antwort:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("keine JSON-Antwort")
        return self._payload


def _matrix(minuten_je_ziel):
    return _Antwort(200, {"sources_to_targets": [[
        {"to_index": i, "from_index": 0,
         "time": None if m is None else m * 60,
         "distance": None if m is None else m}
        for i, m in enumerate(minuten_je_ziel)
    ]]})


def _route(minuten):
    return _Antwort(200, {"trip": {"summary": {"time": minuten * 60, "length": 100.0}}})


class _CacheAufPlatte(unittest.TestCase):
    """Basis: frischer Speicher in einem temporaeren Verzeichnis."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pfad = os.path.join(self.tmp.name, "travel_times_cache.json")
        self._alt = config.TRAVEL_TIME_CACHE_PATH
        config.TRAVEL_TIME_CACHE_PATH = self.pfad
        routing._MATRIX_CACHE.clear()
        routing._CACHE_DATEI_MTIME = -1.0

    def tearDown(self):
        config.TRAVEL_TIME_CACHE_PATH = self._alt
        routing._MATRIX_CACHE.clear()
        routing._CACHE_DATEI_MTIME = -1.0
        self.tmp.cleanup()


class TestLueckenfueller(_CacheAufPlatte):
    def test_einzelweg_fuellt_luecke_der_sammelabfrage(self):
        """Der Kern des Umbaus: Sammelabfrage leer -> Einzelweg liefert."""
        def antwort(url, **kw):
            return _matrix([28, None]) if "sources_to_targets" in url else _route(155)

        with patch("routing.requests.post", side_effect=antwort):
            z = routing.travel_times(47.19, 7.40, [(47.24, 7.51), (46.63, 7.51)], "auto")
        self.assertEqual(z[0]["minutes"], 28)
        self.assertEqual(z[1]["minutes"], 155)   # per Einzelweg nachgefuellt
        self.assertIsNone(z[1]["reason"])

    def test_ohne_fill_gaps_bleibt_die_luecke(self):
        with patch("routing.requests.post", return_value=_matrix([28, None])):
            z = routing.travel_times(47.19, 7.40, [(47.24, 7.51), (46.63, 7.51)],
                                     "auto", fill_gaps=False)
        self.assertEqual(z[1]["reason"], "no_route")

    def test_einzelweg_ohne_route_bleibt_ohne_zahl(self):
        def antwort(url, **kw):
            if "sources_to_targets" in url:
                return _matrix([None])
            return _Antwort(400, None, "no path")

        with patch("routing.requests.post", side_effect=antwort):
            z = routing.travel_times(47.19, 7.40, [(46.63, 7.51)], "auto")
        self.assertIsNone(z[0]["minutes"])
        self.assertEqual(z[0]["reason"], "no_route")

    def test_budget_bremst_das_nachfuellen(self):
        """Mit Budget 0 wird nichts einzeln nachgefragt — der Chat darf nicht warten."""
        def antwort(url, **kw):
            if "sources_to_targets" in url:
                return _matrix([None, None])
            raise AssertionError("Einzelweg trotz aufgebrauchtem Budget")

        with patch("routing.requests.post", side_effect=antwort):
            z = routing.travel_times(47.19, 7.40, [(46.6, 7.5), (46.7, 7.6)],
                                     "auto", budget_seconds=0.0)
        self.assertTrue(all(e["reason"] == "budget" for e in z))

    def test_budget_wird_nicht_gespeichert(self):
        """Zeitnot ist keine Aussage ueber die Strecke — sonst friert sie 30 Tage ein."""
        with patch("routing.requests.post", return_value=_matrix([None])):
            routing.travel_times(47.19, 7.40, [(46.6, 7.5)], "auto", budget_seconds=0.0)
        routing.cache_datei_schreiben()
        # Nichts zu speichern heisst: keine Datei, oder eine ohne diesen Eintrag.
        self.assertEqual(routing._MATRIX_CACHE, {}, "budget darf nicht in den Speicher")
        if os.path.exists(self.pfad):
            with open(self.pfad, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["eintraege"], {})

    def test_budget_wird_beim_naechsten_mal_neu_versucht(self):
        with patch("routing.requests.post", return_value=_matrix([None])):
            routing.travel_times(47.19, 7.40, [(46.6, 7.5)], "auto", budget_seconds=0.0)

        def antwort(url, **kw):
            return _matrix([None]) if "sources_to_targets" in url else _route(99)

        with patch("routing.requests.post", side_effect=antwort):
            z = routing.travel_times(47.19, 7.40, [(46.6, 7.5)], "auto")
        self.assertEqual(z[0]["minutes"], 99)


class TestSpeicherUeberProzessgrenze(_CacheAufPlatte):
    def test_geschriebenes_wird_von_der_platte_gelesen(self):
        """Das ist der Sinn der Datei: Vorwaermskript schreibt, Chat liest."""
        with patch("routing.requests.post", return_value=_matrix([28])):
            routing.travel_times(47.19, 7.40, [(47.24, 7.51)], "auto")
        self.assertGreater(routing.cache_datei_schreiben(), 0)

        # Prozesswechsel simulieren: Speicher im RAM weg, Datei bleibt.
        routing._MATRIX_CACHE.clear()
        routing._CACHE_DATEI_MTIME = -1.0

        with patch("routing.requests.post") as post:
            z = routing.travel_times(47.19, 7.40, [(47.24, 7.51)], "auto")
            post.assert_not_called()
        self.assertEqual(z[0]["minutes"], 28)

    def test_abgelaufene_eintraege_werden_verworfen(self):
        alt = {"eintraege": {
            routing._matrix_cache_key(47.19, 7.40, 47.24, 7.51, "auto"): {
                "ts": 0.0, "minutes": 28, "reason": None}
        }}
        with open(self.pfad, "w", encoding="utf-8") as f:
            json.dump(alt, f)
        routing._cache_datei_laden(force=True)
        self.assertEqual(routing._MATRIX_CACHE, {})

    def test_kaputte_datei_bringt_nichts_zum_absturz(self):
        with open(self.pfad, "w", encoding="utf-8") as f:
            f.write("{das ist kein json")
        routing._cache_datei_laden(force=True)  # nur eine Warnung im Log
        with patch("routing.requests.post", return_value=_matrix([28])):
            z = routing.travel_times(47.19, 7.40, [(47.24, 7.51)], "auto")
        self.assertEqual(z[0]["minutes"], 28)

    def test_schreiben_mergt_fremde_eintraege(self):
        """Server und Vorwaermskript schreiben beide — keiner darf den anderen loeschen."""
        fremd_key = routing._matrix_cache_key(46.95, 7.45, 46.80, 7.80, "auto")
        import time as _t
        with open(self.pfad, "w", encoding="utf-8") as f:
            json.dump({"eintraege": {fremd_key: {"ts": _t.time(), "minutes": 42,
                                                 "reason": None}}}, f)
        with patch("routing.requests.post", return_value=_matrix([28])):
            routing.travel_times(47.19, 7.40, [(47.24, 7.51)], "auto")
        routing.cache_datei_schreiben()
        with open(self.pfad, encoding="utf-8") as f:
            eintraege = json.load(f)["eintraege"]
        self.assertIn(fremd_key, eintraege, "fremder Eintrag wurde ueberschrieben")
        self.assertEqual(len(eintraege), 2)


if __name__ == "__main__":
    unittest.main()
