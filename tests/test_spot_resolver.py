"""Tests: Der Chat findet den Startplatz, den der Pilot meint, oder sagt, dass er fehlt.

Jeder Fall unten ist eine echte Eingabe aus validation/chat/ (Juli bis Oktober
2026). Der schwerste Befund: Nach "Charmey" antwortete der Chat zweimal zu
Gastlosen, obwohl der Startplatz von Charmey als Vounetz-1620 in den Daten
steht (BEFUNDE.md, Nachtrag 26.10.). Ein fremder Startplatz, der wie der
gefragte klingt, ist gefaehrlicher als ein ehrliches "kenne ich nicht".

Gegen die echte Spot-Liste, damit ein Umbenennen in der CSV hier auffaellt.
Kein Test spricht mit dem Netz.
"""
import unittest
from unittest.mock import patch

import i18n
from engine.chat_orchestrator import ChatOrchestratorMixin
from engine.spot_resolver import SpotResolver, norm
from spots import load_spots

SPOTS = load_spots()


class _Engine(ChatOrchestratorMixin):
    """Nur die Felder, die der Handler anfasst."""

    def __init__(self, spots):
        self.spots = spots
        self.spot_analyses = {s["name"]: {"2026-10-27": {"rating": 3}} for s in spots}
        self.region_analyses = {}


class TestEchteEingaben(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = SpotResolver(SPOTS)

    def treffer(self, anfrage):
        e = self.r.aufloesen(anfrage)
        self.assertIsNotNone(e.spot, f"'{anfrage}' nicht eindeutig gefunden: {e}")
        return e.spot["name"]

    def kandidaten(self, anfrage):
        e = self.r.aufloesen(anfrage)
        self.assertIsNone(e.spot, f"'{anfrage}' haette mehrdeutig sein sollen, ergab {e.spot}")
        return {s["name"] for s in e.kandidaten}

    def test_charmey_ist_vounetz_nicht_gastlosen(self):
        self.assertEqual(self.treffer("Charmey"), "Vounetz-1620")

    def test_le_cernil_ist_corgemont(self):
        self.assertEqual(self.treffer("Le Cernil"), "Corgemont")
        self.assertEqual(self.treffer("Cernil"), "Corgemont")

    def test_ortsname_plus_gebiet_findet_den_startplatz(self):
        # anon 10.08.: "Mijoux Col de la Faucille" — frueher nicht gefunden,
        # weil die ganze Anfrage im Namen stecken musste.
        self.assertEqual(self.treffer("Mijoux Col de la Faucille"), "Mijoux")

    def test_bruchstueck_des_namens(self):
        self.assertEqual(self.treffer("Möntschele"), "Möntschelealp")

    def test_klammerteil(self):
        self.assertEqual(self.treffer("Montoz Nord"), "Werdtberg-1240 (Montoz nord)")
        self.assertEqual(self.treffer("Uetliberg"), "Baldern (Uetliberg)")

    def test_umlaut_und_digraph_sind_gleich(self):
        self.assertEqual(self.treffer("Bueelen"), self.treffer("Büelen"))
        self.assertEqual(self.treffer("Brandlen"), "Brändlen-1240")

    def test_saint_und_st(self):
        self.assertEqual(self.treffer("St. Cergue"), "Saint-Cergue")

    def test_tippfehler(self):
        self.assertEqual(self.treffer("Gastlossen"), "Gastlosen")

    def test_hoehenzahl_darf_fehlen(self):
        self.assertEqual(self.treffer("Hohmattli"), "Hohmattli-1770")

    def test_mehrdeutig_wird_nicht_still_entschieden(self):
        # Frueher gewann der erste Teilstring-Treffer.
        self.assertEqual(self.kandidaten("Montoz"),
                         {"Werdtberg-1240 (Montoz nord)", "Werdtberg-1270 (Montoz sud)"})
        self.assertEqual(self.kandidaten("Grenchen"), {"Grenchenberg Nord", "Buetzen"})
        self.assertGreaterEqual(len(self.kandidaten("Rigi")), 3)

    def test_unbekannter_ort_liefert_nichts(self):
        for ort in ("La Berra", "Grimmialp", "Balmberg", "Kaiseregg", "Grand Bornand", "Givrins"):
            e = self.r.aufloesen(ort)
            self.assertIsNone(e.spot, f"'{ort}' ist nicht in den Daten, ergab aber {e.spot}")
            self.assertEqual(e.kandidaten, [], f"'{ort}' ergab Kandidaten {e.kandidaten}")

    def test_gastlosen_traegt_nicht_mehr_den_ort_von_charmey(self):
        gastlosen = next(s for s in SPOTS if s["name"] == "Gastlosen")
        self.assertNotEqual(norm(gastlosen["fluggebiet"]), norm("Vounetse"))

    def test_jeder_alias_zeigt_auf_einen_vorhandenen_startplatz(self):
        from engine.spot_resolver import lade_aliasse
        namen = {s["name"] for s in SPOTS}
        for alias, site in lade_aliasse():
            self.assertIn(site, namen, f"Alias '{alias}' zeigt auf unbekannten Startplatz '{site}'")


class TestToolAntwort(unittest.TestCase):
    def setUp(self):
        self.engine = _Engine(SPOTS)

    def rufen(self, spot_name):
        return self.engine._dispatch_tool(
            "get_spot_analysis", {"spot_name": spot_name, "date": "2026-10-27"}
        )["content"]

    def test_alias_wird_dem_modell_genannt(self):
        c = self.rufen("Charmey")
        self.assertEqual(c["spot"], "Vounetz-1620")
        self.assertIn("Charmey", c["resolved_from"])
        self.assertIn("derselbe Startplatz", c["resolved_from"])

    def test_schwacher_treffer_wird_als_moeglicher_anderer_ort_markiert(self):
        c = self.rufen("Interlaken")
        self.assertIn("anderer Ort", c["resolved_from"])

    def test_exakter_name_ohne_vermerk(self):
        self.assertNotIn("resolved_from", self.rufen("Chasseral"))

    def test_mehrdeutig_liefert_kandidaten(self):
        c = self.rufen("Montoz")
        self.assertEqual({k["name"] for k in c["candidates"]},
                         {"Werdtberg-1240 (Montoz nord)", "Werdtberg-1270 (Montoz sud)"})

    def test_unbekannt_liefert_naechste_startplaetze_mit_distanz(self):
        # Kaiseregg (2185 m, FR) ist kein Startplatz in den Daten; Hohmattli liegt nebenan.
        with patch("routing.geocode",
                   return_value={"lat": 46.645, "lon": 7.335, "display_name": "Kaiseregg"}):
            c = self.rufen("Kaiseregg")
        self.assertTrue(c["not_in_data"])
        namen = [s["name"] for s in c["nearest_spots"]]
        self.assertIn("Hohmattli-1770", namen)
        abstaende = [s["distance_km"] for s in c["nearest_spots"]]
        self.assertEqual(abstaende, sorted(abstaende))
        self.assertIn("nie einen anderen Startplatz", c["instruction"])

    def test_unbekannt_und_ort_nicht_gefunden(self):
        with patch("routing.geocode", return_value=None):
            c = self.rufen("Xyzberg")
        self.assertTrue(c["not_in_data"])
        self.assertNotIn("nearest_spots", c)
        self.assertIn("Rate keine", c["instruction"])

    def test_geocoding_ausfall_bricht_nicht(self):
        import routing
        with patch("routing.geocode", side_effect=routing.RoutingError("down")):
            c = self.rufen("Xyzberg")
        self.assertTrue(c["not_in_data"])


class TestChatSprache(unittest.TestCase):
    def test_chat_antwortet_in_der_sprache_des_piloten(self):
        with i18n.lang_override("en"):
            text = i18n.chat_lang_instruction()
        self.assertIn("language the pilot writes in", text)
        self.assertNotIn("entire response to the user in natural, fluent English", text)

    def test_voranalyse_bleibt_bei_der_oberflaechensprache(self):
        with i18n.lang_override("en"):
            self.assertIn("in natural, fluent English", i18n.llm_lang_instruction())


if __name__ == "__main__":
    unittest.main()
