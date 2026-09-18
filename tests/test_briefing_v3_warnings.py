"""Tests fuer die Code-Zeile der Warnungen im Briefing v3.

Die Code-Zeile steht unter jedem KI-Satz und muss auch ohne KI stimmen:
Worte statt Rohwerte, Zeitfenster konsolidiert, kein Abschnitt verschluckt.
"""
import unittest

import config
from engine.synoptic_llm import _day_shape
from scripts import briefing_v3_context as bc

FULL = ["morning", "midday", "afternoon", "evening"]


class _De(unittest.TestCase):
    def setUp(self):
        self._lang = config.LANG
        config.LANG = "de"

    def tearDown(self):
        config.LANG = self._lang


class TestRuns(unittest.TestCase):
    def test_gap_splits_into_runs(self):
        self.assertEqual(bc._runs(["morning", "afternoon", "evening"]),
                         [["morning"], ["afternoon", "evening"]])

    def test_order_is_normalised(self):
        self.assertEqual(bc._runs(["evening", "morning"]),
                         [["morning"], ["evening"]])


class TestShapePhrase(_De):
    def test_wechselnd_keeps_the_afternoon(self):
        """Vorfall 16.09.2026: 'morgens und wieder abends' verschluckte den
        Nachmittag."""
        sh = _day_shape({"wallis": ["morning", "afternoon", "evening"]})
        self.assertEqual(bc._shape_phrase(sh), "am Vormittag und wieder ab Nachmittag")

    def test_two_single_windows(self):
        sh = _day_shape({"wallis": ["morning", "evening"]})
        self.assertEqual(bc._shape_phrase(sh), "am Vormittag und wieder am Abend")


class TestWindowsText(_De):
    def _text(self, wins):
        return bc._hazard_windows_text({"facts": {"windows": wins,
                                                  "day_shape": _day_shape(wins)}})

    def test_common_course_has_no_place(self):
        wins = {"alpennordhang": ["afternoon", "evening"],
                "tessin": ["afternoon", "evening"]}
        self.assertEqual(self._text(wins), "Ab Nachmittag.")

    def test_two_groups_both_named(self):
        wins = {"alpennordhang": FULL,
                "wallis": ["morning", "afternoon", "evening"],
                "graubuenden_engadin": ["morning", "afternoon", "evening"]}
        text = self._text(wins)
        self.assertIn("im Wallis und in Graubünden", text)
        self.assertIn("am Alpennordhang", text)
        self.assertNotIn("ganztägig.", text.split(",")[0])

    def test_three_groups_name_the_earliest_onset_only(self):
        wins = {"alpennordhang": FULL,
                "wallis": ["morning", "afternoon", "evening"],
                "tessin": ["afternoon", "evening"],
                "graubuenden_engadin": ["midday", "afternoon", "evening"]}
        text = self._text(wins)
        self.assertTrue(text.startswith("Zeitlich gestaffelt: ab Vormittag"))
        self.assertNotIn("ganztägig", text)


class TestCodeLineWithKi(_De):
    """Mit KI-Satz keine Zeiten in der Code-Zeile — sonst stehen sie doppelt."""
    CHECK = {"zones": ["tessin"], "facts": {
        "side": "nord", "peak": "caution", "hours": 6,
        "windows": {"tessin": ["afternoon", "evening"]},
        "day_shape": _day_shape({"tessin": ["afternoon", "evening"]}),
        "course": "zunehmend", "lee_gust_kmh": 55}}

    def test_with_timing(self):
        text = bc._hazard_code_text("FOEHN", self.CHECK)
        self.assertIn("Ab Nachmittag", text)
        self.assertIn("Legt im Tagesverlauf zu", text)
        self.assertIn("55 km/h", text)

    def test_without_timing_keeps_the_numbers(self):
        text = bc._hazard_code_text("FOEHN", self.CHECK, timing=False)
        self.assertNotIn("Ab Nachmittag", text)
        self.assertNotIn("Legt im Tagesverlauf zu", text)
        self.assertIn("55 km/h", text)
        self.assertIn("Nordf\u00f6hn", text)


class TestWindCodeLine(_De):
    def test_no_second_upper_wind_number(self):
        """Nur eine Hoehenwind-Spitze auf der Seite — die im Hoehenwind-Abschnitt."""
        text = bc._hazard_code_text("WIND", {"zones": ["alpennordhang", "wallis"], "facts": {
            "classes": {"alpennordhang": "verblasen", "wallis": "stark_eingeschraenkt"},
            "median_aloft_kmh": 32}}, timing=False)
        self.assertEqual(text, "Verblasen am Alpennordhang, stark eingeschr\u00e4nkt im Wallis.")
        self.assertNotIn("km/h", text)


class TestWords(_De):
    def test_extent(self):
        self.assertEqual(bc._extent_word(0.93), "verbreitet")
        self.assertEqual(bc._extent_word(0.4), "gebietsweise")
        self.assertEqual(bc._extent_word(0.1), "vereinzelt")

    def test_rain_intensity(self):
        self.assertEqual(bc._rain_word(28.3), "kräftig, lokal mit Starkregen")
        self.assertEqual(bc._rain_word(5), "kräftig")
        self.assertEqual(bc._rain_word(0.4), "leicht")


def _wl(dates, active_by_day):
    """Minimales Strukturfeld: je Tag die aktiven Gefahren als Regen/Wind-Schalter."""
    zones = list(config.SYNOPTIC_ZONES)
    precip, wind = [], []
    for d, active in zip(dates, active_by_day):
        precip.append({"date": d, "zones": {z: {"day": {
            "wet_share": 0.6 if "RAIN" in active else 0.0, "p90_mm": 2.0,
            "gewitter_share": 0.2 if "THUNDER" in active else 0.0}} for z in zones}})
        wind.append({"date": d, "zones": {z: {
            "wind_class": "verblasen" if "WIND" in active else "unauffaellig"}
            for z in zones}})
    return {"forecast_dates": list(dates), "precip_zones": {"per_day": precip},
            "wind_zones": {"per_day": wind}}


class TestDaySummary(_De):
    """Entscheid 1: Tagessatz fasst zusammen, faellt nie ein Urteil."""
    DATES = ("2026-09-16", "2026-09-17", "2026-09-18")

    def test_rain_and_wind(self):
        out = bc._day_summaries(_wl(self.DATES, [{"RAIN", "WIND"}, set(), {"THUNDER"}]),
                                list(self.DATES))
        self.assertEqual(out["2026-09-16"], "Regen und starker Wind erschweren das Fliegen.")
        self.assertEqual(out["2026-09-17"], "Keine gr\u00f6sseren Wettergefahren.")
        self.assertEqual(out["2026-09-18"], "Gewitter erschweren das Fliegen.")

    def test_never_a_verdict(self):
        out = bc._day_summaries(_wl(self.DATES, [{"RAIN", "WIND"}, set(), {"RAIN"}]),
                                list(self.DATES))
        for text in out.values():
            for verdict in ("Fenster", "fliegbar", "Top", "kein nutzbar", "unm\u00f6glich"):
                self.assertNotIn(verdict, text)


class TestChipText(_De):
    """Entscheid 4: Warn-Chips in Klartext."""

    def test_clouds(self):
        self.assertEqual(bc._chip_text({"topic": "CLOUDS", "severity": "stop",
                                        "value": "Base 1400m \u2264 region ref 1500m"}),
                         "Wolken bis auf Starth\u00f6he")

    def test_rain_classes_in_both_cache_languages(self):
        for value, expected in (("widespread", "Fl\u00e4chiger Regen"),
                                ("flaechig", "Fl\u00e4chiger Regen"),
                                ("isolated", "Einzelne Schauer"),
                                ("Precipitation", "Regen")):
            self.assertEqual(bc._chip_text({"topic": "RAIN", "severity": "stop",
                                            "value": value}), expected)

    def test_upper_wind_uses_the_thresholds(self):
        self.assertEqual(bc._chip_text({"topic": "WIND_ALOFT", "severity": "stop",
                                        "value": ">30 km/h"}),
                         f"Starker H\u00f6henwind \u00fcber {config.WIND_DANGER_KMH} km/h")

    def test_thunder_risk_keeps_the_percentage(self):
        self.assertEqual(bc._chip_text({"topic": "THUNDERSTORM", "severity": "warn",
                                        "value": "Storm risk 30%"}),
                         "Gewitterrisiko 30 %")

    def test_unknown_topic_falls_back(self):
        self.assertEqual(bc._chip_text({"topic": "TURBULENCE", "severity": "warn",
                                        "label": "Chop", "value": "rough"}), "Chop rough")


class TestFirstSentences(unittest.TestCase):
    """Entscheid 7: nie mitten im Wort schneiden."""

    def test_long_first_sentence_stays_whole(self):
        text = ("A scratchy thermal day with very limited potential. The only productive "
                "window is around midday (11:00-13:00), where a weak peak of 1.3 m/s may "
                "develop before the wind picks up.")
        out = bc._first_sentences(text, 150)
        self.assertEqual(out, "A scratchy thermal day with very limited potential.")

    def test_no_word_is_cut(self):
        text = ("The only productive window is around midday (11:00-13:00), where a weak "
                "peak of 1.3 m/s may develop before the wind picks up and the rain from "
                "the west reaches the region in the early afternoon hours, which ends the "
                "day for most pilots and leaves only short glides from the lower launches")
        out = bc._first_sentences(text, 150)
        self.assertTrue(out.endswith("\u2026"))
        self.assertIn(out[:-1].split()[-1], text.split())


def _day(regions):
    """raw_day mit top_regions: [(region_id, band, rating)]."""
    return {"top_regions": [{"region_id": rid, "safety_band": band,
                             "experience_rating": rating}
                            for rid, band, rating in regions]}


class TestDayVerdict(unittest.TestCase):
    """Entscheid 16.09.2026: der Tag wird aus den Regionen bewertet (Regel B)."""
    IDS = [f"r{i}" for i in range(10)]

    def _verdict(self, spec):
        return bc._day_verdict(_day([(f"r{i}", b, r) for i, (b, r) in enumerate(spec)]),
                               self.IDS)

    def test_wednesday_majority_not_safe(self):
        """Mi 16.09.: 8 Not safe, 2 Caution — der beste Spot hiess 'Caution 3/5'."""
        v = self._verdict([("red", 1)] * 8 + [("amber", 2), ("amber", 3)])
        self.assertEqual((v["tier"], v["rating"]), ("not_safe", 1))

    def test_thursday_majority_safe(self):
        v = self._verdict([("green", 3)] * 3 + [("green", 2)] * 5 + [("amber", 2)] * 2)
        self.assertEqual((v["tier"], v["rating"]), ("green", 2))

    def test_exactly_half_not_safe_is_caution(self):
        """'Mehr als die Haelfte' — genau die Haelfte ist noch nicht Not safe."""
        v = self._verdict([("red", 1)] * 5 + [("amber", 3)] * 5)
        self.assertEqual(v["tier"], "conditional")

    def test_exactly_half_safe_is_safe(self):
        v = self._verdict([("green", 3)] * 5 + [("amber", 2)] * 5)
        self.assertEqual(v["tier"], "green")

    def test_mean_rating_rounds_half_up(self):
        v = self._verdict([("green", 2), ("green", 3)])      # 2.5
        self.assertEqual(v["rating"], 3)

    def test_regions_without_rating_are_ignored(self):
        v = bc._day_verdict(_day([("r0", "green", 4), ("r1", "no_data", 0)]), ["r0", "r1", "r2"])
        self.assertEqual((v["tier"], v["rating"], v["n"]), ("green", 4, 1))

    def test_no_rated_region_is_unknown(self):
        self.assertEqual(bc._day_verdict(_day([]), self.IDS)["tier"], "unknown")


class TestLageLabel(unittest.TestCase):
    """Entscheid 5: deutsches Lage-Label in der englischen Mail uebersetzen."""

    def test_center_names_follow_the_mail_language(self):
        lang = config.LANG
        config.LANG = "en"
        try:
            self.assertEqual(bc._center_name("Atlantik vor Irland"), "Atlantic off Ireland")
            self.assertEqual(bc._center_name("Unbekannt"), "Unbekannt")
        finally:
            config.LANG = lang

    def test_every_grid_label_is_translated(self):
        """Neue Punkte in config.EUROPE_PRESSURE_GRID brauchen eine Uebersetzung."""
        lang = config.LANG
        config.LANG = "en"
        try:
            for point in config.EUROPE_PRESSURE_GRID:
                self.assertNotEqual(bc._lbl("ctr_" + point["label"]),
                                    "ctr_" + point["label"], point["label"])
        finally:
            config.LANG = lang

    def test_english_label(self):
        lang = config.LANG
        config.LANG = "en"
        try:
            self.assertEqual(bc._lbl("lage_Nordfoehnlage"), "North foehn")
        finally:
            config.LANG = lang


if __name__ == "__main__":
    unittest.main()
