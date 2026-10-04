"""Teure Server-Aktionen nur fuer Admins.

KI-Analysen, Wetter-Neuladen und Stations-Abrufe kosten Geld bzw. Rechenzeit
und koennen die Morgenanalyse ueberschreiben. Ohne Admin-Session muss jede
dieser Adressen 403 liefern — und darf die Aktion gar nicht erst starten.
"""
import os
import unittest
from unittest import mock

PROTECTED = [
    ("POST", "/api/run-analyses"),
    ("POST", "/api/run-region-analyses"),
    ("GET", "/api/run-all-analyses-stream"),
    ("GET", "/api/run-analyses-stream"),
    ("GET", "/api/run-region-analyses-stream"),
    ("POST", "/api/refresh-spots"),
    ("POST", "/api/refresh-weather"),
    ("POST", "/api/stations/discover"),
    ("POST", "/api/stations/collect"),
]


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
                    resp = self.client.open(path, method=method,
                                            environ_base={"REMOTE_ADDR": "203.0.113.7"})
                    self.assertEqual(resp.status_code, 403, path)
        self.assertEqual(engine.method_calls, [], "Aktion wurde trotz 403 gestartet")

    def test_admin_still_passes(self):
        import config
        engine = mock.MagicMock()
        engine.reload_spots.return_value = 500
        with self.client.session_transaction() as s:
            s["sub_id"] = 1
            s["email"] = config.ADMIN_EMAIL
        with mock.patch.object(self.web, "engine", engine):
            resp = self.client.post("/api/refresh-spots",
                                    environ_base={"REMOTE_ADDR": "203.0.113.7"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["spots_count"], 500)

    def test_logged_in_non_admin_gets_403(self):
        with self.client.session_transaction() as s:
            s["sub_id"] = 42
            s["email"] = "pilot@example.com"
        for method, path in PROTECTED:
            with self.subTest(path=path):
                resp = self.client.open(path, method=method,
                                        environ_base={"REMOTE_ADDR": "203.0.113.7"})
                self.assertEqual(resp.status_code, 403, path)


if __name__ == "__main__":
    unittest.main()
