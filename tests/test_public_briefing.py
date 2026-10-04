"""Tests fuer das oeffentliche Briefing (engine/public_briefing.py, i18n.lang_override,
GET /api/public/briefing).

  - lang_override gilt nur im eigenen Thread und nur im Block
  - synoptic_cache_path legt fremde Sprachen in eine eigene Datei
  - slim_chain laesst interne Felder weg und kuerzt auf PUBLIC_BRIEFING_DAYS
  - Endpunkt: 200 frisch, 503 fehlend/alt, 404 unbekannte Sprache

LLM-Calls werden NICHT getestet (Integration).
"""
import json
import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import config
import i18n
from engine import public_briefing as pb


class LangOverrideTest(unittest.TestCase):
    def test_block_and_thread_local(self):
        base = i18n.get_current_lang()
        seen_in_thread = []

        def worker(ready, release):
            ready.set()
            release.wait(5)
            seen_in_thread.append(i18n.get_current_lang())

        ready, release = threading.Event(), threading.Event()
        t = threading.Thread(target=worker, args=(ready, release))
        t.start()
        ready.wait(5)
        other = "en" if base == "de" else "de"
        with i18n.lang_override(other):
            self.assertEqual(i18n.get_current_lang(), other)
            release.set()
            t.join(5)
        self.assertEqual(i18n.get_current_lang(), base)
        self.assertEqual(seen_in_thread, [base])

    def test_unknown_lang_ignored(self):
        base = i18n.get_current_lang()
        with i18n.lang_override("fr"):
            self.assertEqual(i18n.get_current_lang(), base)


class CachePathTest(unittest.TestCase):
    def test_other_lang_gets_own_file(self):
        from engine.synoptic_context import synoptic_cache_path
        server = i18n.get_server_lang()
        other = "en" if server == "de" else "de"
        base = Path(config.SYNOPTIC_CACHE_PATH)
        self.assertEqual(synoptic_cache_path(None), base)
        self.assertEqual(synoptic_cache_path(server), base)
        self.assertEqual(synoptic_cache_path(other).name, f"{base.stem}.{other}{base.suffix}")


def _analyse(n_days=5):
    dates = [f"2026-10-{4 + i:02d}" for i in range(n_days)]
    by_date = {}
    for d in dates:
        by_date[d] = {
            "tile": {"tier": "green", "band": "green", "status": "Sicher", "rating": 3, "n": 29,
                     "pressure_hpa": "1029 hPa", "wind_arrow": "↙", "wind_sector": "NE",
                     "wind_strength": "schwach", "wind_hot": False, "wind_dir_deg": 34},
            "warnings": {"any": True, "has_ki": True,
                         "checks": [{"topic": "RAIN", "label": "Regen", "active": True, "level": "warn"}],
                         "entries": [{"topic": "RAIN", "label": "Regen", "severity": "warn",
                                      "ki_text": "Schauer ab Mittag.", "code_text": "Regen Nordalpen."}]},
            "chain": {
                "situation": "Hochdruck mit schwacher Bise.",
                "day_hint": "Trocken, am Nachmittag Schauer.",
                "lage": {"fazit": "Hoch Azoren.", "status": "ok", "status_label": "Daten passen zur Lage",
                         "label": "Hochdruck", "centers": [{"region": "Azoren", "msl": 1030}],
                         "pressure": "1029.2 hPa", "regime": "Hochdruck", "verdict": "match"},
                "stability": {"fazit": "Teils labil.", "status": "info", "status_label": "teils labil",
                              "labile": True, "facts": [{"k": "T850", "v": "12.2°"}], "thunder": []},
                "thermik": {"fazit": "Mässiges Steigen.", "status": "info", "status_label": "mässiges Steigen",
                            "num": {"base": "2400–3000 m", "climb": "1.4–1.8 m/s", "lbl_base": "Basis",
                                    "lbl_climb": "Steigen", "zones": [{"name": "Nordalpen", "base": "2600 m", "climb": "1.4 m/s"}]}},
            },
        }
    return {"dates": dates, "lang": "de", "generated_at": "2026-10-04T06:12:56",
            "labels": {"step_lage": "Lage", "hz_none": "Keine Gefahr."},
            "source": "Daten: ICON", "by_date": by_date, "attempts": 3, "unresolved": ["x"]}


class SlimChainTest(unittest.TestCase):
    def test_whitelist_and_days(self):
        out = pb.slim_chain(_analyse(5), days=3)
        self.assertEqual(len(out["dates"]), 3)
        self.assertEqual(set(out["by_date"]), set(out["dates"]))
        self.assertNotIn("attempts", out)
        self.assertNotIn("unresolved", out)
        d = out["by_date"][out["dates"][0]]
        self.assertNotIn("wind_dir_deg", d["tile"])
        self.assertEqual(d["tile"]["status"], "Sicher")
        self.assertEqual(d["warnings"]["entries"][0]["ki_text"], "Schauer ab Mittag.")
        lage = d["chain"]["lage"]
        self.assertEqual(lage["fazit"], "Hoch Azoren.")
        for internal in ("centers", "pressure", "regime", "verdict", "label"):
            self.assertNotIn(internal, lage)
        self.assertTrue(d["chain"]["stability"]["labile"])
        self.assertEqual(d["chain"]["thermik"]["num"]["zones"][0]["name"], "Nordalpen")
        self.assertIsNone(d["chain"]["fronts"])
        self.assertEqual(out["labels"]["step_lage"], "Lage")
        json.dumps(out, ensure_ascii=False)  # serialisierbar

    def test_missing_chain_stays_none(self):
        a = _analyse(1)
        a["by_date"][a["dates"][0]]["chain"] = None
        out = pb.slim_chain(a, days=3)
        self.assertIsNone(out["by_date"][a["dates"][0]]["chain"])


class EndpointTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_dir = config.PUBLIC_BRIEFING_DIR
        self._old_langs = config.PUBLIC_BRIEFING_LANGS
        config.PUBLIC_BRIEFING_DIR = Path(self._tmp.name)
        config.PUBLIC_BRIEFING_LANGS = ("de", "en")
        # Auf dem Windows-Dev-Rechner loggt web.py jeden lokalen Request als
        # Admin ein (_local_auto_login) — fuer den Admin-Gate-Test abschalten.
        self._old_auto = os.environ.get("LOCAL_AUTO_LOGIN")
        os.environ["LOCAL_AUTO_LOGIN"] = "0"
        import web
        self.client = web.app.test_client()

    def tearDown(self):
        config.PUBLIC_BRIEFING_DIR = self._old_dir
        config.PUBLIC_BRIEFING_LANGS = self._old_langs
        if self._old_auto is None:
            os.environ.pop("LOCAL_AUTO_LOGIN", None)
        else:
            os.environ["LOCAL_AUTO_LOGIN"] = self._old_auto
        self._tmp.cleanup()

    def _write(self, lang, generated_at):
        payload = pb.slim_chain(_analyse(3), days=3)
        payload["lang"] = lang
        payload["generated_at"] = generated_at
        pb.write_public_briefing(lang, payload)

    def test_fresh_200(self):
        self._write("de", datetime.now().replace(microsecond=0).isoformat())
        r = self.client.get("/api/public/briefing?lang=de")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["available"])
        self.assertEqual(body["lang"], "de")
        self.assertEqual(len(body["dates"]), 3)
        self.assertIn("public", r.headers.get("Cache-Control", ""))
        self.assertNotIn("attempts", body)

    def test_missing_503(self):
        r = self.client.get("/api/public/briefing?lang=en")
        self.assertEqual(r.status_code, 503)
        self.assertFalse(r.get_json()["available"])

    def test_stale_503(self):
        old = (datetime.now() - timedelta(hours=config.PUBLIC_BRIEFING_MAX_AGE_H + 1))
        self._write("de", old.replace(microsecond=0).isoformat())
        r = self.client.get("/api/public/briefing?lang=de")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.get_json()["reason"], "stale")

    def test_unknown_lang_404(self):
        r = self.client.get("/api/public/briefing?lang=fr")
        self.assertEqual(r.status_code, 404)

    def test_generate_requires_admin(self):
        r = self.client.post("/api/briefing/generate")
        self.assertIn(r.status_code, (401, 403, 302))


if __name__ == "__main__":
    unittest.main()
