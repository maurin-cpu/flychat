"""Nach dem Login eine Frage: Briefing fuer welche Region?

Bis 10/2026 war die Regionswahl ein freiwilliger Abschnitt der Konto-Seite.
15 von 32 aktiven Konten hatten keine Region und bekamen nie ein Briefing,
ohne es gewaehlt oder abgelehnt zu haben. Jetzt fuehrt der Login ohne Region
auf /willkommen, bis das Konto Regionen hat oder "Ohne Briefing weiter" waehlt.
"""
import os
import unittest
from unittest import mock

from subscriber import SubscriberManager


def test_decline_is_stored_and_keeps_first_timestamp(tmp_path):
    mgr = SubscriberManager(tmp_path / "subscribers.db")
    tok = mgr.create_login_token("neu@example.com")
    sid = mgr.consume_login_token(tok["login_token"])["id"]
    assert mgr.get_session_user(sid)["briefing_declined_at"] is None
    assert mgr.record_briefing_decline(sid)
    first = mgr.get_session_user(sid)["briefing_declined_at"]
    assert first
    assert mgr.record_briefing_decline(sid)
    assert mgr.get_session_user(sid)["briefing_declined_at"] == first


class TestWillkommen(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self._env = mock.patch.dict(os.environ, {"LOCAL_AUTO_LOGIN": "0"})
        self._env.start()
        self._tmp = tempfile.TemporaryDirectory()
        self.mgr = SubscriberManager(Path(self._tmp.name) / "subscribers.db")
        import web
        self.web = web
        self._patch = mock.patch.object(web, "_get_subscriber_manager", return_value=self.mgr)
        self._patch.start()
        self.client = web.app.test_client()
        self.region = web._regions_for_form()[0]["id"]

    def tearDown(self):
        self._patch.stop()
        self._env.stop()
        self._tmp.cleanup()

    def _login(self, email="neu@example.com"):
        tok = self.mgr.create_login_token(email)["login_token"]
        return self.client.post(f"/login/{tok}", environ_base={"REMOTE_ADDR": "203.0.113.7"})

    def test_new_account_lands_on_question_and_starts_briefing(self):
        resp = self._login()
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["Location"].endswith("/willkommen"))

        page = self.client.get("/willkommen")
        self.assertEqual(page.status_code, 200)
        self.assertIn('id="spRegionFilters"', page.get_data(as_text=True))

        resp = self.client.post("/willkommen", data={"choice": "start", "regions": [self.region]})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/account/", resp.headers["Location"])
        sid = self.mgr.get_session_user(1)
        self.assertEqual(sid["regions"], [self.region])
        # Versandtage und Spot-Auswahl bleiben auf den Defaults, also wird versendet
        self.assertEqual(len(sid["active_weekdays"]), 7)
        self.assertTrue(sid["min_tier_set"])

        # Mit Region fragt niemand mehr
        self.assertTrue(self.client.get("/willkommen").headers["Location"].endswith("/account"))
        self.assertTrue(self._login().headers["Location"].endswith("/account"))

    def test_start_without_region_stays_on_question(self):
        self._login()
        resp = self.client.post("/willkommen", data={"choice": "start"})
        self.assertIn("/willkommen?err=", resp.headers["Location"])
        self.assertFalse(self.mgr.get_session_user(1)["regions"])

    def test_skip_is_remembered(self):
        self._login()
        resp = self.client.post("/willkommen", data={"choice": "skip"})
        self.assertTrue(resp.headers["Location"].endswith("/"))
        sub = self.mgr.get_session_user(1)
        self.assertFalse(sub["regions"])
        self.assertTrue(sub["briefing_declined_at"])
        # Naechster Login: keine Frage mehr
        self.assertTrue(self._login().headers["Location"].endswith("/account"))

    def test_anonymous_goes_to_login(self):
        self.assertTrue(self.client.get("/willkommen").headers["Location"].endswith("/login"))
