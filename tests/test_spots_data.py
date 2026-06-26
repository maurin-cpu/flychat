import unittest
from spots import load_spots

class TestSpotsData(unittest.TestCase):
    def test_new_columns_loaded(self):
        """Prüft, ob die PGE-Schema-Spalten aus der CSV korrekt geladen werden."""
        spots = load_spots()
        self.assertGreater(len(spots), 0)

        # Spot mit vollständiger Geometrie (Baldern/Uetliberg)
        baldern = next((s for s in spots if s["name"] == "Baldern (Uetliberg)"), None)
        self.assertIsNotNone(baldern)
        self.assertEqual(baldern["slope_azimuth"], 225)
        self.assertEqual(baldern["slope_angle"], 30)
        self.assertEqual(baldern["kritischer_foehn"], "Süd")
        # Sektor-Flags NE/E/SE -> legacy windrichtung
        self.assertEqual(baldern["windrichtung"], "NO-O-SO")

        # Spot mit fehlenden Geometrie-Werten (First) -> Defaults
        first = next((s for s in spots if s["name"] == "First"), None)
        self.assertIsNotNone(first)
        self.assertIsNone(first["slope_azimuth"])  # leer -> None
        self.assertEqual(first["slope_angle"], 25)  # leer -> Default 25
        self.assertEqual(first["kritischer_foehn"], "Süd")

if __name__ == "__main__":
    unittest.main()
