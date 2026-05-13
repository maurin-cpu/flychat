"""Tests fuer thermik_calculator.min_band_depth().

Physik-Heuristik: 3 Kurbeln × 7 s × (0.75 × peak − 1.0) ≤ 0.5 × band − 100,
mit Safety-Faktor 1.4 und Terrain-Multiplikator. Siehe
meteo_research/band_depth_calibration.md.
"""
import math
import unittest

from thermik_calculator import min_band_depth, _NET_CLIMB_THRESHOLD


class TestMinBandDepth(unittest.TestCase):

    def test_below_net_climb_threshold_returns_inf(self):
        # avg_climb = 0.75 × peak muss > sink_PG (1.0 m/s) sein → peak > 1.33
        for peak in (0.0, 0.5, 1.0, 1.2, 1.32):
            for zone in ("mittelland", "jura", "voralpen", "alpen", "hochalpin"):
                self.assertTrue(
                    math.isinf(min_band_depth(peak, zone)),
                    f"peak={peak} zone={zone} sollte inf liefern",
                )

    def test_at_threshold_returns_inf(self):
        # Genau am Threshold (1.0/0.75): noch nicht produktiv
        self.assertTrue(math.isinf(min_band_depth(_NET_CLIMB_THRESHOLD - 0.01, "mittelland")))

    def test_above_threshold_finite(self):
        # Klar oberhalb: finiter Wert
        result = min_band_depth(2.0, "mittelland")
        self.assertTrue(math.isfinite(result))
        self.assertGreater(result, 0)

    def test_terrain_monotonicity(self):
        # Bei gleichem Peak: mittelland > jura > voralpen > alpen > hochalpin
        peak = 2.5
        m = min_band_depth(peak, "mittelland")
        j = min_band_depth(peak, "jura")
        v = min_band_depth(peak, "voralpen")
        a = min_band_depth(peak, "alpen")
        h = min_band_depth(peak, "hochalpin")
        self.assertGreater(m, j)
        self.assertGreater(j, v)
        self.assertGreater(v, a)
        self.assertGreater(a, h)

    def test_climb_monotonicity(self):
        # Bei gleicher Zone: staerkerer Peak → groessere geforderte Banddicke
        zone = "voralpen"
        prev = min_band_depth(1.5, zone)
        for peak in (2.0, 2.5, 3.0, 4.0):
            current = min_band_depth(peak, zone)
            self.assertGreater(current, prev, f"peak={peak} nicht > vorheriger")
            prev = current

    def test_formula_match_mittelland(self):
        # base = 1.4 × (31.5 × peak + 158), terrain_factor mittelland = 1.0
        for peak in (1.5, 2.0, 2.5, 3.0, 4.0):
            expected = 1.4 * (31.5 * peak + 158.0)
            self.assertAlmostEqual(min_band_depth(peak, "mittelland"), expected, places=2)

    def test_formula_match_hochalpin(self):
        # base × 0.50 fuer hochalpin
        for peak in (1.5, 2.5, 4.0):
            expected = 1.4 * (31.5 * peak + 158.0) * 0.50
            self.assertAlmostEqual(min_band_depth(peak, "hochalpin"), expected, places=2)

    def test_unknown_zone_defaults_to_1_0(self):
        # Unbekannte Zone -> Faktor 1.0 (konservativ wie mittelland)
        self.assertAlmostEqual(
            min_band_depth(2.0, "unbekannt"),
            min_band_depth(2.0, "mittelland"),
            places=2,
        )

    def test_invalid_climb_input_returns_inf(self):
        for bad in (None, "x", [], {}):
            self.assertTrue(math.isinf(min_band_depth(bad, "mittelland")))  # type: ignore[arg-type]

    def test_realistic_voralpen_15ms_below_old_400m(self):
        # Beispiel aus Research-Doc: 1.5 m/s Voralpen sollte unter alter
        # Konstante (400 m) liegen — Jura-/Voralpen-Tage werden so wieder
        # als produktiv erkannt.
        result = min_band_depth(1.5, "voralpen")
        self.assertLess(result, 400.0)

    def test_realistic_mittelland_25ms_below_old_400m(self):
        # Auch 2.5 m/s Mittelland (typischer Sommer-Cu-Tag) muss < 400 m
        # bleiben, sonst False-Positive "band-flach" wie vor dem Refactor.
        result = min_band_depth(2.5, "mittelland")
        self.assertLess(result, 400.0)


if __name__ == "__main__":
    unittest.main()
