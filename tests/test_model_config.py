import os
import unittest
from unittest.mock import patch
from chat_engine import FlychatEngine

class TestModelConfig(unittest.TestCase):
    def test_default_model(self):
        """Testet, ob das Standardmodell korrekt auf gpt-4o-mini gesetzt ist."""
        with patch.dict(os.environ, {}, clear=True):
            engine = FlychatEngine()
            self.assertEqual(engine.model, "gpt-4o-mini")

    def test_env_model_override(self):
        """Testet, ob die Umgebungsvariable OPENAI_MODEL korrekt priorisiert wird."""
        test_model = "gpt-something-else"
        with patch.dict(os.environ, {"OPENAI_MODEL": test_model}):
            engine = FlychatEngine()
            self.assertEqual(engine.model, test_model)

if __name__ == "__main__":
    unittest.main()
