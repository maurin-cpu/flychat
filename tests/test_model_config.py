import os
import unittest
from unittest.mock import patch
import config
from chat_engine import WingcastEngine

class TestModelConfig(unittest.TestCase):
    def test_default_model(self):
        """Testet, ob das Standardmodell korrekt auf gpt-4o-mini gesetzt ist."""
        with patch.dict(os.environ, {}, clear=True):
            engine = WingcastEngine()
            self.assertEqual(engine.model, "gpt-4o-mini")

    def test_config_model_override(self):
        """Override via setattr(config, 'OPENAI_CHAT_MODEL', ...) greift sofort.

        Ersetzt die alte OPENAI_MODEL-ENV-Variable: get_model() liest jetzt
        das Top-Level-config-Attribut (Admin-UI-Mechanismus), das WingcastEngine
        beim (Re-)Init via config.get_model(provider, 'chat') uebernimmt.
        """
        test_model = "gpt-something-else"
        with patch.object(config, "CHAT_PROVIDER", "openai"), \
                patch.object(config, "OPENAI_CHAT_MODEL", test_model):
            engine = WingcastEngine()
            self.assertEqual(engine.model, test_model)

if __name__ == "__main__":
    unittest.main()
