import unittest
from spots import load_spots

class TestSpotsData(unittest.TestCase):
    def test_new_columns_loaded(self):
        """Prüft, ob die neuen Spalten aus der CSV korrekt geladen werden."""
        spots = load_spots()
        self.assertGreater(len(spots), 0)
        
        # Prüfe Balderen (Uetliberg)
        balderen = next((s for s in spots if s["name"] == "Balderen"), None)
        self.assertIsNotNone(balderen)
        self.assertEqual(balderen["ideal_wind_min"], 15)
        self.assertEqual(balderen["ideal_wind_max"], 30)
        self.assertEqual(balderen["slope_azimuth"], 225)
        self.assertEqual(balderen["slope_angle"], 30)
        self.assertEqual(balderen["kritischer_foehn"], "Süd")
        
        # Prüfe einen Spot mit fehlenden Werten (First)
        first = next((s for s in spots if s["name"] == "First"), None)
        self.assertIsNotNone(first)
        self.assertEqual(first["ideal_wind_min"], 5)  # Default
        self.assertIsNone(first["slope_azimuth"])
        self.assertEqual(first["kritischer_foehn"], "Süd")

if __name__ == "__main__":
    unittest.main()
