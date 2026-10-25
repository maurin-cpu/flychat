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
        # zwei Modelle wie bei Open-Meteo: ICON-CH1 bis Mittag, danach ICON-CH2
        r.json.return_value = [{"hourly": {"time": TIMES,
                                           "wind_speed_10m_meteoswiss_icon_ch1": [1.0] * 12 + [None] * 12,
                                           "wind_speed_10m_meteoswiss_icon_ch2": [2.0] * 24}}] * n
        return r

    def test_fetch_maps_points_by_id(self):
        n = len(ft.load_talpunkte())
        with mock.patch("foehn_talpunkte.requests.get", return_value=self._resp(n)):
            d = ft.fetch_talpunkt_wind(1)
        self.assertEqual(len(d["punkte"]), n)
        self.assertEqual(d["model"], [config.SURFACE_PRIMARY_MODEL] * 12 + [config.SURFACE_SECONDARY_MODEL] * 12)
        self.assertEqual(d["punkte"]["alt"]["hourly"]["wind_speed_10m"], [1.0] * 12 + [2.0] * 12)
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
        # Warnung nur noch als Label (25.10.2026): die Zahlen stehen allein in Block 3
        self.assertEqual(set(_foehn_warning(day)), {"topic", "label", "severity", "sev_label", "short", "sev_short", "block", "block_label"})
        # eine Zahl, eine Quelle: Block 3 und Chips
        nums = lambda s: sorted(set(int(x) for x in re.findall(r"(\d+)(?=[–\s]*(?:\d+\s*)?km/h)", s)))  # noqa: E731
        self.assertEqual(nums(fazit), [22, 34, 55])

    def test_unconfirmed_names_valley_wind_never_no_foehn(self):
        # User 12.10.2026: nie "kein Foehn(wind)" — Windstaerke im Tal nennen,
        # bei schwachem Wind "deutet nicht auf Foehn hin".
        tal = sc.foehn_tal_for_day(_series(confirmed=False), DATE, "sued")
        day = _day(tal)
        fazit = day["chain"]["foehn"]["fazit"]
        tal_txt = ("In den 3 Föhntälern zeigt ICON-CH2 Wind bis 8 km/h, Böen bis 15 km/h (Reusstal)"
                   " — die Windstärke deutet am Talboden nicht auf Föhn hin.")
        self.assertIn(tal_txt, fazit)
        self.assertIn("In der Höhe können die Daten trotzdem auf Föhn hindeuten", fazit)
        self.assertNotIn("keinen Föhn", fazit)
        facts = {f["k"]: f["v"] for f in day["chain"]["foehn"]["facts"]}
        self.assertEqual(facts["Föhntäler"], "0/3")
        self.assertNotIn("Böe", facts)
        self.assertEqual(_foehn_warning(day)["label"], "Föhn")
        self.assertEqual(day["chain"]["foehn"]["status"], "warn")      # Pille bleibt orange

    def test_unconfirmed_strong_wind_is_not_called_weak(self):
        series = _series(confirmed=False)
        series["punkte"]["alt"]["hourly"] = _hourly(wind=35.0, gust=60.0, direction=300.0)
        tal = sc.foehn_tal_for_day(series, DATE, "sued")
        fazit = _day(tal)["chain"]["foehn"]["fazit"]
        self.assertIn("Wind bis 35 km/h, Böen bis 60 km/h (Reusstal)", fazit)
        self.assertIn("nicht das typische Föhnmuster", fazit)
        self.assertNotIn("Windstärke deutet", fazit)

    def test_without_series_says_not_verifiable(self):
        day = _day(None)
        self.assertIn("nicht prüfbar", day["chain"]["foehn"]["fazit"])
        facts = {f["k"]: f["v"] for f in day["chain"]["foehn"]["facts"]}
        self.assertEqual(facts["Föhntäler"], "n. prüfbar")
        self.assertNotIn("code_text", _foehn_warning(day))


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


class TestTalmerkmaleBriefing(unittest.TestCase):
    """Föhn-Block nach Talmerkmalen (14.10.2026): beide Seiten jeden Tag,
    Richtung + Wind + Feuchte, Druck nur als Zahl, nie ein Urteil."""

    def setUp(self):
        self._lang = config.LANG
        config.LANG = "en"

    def tearDown(self):
        config.LANG = self._lang

    def _fo(self, series, dp=2.0):
        return {"claim": {"delta_p_sued_max_hpa": dp, "delta_p_nord_max_hpa": 1.0},
                "taeler": {s: sc.foehn_tal_for_day(series, DATE, s) for s in ("sued", "nord")}}

    def test_humidity_and_direction_dry_are_counted(self):
        r = fi.evaluate_talpunkt(_hourly(foehn_hours=(11, 12), fw=(14, 15), fg=(23, 24)),
                                 list(range(10, 17)), "Süd")
        self.assertFalse(r["bestaetigt"])          # zu schwach fuer alle drei Merkmale
        self.assertTrue(r["dir_dry"])              # aber Foehnrichtung + trocken + Wind knapp darunter
        self.assertEqual(r["rh_min_pct"], 38)

    def test_weak_dry_breeze_in_sector_is_not_counted(self):
        # Vorschau 14.10.: trockene Talbrise um 10 km/h im 180°-Sektor = kein Merkmal
        r = fi.evaluate_talpunkt(_hourly(foehn_hours=(11, 12, 13), fw=(9, 10, 10), fg=(15, 16, 16)),
                                 list(range(10, 17)), "Süd")
        self.assertFalse(r["dir_dry"])

    def test_valleys_are_checked_without_pressure_index(self):
        # Druck 2 hPa, trotzdem bestaetigte Taeler -> Block nennt sie
        text = bc._foehn_valley_fazit(self._fo(_series(True)), {})
        self.assertIn("dry wind from the foehn direction in 2 of 3 valleys", text)
        self.assertNotIn("hPa", text)          # Druck nur als Kennzahl
        self.assertNotRegex(text, r"(?i)threshold|no signs|no foehn\b")
        kind, label, facts = bc._foehn_valley_status(self._fo(_series(True)), {})
        self.assertEqual(kind, "warn")
        self.assertIn("valleys", label)

    def test_calm_valleys_with_strong_wind_aloft_name_the_pattern(self):
        fo = self._fo(_series(False))
        fo["taeler"]["nord"] = None                 # nur Nordseite mit Daten, ruhig
        fo["taeler"]["nord"] = sc.foehn_tal_for_day(
            {"model": "meteoswiss_icon_ch2", "time": TIMES,
             "punkte": {"pio": {"meta": {"id": "pio", "tal": "Leventina", "station": "Piotta",
                                         "region_id": "leventina_blenio", "foehn_typ": "Nord"},
                                "hourly": _hourly()}}}, DATE, "nord")
        sw = {"max_gust_kmh": 81, "dir_deg": 0, "spot": "Cari", "elevation_m": 2293, "hour": 9}
        text = bc._foehn_valley_fazit(fo, sw)
        self.assertIn("Valleys: no dry wind from the foehn direction", text)
        self.assertIn("gusts up to 81 km/h from the north", text)
        self.assertIn("over a cold-air pool", bc._foehn_valley_reading(fo, sw))
        self.assertNotIn("cold-air pool", text)   # Deutung nur in der Einordnung
        kind, label, _ = bc._foehn_valley_status(fo, sw)
        self.assertEqual((kind, label), ("info", "Wind aloft 81 km/h"))

    def test_quiet_day_states_numbers_not_verdict(self):
        fo = self._fo(_series(False))
        fo["taeler"]["nord"] = None
        text = bc._foehn_valley_fazit(fo, {"max_gust_kmh": 20})
        self.assertIn("no dry wind from the foehn direction in the 3 valleys", text)
        self.assertNotRegex(text, r"(?i)no signs of foehn|without signs|threshold")

    def test_old_cache_without_taeler_keeps_legacy_text(self):
        fo = {"claim": {"delta_p_sued_max_hpa": 2.0}, "sued_active": False}
        wl = {"foehn": {"per_day": [dict(fo, date=DATE)]}}
        self.assertIn("pressure difference", bc._foehn_fazit(wl, DATE))


class TestEinordnung(unittest.TestCase):
    """Einordnung: ein fester Satz je Datenlage, immer mit Grenze, nie Urteil."""

    def setUp(self):
        self._lang = config.LANG
        config.LANG = "en"

    def tearDown(self):
        config.LANG = self._lang

    def _fo(self, confirmed, dp=2.0):
        return {"claim": {"delta_p_sued_max_hpa": dp},
                "taeler": {"sued": sc.foehn_tal_for_day(_series(confirmed), DATE, "sued"), "nord": None}}

    def test_each_case_has_its_sentence(self):
        self.assertIn("features MeteoSwiss uses", bc._foehn_valley_reading(self._fo(True), {}))
        self.assertIn("indicators in the valleys show no foehn signal", bc._foehn_valley_reading(self._fo(False), {}))
        self.assertIn("pressure difference this large", bc._foehn_valley_reading(self._fo(False, dp=9), {}))

    def test_calm_day_names_the_limit_never_gives_all_clear(self):
        text = bc._foehn_valley_reading(self._fo(False), {})
        self.assertIn("model forecast", text)
        self.assertIn("inner-Alpine", text)
        self.assertNotRegex(text, r"(?i)no foehn|safe|no risk")

    def test_both_languages_carry_every_sentence(self):
        for key in ("fvr_quiet", "fvr_pool", "fvr_dirdry", "fvr_full", "fvr_dp_high", "fvr_guide"):
            for lang in ("de", "en"):
                config.LANG = lang
                self.assertNotEqual(bc._lbl(key), key, (key, lang))


class TestRuhigerTag(unittest.TestCase):
    """Recherche 14.10.2026: kein Anbieter schreibt 'kein Foehn' in Prognosen,
    der SHV nennt Schweigen bei seichtem Foehn als Unfallmuster -> ruhiger Tag
    = neutrale Pille, Indikatoren + Grenze + Live-Werte, nie Entwarnung."""

    def setUp(self):
        self._lang = config.LANG
        config.LANG = "de"

    def tearDown(self):
        config.LANG = self._lang

    def test_quiet_day_is_neutral_not_green(self):
        fo = {"claim": {"delta_p_sued_max_hpa": 2.0},
              "taeler": {"sued": sc.foehn_tal_for_day(_series(False), DATE, "sued"), "nord": None}}
        kind, label, _ = bc._foehn_valley_status(fo, {})
        self.assertEqual(kind, "neutral")
        text = bc._foehn_valley_reading(fo, {})
        self.assertIn("Seichter Föhn wird von Modellen oft nicht erfasst", text)
        self.assertIn("Live-Werte", text)
        self.assertNotRegex(text, r"kein Föhn")


class TestRichtung(unittest.TestCase):
    """14.10.2026: Hoehe SO–SW / NW–NO = Foehnrichtung (User-Regel, Guetsch-Messung);
    Ost/West nur als Wind. Taeler: gemessene Richtung je Tal, im Text genannt."""

    def setUp(self):
        self._lang = config.LANG
        config.LANG = "en"

    def tearDown(self):
        config.LANG = self._lang

    def _quiet(self):
        return {"claim": {"delta_p_sued_max_hpa": 2.0},
                "taeler": {"sued": sc.foehn_tal_for_day(_series(False), DATE, "sued"),
                           "nord": sc.foehn_tal_for_day(_series(False), DATE, "nord")}}

    def test_west_wind_aloft_is_only_wind(self):
        fo = self._quiet()
        fo["taeler"]["nord"]["n_dir_dry"] = 0
        fo["taeler"]["nord"]["n_bestaetigt"] = 0
        sw = {"max_gust_kmh": 70, "dir_deg": 270, "spot": "Piz X", "elevation_m": 2900, "hour": 9}
        self.assertIn("from the west", bc._foehn_valley_fazit(fo, sw))
        self.assertNotIn("cold-air pool", bc._foehn_valley_reading(fo, sw))
        kind, label, _ = bc._foehn_valley_status(fo, sw)
        self.assertNotIn("aloft", label)

    def test_aloft_sectors_follow_user_rule(self):
        self.assertEqual(bc._aloft_foehn_side({"dir_deg": 140}), "sued")
        self.assertEqual(bc._aloft_foehn_side({"dir_deg": 220}), "sued")
        self.assertEqual(bc._aloft_foehn_side({"dir_deg": 320}), "nord")
        self.assertEqual(bc._aloft_foehn_side({"dir_deg": 40}), "nord")
        self.assertIsNone(bc._aloft_foehn_side({"dir_deg": 270}))
        self.assertIsNone(bc._aloft_foehn_side({"dir_deg": 90}))

    def test_valley_named_with_its_direction(self):
        fo = {"claim": {"delta_p_sued_max_hpa": 6.0},
              "taeler": {"sued": sc.foehn_tal_for_day(_series(True), DATE, "sued"), "nord": None}}
        text = bc._foehn_valley_fazit(fo, {})
        self.assertRegex(text, r"Reusstal from S")
        self.assertIn("South side valleys: no valley data — not verifiable.", text)

    def test_measured_sector_overrides_half_circle(self):
        # Leventina: Foehn aus West (Talachse) — Halbkreis 270–90 haette 255° verpasst
        h = _hourly(foehn_hours=(11, 12, 13), fw=(25, 28, 30), fg=(45, 50, 52), fdir=255.0, frh=40.0)
        r_alt = fi.evaluate_talpunkt(h, list(range(10, 17)), "Nord")
        r_neu = fi.evaluate_talpunkt(h, list(range(10, 17)), "Nord", sektor=[225, 10])
        self.assertFalse(r_alt["bestaetigt"])
        self.assertTrue(r_neu["bestaetigt"])
        self.assertAlmostEqual(r_neu["foehn_dir_deg"], 255, delta=1)


class TestFoehnRichter(unittest.TestCase):
    """scripts/validate_foehn_daily: Wahrheit je Stunde und Urteil je Tal."""

    def test_wahrheit_counts_foehn_and_mixed_hours(self):
        from scripts import validate_foehn_daily as v
        idx = {12: ["2"] * 6, 13: ["2", "2", "2", "0", "0", "0"], 14: ["1"] * 6, 15: ["2", "2", "0", "0", "0", "0"]}
        w = v._wahrheit(idx)
        self.assertEqual(w["foehn_std"], [12, 13])
        self.assertEqual(w["misch_std"], [14])

    def test_urteil(self):
        from scripts import validate_foehn_daily as v
        f = {"foehn_std": [12, 13], "misch_std": []}
        m = {"foehn_std": [], "misch_std": [12, 13]}
        q = {"foehn_std": [12], "misch_std": []}
        self.assertEqual(v._urteil(True, f), "treffer")
        self.assertEqual(v._urteil(False, f), "verpasst")
        self.assertEqual(v._urteil(True, m), "mischluft")
        self.assertEqual(v._urteil(True, q), "fehlalarm")
        self.assertEqual(v._urteil(False, q), "still")


class TestLegende(unittest.TestCase):
    """Legende: wann ein Tal zaehlt — Zahlen aus den Konstanten der Regel."""

    def test_legend_numbers_come_from_the_rule(self):
        config_lang = config.LANG
        config.LANG = "en"
        try:
            fo = {"taeler": {"sued": sc.foehn_tal_for_day(_series(False), DATE, "sued"), "nord": None}}
            text = bc._foehn_legend(fo)
            self.assertIn(f"from {fi.TAL_WIND_WEAK_KMH} km/h", text)
            self.assertIn(f"gusts from {fi.TAL_GUST_WEAK_KMH} km/h", text)
            self.assertIn(f"at most {fi.TAL_RH_WEAK} %", text)
            self.assertIn(f"at least {fi.TAL_MIN_HOURS} hours", text)
            self.assertEqual(bc._foehn_legend({"taeler": {"sued": None, "nord": None}}), "")
        finally:
            config.LANG = config_lang


class TestWarnungAusTaelern(unittest.TestCase):
    """14.10.2026: Foehn-Warnung auch ohne Druckschwelle, wenn Taeler trockenen
    Wind aus Foehnrichtung zeigen (Blog-Fall 26.08.: 3 hPa, Foehn in Andeer)."""

    def setUp(self):
        self._lang = config.LANG
        config.LANG = "en"

    def tearDown(self):
        config.LANG = self._lang

    def _wl(self):
        wl = _wetterlage(None)
        d = wl["foehn"]["per_day"][0]
        d.update(sued_active=False, peak_sued="none", sued_hours=0, claim={"delta_p_sued_max_hpa": 3.0})
        d["taeler"] = {"sued": sc.foehn_tal_for_day(_series(True), DATE, "sued"), "nord": None}
        return wl

    def test_valley_signs_activate_the_warning(self):
        chk = sl.hazard_checks(self._wl())[0]["checks"]["FOEHN"]
        self.assertTrue(chk["active"])
        self.assertEqual(chk["facts"]["side"], "sued")
        self.assertIsNone(chk["facts"]["tal"])              # KI-Validator: keine Talzahl-Pflicht
        self.assertEqual(chk["facts"]["valley_signs"]["n"], 2)

    def test_warning_label_for_valley_signs(self):
        day = bc.build_chain_all_days(self._wl(), [DATE])["by_date"][DATE]
        self.assertEqual(_foehn_warning(day)["label"], "Foehn")

    def test_no_valley_signs_no_warning(self):
        wl = self._wl()
        wl["foehn"]["per_day"][0]["taeler"] = {"sued": sc.foehn_tal_for_day(_series(False), DATE, "sued"), "nord": None}
        self.assertFalse(sl.hazard_checks(wl)[0]["checks"]["FOEHN"]["active"])
