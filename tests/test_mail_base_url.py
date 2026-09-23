"""Mail-Links aus dem Scheduler duerfen nicht auf localhost zeigen.

23.09.2026: Das Briefing lief in test_request_context() ohne base_url —
request.host_url war "http://localhost/", Oeffnungs-Pixel und Klick-Links
zeigten auf localhost, keine einzige Oeffnung kam an. Dasselbe traf die
Abmelde-/Konto-Links der Monats-Treffer-Mail.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import email_service  # noqa: E402
import mail_tracking  # noqa: E402


class MailBaseUrlTest(unittest.TestCase):
    def setUp(self):
        from web import app
        self.app = app
        self._old = config.BASE_URL
        config.BASE_URL = "https://app.wingcast.ch"

    def tearDown(self):
        config.BASE_URL = self._old

    def test_mail_context_liefert_prod_domain(self):
        with email_service.mail_context(self.app):
            base = email_service._resolve_base_url()
            self.assertEqual(base, "https://app.wingcast.ch")
            self.assertTrue(mail_tracking.pixel_url(base, 7, "2026-09-23")
                            .startswith("https://app.wingcast.ch/t/o/7/"))
            urls = email_service._build_urls(action_token="X")
            self.assertEqual(urls["unsubscribe"], "https://app.wingcast.ch/unsubscribe/X")

    def test_echter_request_behaelt_eigenen_host(self):
        with self.app.test_request_context(base_url="http://localhost:5000"):
            self.assertEqual(email_service._resolve_base_url(), "http://localhost:5000")


if __name__ == "__main__":
    unittest.main()
