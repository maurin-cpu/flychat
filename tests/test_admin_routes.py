"""Teure Server-Aktionen nur fuer Admins.

KI-Analysen, Wetter-Neuladen und Stations-Abrufe kosten Geld bzw. Rechenzeit
und koennen die Morgenanalyse ueberschreiben. Ohne Admin-Session muss jede
dieser Adressen 403 liefern — und darf die Aktion gar nicht erst starten.
"""
import os
import unittest
from unittest import mock

PROTECTED = [
    ("GET", "/api/run-analyses-stream"),
    ("GET", "/api/run-region-analyses-stream"),
    ("POST", "/api/refresh-weather"),
    ("POST", "/api/stations/discover"),
    ("POST", "/api/stations/collect"),
]

# Seit 04.10.2026 entfernt (kein Aufrufer mehr) — duerfen nicht zurueckkommen,
# schon gar nicht ungeschuetzt.
REMOVED = [
    ("POST", "/api/run-analyses"),
    ("POST", "/api/run-region-analyses"),
    ("GET", "/api/run-all-analyses-stream"),
    ("GET", "/api/analyses-status"),
    ("POST", "/api/refresh-spots"),
    ("GET", "/api/thresholds"),
]

REMOTE = {"REMOTE_ADDR": "203.0.113.7"}


class TestAdminOnlyRoutes(unittest.TestCase):
    def setUp(self):
        # Lokales Auto-Login (Windows-Dev) aus — sonst waere der Test-Client Admin
        self._env = mock.patch.dict(os.environ, {"LOCAL_AUTO_LOGIN": "0"})
        self._env.start()
        import web
        self.web = web
        self.client = web.app.test_client()

    def tearDown(self):
        self._env.stop()

    def test_anonymous_gets_403_and_nothing_runs(self):
        engine = mock.MagicMock()
        with mock.patch.object(self.web, "engine", engine):
            for method, path in PROTECTED:
                with self.subTest(path=path):
                    resp = self.client.open(path, method=method, environ_base=REMOTE)
                    self.assertEqual(resp.status_code, 403, path)
        self.assertEqual(engine.method_calls, [], "Aktion wurde trotz 403 gestartet")

    def test_logged_in_non_admin_gets_403(self):
        with self.client.session_transaction() as s:
            s["sub_id"] = 42
            s["email"] = "pilot@example.com"
        for method, path in PROTECTED:
            with self.subTest(path=path):
                resp = self.client.open(path, method=method, environ_base=REMOTE)
                self.assertEqual(resp.status_code, 403, path)

    def test_admin_still_passes(self):
        import config
        engine = mock.MagicMock()
        engine.weather_data = {"_meta": {"last_updated": "2026-10-04T05:00:00"}, "Spot A": {}}
        engine.last_refresh_stale = False
        with self.client.session_transaction() as s:
            s["sub_id"] = 1
            s["email"] = config.ADMIN_EMAIL
        with mock.patch.object(self.web, "engine", engine):
            resp = self.client.post("/api/refresh-weather", environ_base=REMOTE)
        self.assertNotEqual(resp.status_code, 403)
        engine.refresh_weather.assert_called_once_with(force=True)

    def test_removed_routes_are_gone(self):
        for method, path in REMOVED:
            with self.subTest(path=path):
                resp = self.client.open(path, method=method, environ_base=REMOTE)
                self.assertIn(resp.status_code, (404, 405), path)


if __name__ == "__main__":
    unittest.main()
