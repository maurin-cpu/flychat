"""Haftungshinweis am Konto quittieren: DB-Spalte, Endpoint, Modal-Steuerung.

Vorher lag das "Verstanden" nur im Browser (localStorage) und war im Streitfall
keinem Nutzer zuordenbar. Jetzt: eingeloggt und nicht quittiert -> Modal wird
erzwungen (disclaimer_pending), der Klick landet per POST am Konto.
"""
import os
import unittest
from unittest import mock

from subscriber import SubscriberManager


def _mgr_mit_konto(tmp_path):
    mgr = SubscriberManager(tmp_path / "subscribers.db")
    created = mgr.create("pilot@example.com", ["Jura"], "standard")
    sub = mgr.confirm(created["confirm_token"])
    return mgr, sub["id"]


def test_record_keeps_first_timestamp_and_updates_version(tmp_path):
    mgr, sid = _mgr_mit_konto(tmp_path)
    assert mgr.get_session_user(sid)["disclaimer_accepted_at"] is None
    assert mgr.record_disclaimer_accept(sid, "v1")
    first = mgr.get_session_user(sid)["disclaimer_accepted_at"]
    assert first
    assert mgr.record_disclaimer_accept(sid, "v2")
    sub = mgr.get_session_user(sid)
    assert sub["disclaimer_accepted_at"] == first
    assert sub["disclaimer_version"] == "v2"


def test_record_unknown_account_is_false(tmp_path):
    mgr, _ = _mgr_mit_konto(tmp_path)
    assert mgr.record_disclaimer_accept(999, "v1") is False


class TestDisclaimerRoute(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, {"LOCAL_AUTO_LOGIN": "0"})
        self._env.start()
        import web
        self.web = web
        self.client = web.app.test_client()

    def tearDown(self):
        self._env.stop()

    def test_anonymous_cannot_record(self):
        resp = self.client.post("/api/disclaimer-accept",
                                environ_base={"REMOTE_ADDR": "203.0.113.7"})
        self.assertEqual(resp.status_code, 401)

    def test_logged_in_pending_then_accepted(self):
        mgr = mock.MagicMock()
        mgr.get_session_user.return_value = {"id": 7, "disclaimer_accepted_at": None,
                                             "disclaimer_version": None}
        mgr.record_disclaimer_accept.return_value = True
        with self.client.session_transaction() as s:
            s["sub_id"] = 7
            s["email"] = "pilot@example.com"
        with mock.patch.object(self.web, "_get_subscriber_manager", return_value=mgr):
            with self.web.app.test_request_context():
                from flask import session
                session["sub_id"] = 7
                self.assertFalse(self.web._disclaimer_accepted())
            resp = self.client.post("/api/disclaimer-accept",
                                    environ_base={"REMOTE_ADDR": "203.0.113.7"})
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.get_json()["ok"])
            mgr.record_disclaimer_accept.assert_called_once_with(7, self.web.DISCLAIMER_VERSION)
            # Nach der Quittierung fragt niemand mehr die DB: Session merkt es sich.
            mgr.get_session_user.reset_mock()
            with self.client.session_transaction() as s:
                self.assertEqual(s.get("disclaimer_ok"), self.web.DISCLAIMER_VERSION)
