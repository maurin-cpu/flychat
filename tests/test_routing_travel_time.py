"""Tests fuer routing.travel_times + die Grenzen des Kartendienstes.

Hintergrund: Am 25.09.2026 fragte ein Pilot nach Gebieten "maximal 1h30 ab
Grenchen". Der Dienst deckelt Isochronen bei 60 Minuten, die App meldete das als
"Dienst gerade nicht erreichbar, bitte in ein paar Minuten erneut versuchen", und
der Pilot versuchte es dreimal vergeblich (validation/chat/BEFUNDE.md §7).

Diese Tests halten die Lehre daraus fest: Eine FESTE Grenze darf nie als
vorübergehender Ausfall auftreten, und eine Fahrzeit darf nie geraten werden.
Kein Test spricht mit dem Netz — der Dienst wird gemockt.
"""
import unittest
from unittest.mock import patch

import config
import routing


class _Antwort:
    """Minimal-Attrappe einer requests-Response."""

    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("keine JSON-Antwort")
        return self._payload


def _matrix_antwort(minuten_je_ziel):
    """Valhalla-Matrixantwort: Sekunden je Ziel, None = keine Route."""
    return _Antwort(200, {"sources_to_targets": [[
        {"to_index": i, "from_index": 0,
         "time": None if m is None else m * 60,
         "distance": None if m is None else m}
        for i, m in enumerate(minuten_je_ziel)
    ]]})


class TestIsochroneGrenze(unittest.TestCase):
    """Die 60-Minuten-Grenze muss als Grenze erkennbar sein, nicht als Ausfall."""

    def test_ueber_grenze_wirft_limit_fehler_ohne_netz(self):
        with patch("routing.requests.post") as post:
            with self.assertRaises(routing.RoutingLimitError):
                routing.isochrone(47.19, 7.40, 90, "auto")
            post.assert_not_called()  # gar nicht erst fragen

    def test_limit_fehler_ist_kein_gewoehnlicher_ausfall(self):
        # Beide erben von RoutingError, aber der Aufrufer muss sie
        # unterscheiden koennen — sonst entsteht wieder die Retry-Schleife.
        self.assertTrue(issubclass(routing.RoutingLimitError, routing.RoutingError))
        self.assertFalse(issubclass(routing.RoutingError, routing.RoutingLimitError))

    def test_genau_auf_der_grenze_wird_gefragt(self):
        grenze = config.VALHALLA_MAX_ISOCHRONE_MINUTES
        with patch("routing.requests.post") as post:
            post.return_value = _Antwort(200, {
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "properties": {},
                              "geometry": {"type": "Polygon",
                                           "coordinates": [[[7, 47], [8, 47], [8, 48], [7, 47]]]}}],
            })
            routing.isochrone(47.19, 7.40, grenze, "auto")
            post.assert_called_once()


class TestTravelTimes(unittest.TestCase):
    def setUp(self):
        routing._MATRIX_CACHE.clear()

    def test_fahrzeiten_kommen_pro_ziel_zurueck(self):
        ziele = [(47.24, 7.51), (47.13, 7.03)]
        with patch("routing.requests.post", return_value=_matrix_antwort([28, 47])):
            z = routing.travel_times(47.19, 7.40, ziele, "auto")
        self.assertEqual([e["minutes"] for e in z], [28, 47])
        self.assertEqual([e["reason"] for e in z], [None, None])

    def test_ohne_route_wird_benannt_nicht_geschaetzt(self):
        """Der haeufigste Fall: Startplatz liegt am Berg, nicht an der Strasse."""
        ziele = [(47.24, 7.51), (46.63, 7.51)]
        with patch("routing.requests.post", return_value=_matrix_antwort([28, None])):
            z = routing.travel_times(47.19, 7.40, ziele, "auto")
        self.assertEqual(z[0]["minutes"], 28)
        self.assertIsNone(z[1]["minutes"])
        self.assertEqual(z[1]["reason"], "no_route")

    def test_streckengrenze_wird_als_limit_gemeldet(self):
        """HTTP 400 des Dienstes -> reason 'limit', kein geratener Wert."""
        with patch("routing.requests.post",
                   return_value=_Antwort(400, None, "Path distance exceeds the max distance limit")):
            z = routing.travel_times(47.19, 7.40, [(46.0, 9.5)], "auto")
        self.assertIsNone(z[0]["minutes"])
        self.assertEqual(z[0]["reason"], "limit")

    def test_abbruch_nach_der_grenze_statt_jedes_ziel_einzeln(self):
        """Ziele hinter der Grenze werden markiert, nicht einzeln angefragt.

        Vorher lief jedes ferne Ziel in einen eigenen 400er — eine Anfrage
        brauchte dadurch 152 Sekunden.
        """
        nah = [(47.19 + i * 0.001, 7.40) for i in range(3)]
        fern = [(46.0 + i * 0.01, 9.5 + i * 0.01) for i in range(40)]
        with patch("routing.requests.post",
                   return_value=_Antwort(400, None, "max distance limit")) as post:
            z = routing.travel_times(47.19, 7.40, nah + fern, "auto")
        self.assertTrue(all(e["reason"] == "limit" for e in z))
        # Binaersuche im ersten Block, danach Schluss: klar unter der Zielzahl.
        self.assertLess(post.call_count, 15)

    def test_cache_verhindert_zweite_anfrage(self):
        ziele = [(47.24, 7.51)]
        with patch("routing.requests.post", return_value=_matrix_antwort([28])) as post:
            routing.travel_times(47.19, 7.40, ziele, "auto")
            routing.travel_times(47.19, 7.40, ziele, "auto")
            self.assertEqual(post.call_count, 1)

    def test_cache_trennt_verkehrsmittel(self):
        ziele = [(47.24, 7.51)]
        with patch("routing.requests.post", return_value=_matrix_antwort([28])) as post:
            routing.travel_times(47.19, 7.40, ziele, "auto")
            routing.travel_times(47.19, 7.40, ziele, "bicycle")
            self.assertEqual(post.call_count, 2)

    def test_dienst_nicht_erreichbar_bleibt_ein_fehler(self):
        """Ein echter Ausfall (500) darf NICHT als 'limit' verharmlost werden."""
        with patch("routing.requests.post", return_value=_Antwort(503, None, "upstream down")):
            with self.assertRaises(routing.RoutingError) as ctx:
                routing.travel_times(47.19, 7.40, [(47.24, 7.51)], "auto")
            self.assertNotIsInstance(ctx.exception, routing.RoutingLimitError)

    def test_unbekannter_modus(self):
        with self.assertRaises(ValueError):
            routing.travel_times(47.19, 7.40, [(47.2, 7.5)], "helikopter")

    def test_leere_zielliste(self):
        self.assertEqual(routing.travel_times(47.19, 7.40, [], "auto"), [])


class TestVorfilter(unittest.TestCase):
    """Der Luftlinien-Vorfilter darf keinen echten Treffer verlieren."""

    def test_grenze_waechst_mit_der_zeit(self):
        self.assertLess(routing.max_straight_line_km(30),
                        routing.max_straight_line_km(90))

    def test_grenze_ist_grosszuegiger_als_jede_echte_fahrt(self):
        # 90 Minuten: die Luftlinie kann nie mehr als 90/60 * 120 km sein,
        # weil die Fahrstrecke immer laenger ist als die Luftlinie.
        self.assertGreaterEqual(routing.max_straight_line_km(90), 150)

    def test_haversine_bekannte_distanz(self):
        # Grenchen -> Weissenstein, rund 6 km Luftlinie.
        km = routing.haversine_km(47.1923, 7.3958, 47.2431, 7.5103)
        self.assertGreater(km, 4)
        self.assertLess(km, 12)


if __name__ == "__main__":
    unittest.main()
