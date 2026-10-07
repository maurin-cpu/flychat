"""Föhn-Bestätigung durch die Talpunkte — nur im Briefing (docs/FOEHN.md).

Regel, Abruf, Auswertung pro Tag, Snapshot, Briefing-Satz/Chips/Warnbox,
KI-Payload und Validator. Kern: eine Zahl, eine Quelle — dieselben Talwerte in
Block 3, Chips, Warnbox und KI-Payload.
"""
import re
import unittest
from unittest import mock

import config
import foehn_indicators as fi
import foehn_talpunkte as ft
from engine import synoptic_context as sc
from engine import synoptic_llm as sl
from scripts import briefing_v3_context as bc

DATE = "2026-09-16"
HOURS = list(range(24))
TIMES = [f"{DATE}T{h:02d}:00" for h in HOURS]


def _hourly(wind=8.0, gust=15.0, direction=300.0, rh=70.0, foehn_hours=(), fw=(), fg=(), fdir=170.0, frh=38.0):
    """Stundenreihe eines Talpunkts: ruhig, ausser in `foehn_hours` (Werte fw/fg)."""
    h = {"wind_speed_10m": [wind] * 24, "wind_gusts_10m": [gust] * 24,
         "wind_direction_10m": [direction] * 24, "relative_humidity_2m": [rh] * 24,
         "temperature_2m": [15.0] * 24}
    for k, hour in enumerate(foehn_hours):
        h["wind_speed_10m"][hour] = fw[k]
        h["wind_gusts_10m"][hour] = fg[k]
        h["wind_direction_10m"][hour] = fdir
        h["relative_humidity_2m"][hour] = frh
    return h


def _series(confirmed: bool = True) -> dict:
    """Talreihe wie fetch_talpunkt_wind: Reusstal + Haslital mit Föhn (wenn
    confirmed), Glarus ruhig, ein Nordföhntal (zählt bei Südföhn nicht)."""
    punkte = {
        "alt": {"meta": {"id": "alt", "tal": "Reusstal / Urnerland", "station": "Altdorf",
                         "region_id": "zentralschweizer_alpen", "foehn_typ": "Süd"},
                "hourly": _hourly(foehn_hours=(11, 12, 13), fw=(22, 30, 34), fg=(40, 55, 50))
                if confirmed else _hourly()},
        "mer": {"meta": {"id": "mer", "tal": "Haslital", "station": "Meiringen",
                         "region_id": "berner_alpen", "foehn_typ": "Süd"},
                "hourly": _hourly(foehn_hours=(12, 13), fw=(24, 28), fg=(45, 52))
                if confirmed else _hourly()},
        "gla": {"meta": {"id": "gla", "tal": "Glarnerland (Linthtal, unten)", "station": "Glarus",
                         "region_id": "glarner_alpen", "foehn_typ": "Süd"},
                "hourly": _hourly()},
        "pio": {"meta": {"id": "pio", "tal": "Leventina", "station": "Piotta",
                         "region_id": "leventina_blenio", "foehn_typ": "Nord"},
                "hourly": _hourly(foehn_hours=(10, 11, 12), fw=(30, 30, 30), fg=(50, 50, 50), fdir=0.0)},
    }
    return {"model": "meteoswiss_icon_ch2", "time": TIMES, "punkte": punkte}


class TestRegel(unittest.TestCase):
    def test_sector_wraps_over_north(self):
        self.assertTrue(fi.dir_in_sector(10, 270, 90))
        self.assertTrue(fi.dir_in_sector(300, 270, 90))
        self.assertFalse(fi.dir_in_sector(180, 270, 90))
        self.assertTrue(fi.dir_in_sector(180, 90, 270))

    def test_foehn_hours_need_direction_strength_and_dryness(self):
        idx = list(range(6, 18))
        h = _hourly(foehn_hours=(11, 12), fw=(22, 10), fg=(25, 35))
        r = fi.evaluate_talpunkt(h, idx, "Süd")
        self.assertTrue(r["bestaetigt"])
        self.assertEqual((r["wind_min_kmh"], r["wind_max_kmh"], r["gust_max_kmh"]), (10, 22, 35))
        self.assertEqual(r["first_index"], 11)
        wrong_dir = _hourly(foehn_hours=(11, 12), fw=(30, 30), fg=(50, 50), fdir=330.0)
        self.assertFalse(fi.evaluate_talpunkt(wrong_dir, idx, "Süd")["bestaetigt"])
        humid = _hourly(foehn_hours=(11, 12), fw=(30, 30), fg=(50, 50), frh=85.0)
        self.assertFalse(fi.evaluate_talpunkt(humid, idx, "Süd")["bestaetigt"])
        one_hour = _hourly(foehn_hours=(11,), fw=(30,), fg=(50,))
        self.assertFalse(fi.evaluate_talpunkt(one_hour, idx, "Süd")["bestaetigt"])

    def test_missing_data_is_not_no_foehn(self):
        h = {"wind_speed_10m": [None] * 24, "wind_gusts_10m": [None] * 24,
             "wind_direction_10m": [None] * 24, "relative_humidity_2m": [None] * 24}
        r = fi.evaluate_talpunkt(h, list(range(6, 18)), "Süd")
        self.assertFalse(r["has_data"])
        s = fi.summarize_taeler([{**r, "tal": "X"}])
        self.assertEqual(s["n_total"], 0)

    def test_wallis_sector_includes_east(self):
        h = _hourly(foehn_hours=(11, 12), fw=(25, 25), fg=(40, 40), fdir=80.0)
        self.assertTrue(fi.evaluate_talpunkt(h, list(range(6, 18)), "Süd(-ost)")["bestaetigt"])
        self.assertFalse(fi.evaluate_talpunkt(h, list(range(6, 18)), "Süd")["bestaetigt"])


class TestKurzname(unittest.TestCase):
    def test_short_names(self):
        self.assertEqual(ft.tal_kurzname("Reusstal / Urnerland"), "Reusstal")
        self.assertEqual(ft.tal_kurzname("Misox (unten)"), "Misox")
        self.assertEqual(ft.tal_kurzname("St. Galler Rheintal oben"), "St. Galler Rheintal")


class TestAbruf(unittest.TestCase):
    def _resp(self, n):
        r = mock.Mock()
        r.raise_for_status.return_value = None
        r.json.return_value = [{"hourly": {"time": TIMES, "wind_speed_10m": [1.0] * 24}}] * n
        return r

    def test_fetch_maps_points_by_id(self):
        n = len(ft.load_talpunkte())
        with mock.patch("foehn_talpunkte.requests.get", return_value=self._resp(n)):
            d = ft.fetch_talpunkt_wind(1)
        self.assertEqual(len(d["punkte"]), n)
        self.assertEqual(d["model"], config.SURFACE_SECONDARY_MODEL)
        self.assertIn("foehn_typ", d["punkte"]["alt"]["meta"])

    def test_fetch_rejects_length_mismatch(self):
        n = len(ft.load_talpunkte())
        with mock.patch("foehn_talpunkte.requests.get", return_value=self._resp(n - 1)):
            self.assertIsNone(ft.fetch_talpunkt_wind(1))


class TestTagesauswertung(unittest.TestCase):
    def test_confirmed_day(self):
        t = sc.foehn_tal_for_day(_series(), DATE, "sued")
        self.assertEqual(t["n_total"], 3)                 # Nordtal zählt bei Südföhn nicht
        self.assertEqual(t["n_bestaetigt"], 2)
        self.assertEqual((t["wind_min_kmh"], t["wind_max_kmh"], t["gust_max_kmh"]), (22, 34, 55))
        self.assertEqual(t["gust_tal"], "Reusstal / Urnerland")
        self.assertEqual(t["first_hour"], 11)
        self.assertEqual(ft.tal_namen(t), ["Reusstal", "Haslital"])

    def test_no_series_gives_none(self):
        self.assertIsNone(sc.foehn_tal_for_day(None, DATE, "sued"))

    def test_decide_foehn_summary_attaches_tal_only_on_foehn_days(self):
        nord_times = TIMES
        data = {"nord": {"hourly": {"time": nord_times, "pressure_msl": [1015.0] * 24}},
                "sued": {"hourly": {"time": nord_times, "pressure_msl": [1021.0] * 24}}}
        cache = {"_meta": {"foehn_tal_series": _series()}}
        with mock.patch("foehn_indicators.fetch_foehn_data", return_value=data):
            out = sc.decide_foehn_summary([DATE], weather_cache=cache)
            plain = sc.decide_foehn_summary([DATE])
        day = out["per_day"][0]
        self.assertTrue(day["sued_active"])
        self.assertEqual(day["tal"]["n_bestaetigt"], 2)
        self.assertIsNone(plain["per_day"][0]["tal"])
        calm = {"nord": data["nord"], "sued": {"hourly": {"time": nord_times, "pressure_msl": [1015.0] * 24}}}
        with mock.patch("foehn_indicators.fetch_foehn_data", return_value=calm):
            out = sc.decide_foehn_summary([DATE], weather_cache=cache)
        self.assertIsNone(out["per_day"][0]["tal"])


def _wetterlage(tal):
    return {"forecast_dates": [DATE], "foehn": {"per_day": [{
        "date": DATE, "sued_active": True, "nord_active": False, "peak_sued": "caution",
        "peak_nord": "none", "sued_hours": 6, "nord_hours": 0,
        "sued_windows": {"morning": {"hours": 0, "peak": "none"}, "midday": {"hours": 3, "peak": "caution"},
                         "afternoon": {"hours": 3, "peak": "caution"}, "evening": {"hours": 0, "peak": "none"}},
        "nord_windows": {}, "claim": {"delta_p_sued_max_hpa": 6.2},
        "lee": {"gust_nord_max_kmh": 40}, "tal": tal}]}}


def _day(tal):
    out = bc.build_chain_all_days(_wetterlage(tal), [DATE])
    return out["by_date"][DATE]


def _foehn_warning(day):
    return next(w for w in day["warnings"]["entries"] if w.get("topic") == "FOEHN")


class TestBriefing(unittest.TestCase):
    def setUp(self):
        self._lang = config.LANG
        config.LANG = "de"

    def tearDown(self):
        config.LANG = self._lang

    def test_confirmed_sentence_chips_and_warnbox_use_same_numbers(self):
        tal = sc.foehn_tal_for_day(_series(), DATE, "sued")
        day = _day(tal)
        fazit = day["chain"]["foehn"]["fazit"]
        self.assertIn("zeigt den Föhn auch am Boden in Reusstal, Haslital", fazit)
        self.assertIn("Wind 22–34 km/h aus Süd, Böen bis 55 km/h (Reusstal), ab Mittag", fazit)
        facts = {f["k"]: f["v"] for f in day["chain"]["foehn"]["facts"]}
        self.assertEqual(facts["Föhntäler"], "2/3")
        self.assertEqual(facts["Böe"], "55 km/h")
        code = _foehn_warning(day)["code_text"]
        self.assertIn("In den Föhntälern Wind 22–34 km/h, Böen bis 55 km/h (Reusstal).", code)
        self.assertNotIn("Im Lee", code)
        # eine Zahl, eine Quelle: Block 3, Chips, Warnbox, KI-Payload
        nums = lambda s: sorted(set(int(x) for x in re.findall(r"(\d+)(?=[–\s]*(?:\d+\s*)?km/h)", s)))  # noqa: E731
        self.assertEqual(nums(fazit), [22, 34, 55])
        self.assertEqual(nums(code), [22, 34, 55])
        entry = sl._hazards_for_llm(sl.hazard_checks(_wetterlage(tal)))[0]["active"]["FOEHN"]
        self.assertEqual((entry["tal_wind_kmh"], entry["tal_gust_max_kmh"]), ("22-34", 55))
        self.assertEqual(entry["tal_confirmed"], ["Reusstal", "Haslital"])
        self.assertNotIn("lee_gust_kmh", entry)

    def test_unconfirmed_sentence_has_no_number(self):
        tal = sc.foehn_tal_for_day(_series(confirmed=False), DATE, "sued")
        day = _day(tal)
        fazit = day["chain"]["foehn"]["fazit"]
        self.assertIn("bleibt laut Modell in der Höhe", fazit)
        self.assertNotIn("km/h", fazit.split("Startplätze")[0])
        facts = {f["k"]: f["v"] for f in day["chain"]["foehn"]["facts"]}
        self.assertEqual(facts["Föhntäler"], "0/3")
        self.assertNotIn("Böe", facts)
        self.assertIn("Daten zeigen in den Föhntälern keinen Föhnwind.", _foehn_warning(day)["code_text"])
        self.assertEqual(day["chain"]["foehn"]["status"], "warn")      # Pille bleibt orange

    def test_without_series_says_not_verifiable(self):
        day = _day(None)
        self.assertIn("nicht prüfbar", day["chain"]["foehn"]["fazit"])
        facts = {f["k"]: f["v"] for f in day["chain"]["foehn"]["facts"]}
        self.assertEqual(facts["Föhntäler"], "n. prüfbar")
        self.assertNotIn("Föhntälern", _foehn_warning(day)["code_text"])


class TestValidator(unittest.TestCase):
    def setUp(self):
        self.yes = sc.foehn_tal_for_day(_series(), DATE, "sued")
        self.no = sc.foehn_tal_for_day(_series(confirmed=False), DATE, "sued")

    def _kinds(self, text, tal, **kw):
        opts = dict(require_name=True, require_aloft=True, only_foehn_sentences=False)
        opts.update(kw)
        return {k for k, _ in sl._foehn_tal_problems(text, tal, **opts)}

    def test_confirmed_needs_valley_name_and_matching_numbers(self):
        ok = "Moderate south foehn builds over the Northern Alps, gusty in the Reusstal, gusts up to 55 km/h."
        self.assertEqual(self._kinds(ok, self.yes), set())
        self.assertIn("foehn_tal_missing", self._kinds("Moderate south foehn over the Northern Alps.", self.yes))
        self.assertIn("foehn_number_mismatch",
                      self._kinds("South foehn in the Reusstal, gusts up to 45 km/h.", self.yes))

    def test_unconfirmed_must_stay_aloft_and_not_claim_valleys(self):
        self.assertEqual(self._kinds("South foehn stays aloft and does not reach the valleys.", self.no), set())
        kinds = self._kinds("Moderate south foehn, gusty in the valleys.", self.no)
        self.assertIn("foehn_tal_overclaim", kinds)
        self.assertIn("foehn_tal_unconfirmed", kinds)
        self.assertIn("foehn_number_mismatch",
                      self._kinds("South foehn stays aloft, gusts 30 km/h.", self.no))

    def test_day_line_checks_only_foehn_sentences(self):
        line = "Rain from the west with gusts 40 km/h; south foehn stays aloft."
        self.assertEqual(self._kinds(line, self.no, require_name=False, require_aloft=False,
                                     only_foehn_sentences=True), set())

    def test_old_cache_without_tal_adds_nothing(self):
        self.assertEqual(sl._foehn_tal_problems("gusty in the valleys", None, require_name=True,
                                                require_aloft=True, only_foehn_sentences=False), [])

    def test_payload_foehn_block_has_no_tal_details(self):
        out = sl._foehn_for_llm({"per_day": [{"date": DATE, "tal": self.yes}], "decided_by": "x"})
        self.assertNotIn("tal", out["per_day"][0])
        self.assertNotIn("decided_by", out)


class TestSnapshot(unittest.TestCase):
    def test_block_has_verdict_and_raw_hours(self):
        from scripts.snapshot_weather import build_foehn_tal_block
        b = build_foehn_tal_block(_series(), DATE)
        self.assertEqual(b["model"], "meteoswiss_icon_ch2")
        alt = b["punkte"]["alt"]
        self.assertTrue(alt["verdict"]["bestaetigt"])
        self.assertEqual(alt["verdict"]["first_hour"], 11)
        self.assertEqual(sorted(alt["hours"])[0], f"{config.FLIGHT_HOURS_START:02d}:00")
        self.assertEqual(len(alt["hours"]), config.FLIGHT_HOURS_END - config.FLIGHT_HOURS_START)
        self.assertIsNone(build_foehn_tal_block(None, DATE))


if __name__ == "__main__":
    unittest.main()
