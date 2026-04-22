import unittest
from chat_engine import GleitcastEngine

class TestLLMControl(unittest.TestCase):
    def setUp(self):
        self.engine = GleitcastEngine()

    def test_initial_no_weather_context(self):
        """Testet, ob initial kein Wetter-Kontext vorhanden ist."""
        self.assertFalse(self.engine.weather_context_str)

    def test_weather_context_after_set(self):
        """Testet, ob Wetter-Kontext korrekt gesetzt wird."""
        self.engine.weather_context_str = "Hitzetag am Pilatus. 30 Grad."
        self.assertIsNotNone(self.engine.weather_context_str)
        self.assertIn("Pilatus", self.engine.weather_context_str)

if __name__ == "__main__":
    unittest.main()
