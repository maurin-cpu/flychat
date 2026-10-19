"""Vier Föhn-Indikatoren im Briefing (Block 3, 15.10.2026).

Druck, Windkarte (Raster über die Alpenregionen), kühlere Luv-Seite, Täler —
Zählung, Labels und Deutungstext. Kern: Labels und Text aus derselben Quelle,
nie "kein Föhn" als Aussage, keine Wertungswörter.
"""
import re
import unittest

import config
import foehn_indicators as fi
import i18n
from scripts import briefing_v3_context as bc

DATE = "2026-10-15"
TIMES = [f"{DATE}T{h:02d}:00" for h in range(24)]
IDX = [i for i in range(24) if config.FLIGHT_HOURS_START <= i < config.FLIGHT_HOURS_END]


def _station(p_nord, p_sued, t_nord, t_sued, from_h=0):
    """Zürich/Lugano (ICON-D2); vor `from_h` beide Seiten gleich (kein Zeichen)."""
    def ser(v, base):
        return [base if h < from_h else v for h in range(24)]
    return ({"time": TIMES, "model": ["icon_d2"] * 24, "pressure_msl": ser(p_nord, p_nord),
             "temperature_800hPa": ser(t_nord, t_nord)},
            {"time": TIMES, "model": ["icon_d2"] * 24, "pressure_msl": ser(p_sued, p_nord),
             "temperature_800hPa": ser(t_sued, t_nord)})


def _karte(red_regions=(), direction=170.0, n_per_region=4, regions=None, from_h=0):
    """Raster (ICON-CH2): je Region n Punkte; Regionen in red_regions zeigen ab
    `from_h` 35 km/h aus `direction`, die übrigen 10 km/h."""
    regions = regions or [(f"r{i}", f"Region {i}", ("sued", "nord")) for i in range(6)]
    punkte = []
    for rid, name, sides in regions:
        for _ in range(n_per_region):
            strong = [rid in red_regions and h >= from_h for h in range(24)]
            punkte.append({"region_id": rid, "region": name, "sides": sides,
                           "hourly": {"wind_speed_10m": [35.0 if x else 10.0 for x in strong],
                                      "wind_direction_10m": [direction] * 24,
                                      "wind_gusts_10m": [55.0 if x else 20.0 for x in strong]}})
    return {"model": "meteoswiss_icon_ch2", "time": TIMES, "punkte": punkte}


def _taeler(n_on=0, total=23, tal="Reusstal / Urnerland", gust=60, from_h=None):
    rows = [{"tal": tal, "dir_dry": True, "all_gust_max_kmh": gust,
             **({"first_dir_dry_hour": from_h} if from_h is not None else {})}] * n_on
    return {"sued": {"n_total": total, "taeler": rows, "model": "meteoswiss_icon_ch2"}, "nord": None}


class WindKarteTest(unittest.TestCase):
    def test_counts_regions_with_red_share(self):
        out = fi.evaluate_wind_karte(_karte(red_regions=("r0", "r1", "r2")), DATE)
        self.assertTrue(out["on"])
        self.assertEqual((out["side"], out["n"], out["total"]), ("sued", 3, 6))

    def test_below_min_regions_not_on(self):
        out = fi.evaluate_wind_karte(_karte(red_regions=("r0",)), DATE)
        self.assertFalse(out["on"])
        self.assertEqual(out["n"], 1)

    def test_west_wind_never_counts(self):
        out = fi.evaluate_wind_karte(_karte(red_regions=("r0", "r1", "r2", "r3"), direction=270.0), DATE)
        self.assertEqual(out["n"], 0)

    def test_north_wind_only_where_north_foehn_occurs(self):
        regs = [("t", "Tessin", ("nord",)), ("z", "Zentral", ("sued",))]
        out = fi.evaluate_wind_karte(_karte(red_regions=("t", "z"), direction=350.0, regions=regs), DATE)
        self.assertEqual((out["side"], out["n"], out["total"]), ("nord", 1, 1))

    def test_no_data_is_none(self):
        self.assertIsNone(fi.evaluate_wind_karte(None, DATE))

    def test_grid_only_alpine_regions(self):
        pts = fi.karte_punkte()
        self.assertGreater(len(pts), 300)
        import csv
        terrain = {r["id"]: r["terrain_type"] for r in csv.DictReader(
            open(config.FOEHN_TALPUNKTE_PATH.parent / "regionen.csv", encoding="utf-8"))}
        self.assertFalse({p["region_id"] for p in pts if terrain[p["region_id"]] in ("jura", "mittelland")})


class IndikatorenTest(unittest.TestCase):
    def _ind(self, dp=(1013, 1020), t=(0.0, -4.0), red=("r0", "r1", "r2"), val=3, from_h=0, val_h=None):
        nh, sh = _station(dp[0], dp[1], t[0], t[1], from_h=from_h)
        return fi.evaluate_indicators(nh, sh, IDX, _karte(red_regions=red, from_h=from_h), DATE,
                                      _taeler(val, from_h=val_h))

    def test_all_four(self):
        ind = self._ind()
        self.assertEqual(ind["n_on"], 4)
        self.assertEqual(ind["pressure"]["high_side"], "sued")
        self.assertEqual(ind["side"], "sued")
        self.assertEqual(ind["luv_cooler"], {"on": True, "against": False, "cooler_k": 4.0, "side": "sued",
                                             "model": ["icon_d2"], "from_hour": config.FLIGHT_HOURS_START})

    def test_onset_hour_per_indicator(self):
        # wie die Frontzeichen: ab welcher Stunde zeigt jedes Zeichen sich
        ind = self._ind(from_h=11, val_h=13)
        self.assertEqual(ind["pressure"]["from_hour"], 11)
        self.assertEqual(ind["luv_cooler"]["from_hour"], 11)
        self.assertEqual(ind["wind_map"]["from_hour"], 11)
        self.assertEqual(ind["valleys"]["from_hour"], 13)
        self.assertEqual(ind["from_hour"], 11)
        self.assertEqual(ind["wind_map"]["model"], "meteoswiss_icon_ch2")
        self.assertEqual(ind["valleys"]["model"], "meteoswiss_icon_ch2")

    def test_station_models_merged_d2_first(self):
        # fetch_foehn_data: ICON-D2, nach dessen Horizont ICON-EU — Schlüssel ohne Suffix
        raw = {"hourly": {"time": ["t0", "t1"], "pressure_msl_icon_d2": [1010.0, None],
                          "pressure_msl_icon_eu": [1011.0, 1012.0]}}
        h = fi._merge_models(raw)["hourly"]
        self.assertEqual(h["pressure_msl"], [1010.0, 1012.0])
        self.assertEqual(h["model"], ["icon_d2", "icon_eu"])

    def test_signs_of_other_side_count_against_not_for(self):
        # 18.10.2026: Windkarte Süd + Tal, aber Druck und Kälte im Norden
        nh, sh = _station(1019, 1014, -3.0, 0.0)
        ind = fi.evaluate_indicators(nh, sh, IDX, _karte(red_regions=("r0", "r1", "r2")), DATE, _taeler(1))
        self.assertEqual(ind["side"], "sued")            # Gleichstand 2:2 -> der Wind entscheidet
        self.assertEqual(ind["n_on"], 2)
        self.assertTrue(ind["pressure"]["against"])
        self.assertFalse(ind["pressure"]["on"])
        self.assertTrue(ind["luv_cooler"]["against"])
        with i18n.lang_override("en"):
            txt = bc._foehn_indicator_text(ind)
            self.assertNotIn("points to south foehn", txt.lower())
            # Druck steht zuerst und zeigt auf seine Seite; die Zeichen des Tages danach
            self.assertTrue(txt.startswith("In ICON-D2, the pressure difference points to north foehn already at "
                                           "06:00. ICON-CH2 still shows signs of south foehn already at 06:00:"), txt)
            self.assertIn("Against it: a warmer south side aloft (ICON-D2).", txt)

    def test_none(self):
        ind = self._ind(dp=(1015, 1016), t=(0.0, -0.5), red=(), val=0)
        self.assertEqual(ind["n_on"], 0)

    def test_north_side(self):
        nh, sh = _station(1020, 1014, -3.0, 0.0)
        ind = fi.evaluate_indicators(nh, sh, IDX, None, DATE, _taeler(0))
        self.assertEqual(ind["pressure"]["high_side"], "nord")
        self.assertTrue(ind["pressure"]["on"])
        self.assertEqual(ind["luv_cooler"]["side"], "nord")
        self.assertTrue(ind["luv_cooler"]["on"])
        self.assertIsNone(ind["wind_map"])


class BriefingTextTest(unittest.TestCase):
    # Wertungswoerter und die nackte Aussage "kein Foehn" ("no foehn pattern" in den Daten ist erlaubt)
    # ("too weak"/"zu schwach" = Faustregel ueber die Modelle, keine Wertung des Tages)
    WORDS = re.compile(r"(?<!too )\bweak\b|(?<!zu )\bschwach\b|\b(small|klein)\b"
                       r"|\bno foehn\b(?! pattern)|\bkein Föhn\b", re.I)

    def _ind(self, **kw):
        return IndikatorenTest._ind(IndikatorenTest(), **kw)

    def _both(self, ind):
        out = {}
        for lang in ("en", "de"):
            with i18n.lang_override(lang):
                out[lang] = (bc._foehn_indicator_status(ind), bc._foehn_indicator_text(ind))
        return out

    def test_calm_day_never_says_no_foehn(self):
        r = self._both(self._ind(dp=(1015, 1016), t=(0.0, -0.5), red=(), val=0))
        (kind, pill, facts), txt = r["en"]
        self.assertEqual(kind, "neutral")
        self.assertEqual(pill, "Foehn indicators: 0 of 4")
        self.assertIn("Foehn is still possible", txt)
        self.assertNotRegex(txt, r"(?i)\bno foehn\b(?! pattern)")
        self.assertNotRegex(r["de"][1], r"(?i)\bkein Föhn\b")

    def test_local_valley_sign(self):
        r = self._both(self._ind(dp=(1015, 1016), t=(0.0, -0.5), red=(), val=1))
        (kind, pill, facts), txt = r["en"]
        self.assertEqual(kind, "warn")
        self.assertTrue(txt.startswith("In ICON-D2, the pressure difference does not point to foehn. ICON-CH2 still "
                                       "shows a sign of south foehn: dry wind from the foehn direction in Reusstal."), txt)
        self.assertIn("Not in ICON-D2: a cooler south side aloft; not in ICON-CH2: wind from the foehn direction "
                      "in the regions.", txt)
        self.assertIn("Inner-Alpine foehn", txt)

    def test_setup_without_wind(self):
        r = self._both(self._ind(dp=(1013, 1020), t=(0.0, -0.5), red=(), val=0))
        (kind, _, _), txt = r["en"]
        self.assertEqual(kind, "info")
        # Modell statt "in the data", Zeichen beim Namen statt Zahlen (User 17.10.2026)
        self.assertEqual(txt, "In ICON-D2, the pressure difference points to south foehn already at 06:00. "
                              "ICON-CH2 shows none of the signs in the wind. Not in ICON-D2: a cooler south side "
                              "aloft. Models usually show foehn wind too weak.")
        self.assertEqual(r["de"][1], "In ICON-D2 zeigt der Druckunterschied bereits um 06 Uhr auf Südföhn. "
                                     "ICON-CH2 zeigt keines der Zeichen im Wind. Nicht in ICON-D2: kühlere Südseite "
                                     "in der Höhe. Modelle zeigen Föhnwind meist zu schwach.")

    def test_text_has_no_numbers_but_labels_do(self):
        # die Zahlen stehen in den Labels, der Text nennt die Zeichen (wie die Frontzeichen)
        for kw in ({}, dict(red=("r0", "r1", "r2"), val=2, t=(0.0, -0.5), from_h=11, val_h=13),
                   dict(dp=(1015, 1016), t=(0.0, -3.0), red=(), val=0, from_h=9)):
            for lang, ((_, _, facts), txt) in self._both(self._ind(**kw)).items():
                no_clock = re.sub(r"\d{2}(:00| Uhr)|ICON-\w+|Region \d", "", txt)
                self.assertNotRegex(no_clock, r"\d", f"{lang}: {txt}")
                self.assertRegex(facts[0]["v"], r"\d+ hPa")

    def test_all_four_names_strongest_valley(self):
        r = self._both(self._ind())
        (kind, pill, _), txt = r["en"]
        self.assertEqual((kind, pill), ("warn", "Foehn indicators: 4 of 4 · from ~06:00"))
        self.assertTrue(txt.startswith("In ICON-D2, the pressure difference points to south foehn already at 06:00. "
                                       "ICON-D2 shows a matching sign already at 06:00: a cooler south side aloft. "
                                       "ICON-CH2 shows matching signs already at 06:00:"), txt)
        self.assertIn("dry wind from the foehn direction in the valleys (strongest Reusstal)", txt)

    def test_cooler_side_only(self):
        r = self._both(self._ind(dp=(1015, 1016), t=(0.0, -3.0), red=(), val=0, from_h=9))
        self.assertTrue(r["en"][1].startswith("In ICON-D2, the pressure difference does not point to foehn. ICON-D2 "
                                              "still shows a sign of south foehn from about 09:00: a cooler south side "
                                              "aloft. ICON-CH2 shows none of the signs in the wind."), r["en"][1])

    def test_labels_marked_and_same_numbers_as_text(self):
        (kind, pill, facts), txt = self._both(self._ind(val=3))["en"]
        self.assertEqual([f["on"] for f in facts], [True, True, True, True])
        self.assertEqual(facts[0]["v"], "7 hPa (south higher), from ~06:00")
        self.assertEqual(facts[3]["v"], "3 of 23")
        self.assertEqual(facts[3]["k"], "Valleys with dry wind from foehn direction")

    def test_onset_and_models_in_text(self):
        r = self._both(self._ind(red=("r0", "r1", "r2"), val=2, t=(0.0, -0.5), from_h=11, val_h=13))
        (kind, pill, facts), txt = r["en"]
        self.assertEqual(pill, "Foehn indicators: 3 of 4 · from ~11:00")
        self.assertEqual(facts[1]["v"], "3 of 6, from ~11:00")
        # wie die Frontzeichen: Druck zuerst, dann je Modell die Zeichen mit Uhrzeit und Tageszeit
        self.assertEqual(txt, "In ICON-D2, the pressure difference points to south foehn from about 11:00. "
                              "ICON-CH2 shows matching signs from about 11:00: wind from the foehn direction in the "
                              "regions (mainly Region 0 and Region 1) and dry wind from the foehn direction in the "
                              "valleys (strongest Reusstal) around midday. Not in ICON-D2: a cooler south side aloft.")
        self.assertEqual(r["de"][1], "In ICON-D2 zeigt der Druckunterschied ab etwa 11 Uhr auf Südföhn. ICON-CH2 "
                                     "zeigt passende Zeichen ab etwa 11 Uhr: um die Mittagszeit Wind aus Föhnrichtung "
                                     "in den Regionen (vor allem Region 0 und Region 1) und trockener Wind aus "
                                     "Föhnrichtung in den Tälern (am stärksten Reusstal). Nicht in ICON-D2: kühlere "
                                     "Südseite in der Höhe.")

    def test_signs_sorted_by_time(self):
        # Täler am frühen Morgen vor der Windkarte am Vormittag
        txt = self._both(self._ind(red=("r0", "r1", "r2"), val=2, t=(0.0, -0.5), from_h=11, val_h=7))["en"][1]
        self.assertIn("ICON-CH2 shows matching signs from about 07:00: dry wind from the foehn direction in the "
                      "valleys (strongest Reusstal) in the early morning and wind from the foehn direction in the "
                      "regions (mainly Region 0 and Region 1) around midday.", txt)

    def test_no_judgement_words(self):
        cases = [self._ind(), self._ind(dp=(1015, 1016), t=(0.0, -0.5), red=(), val=0),
                 self._ind(dp=(1015, 1016), t=(0.0, -0.5), red=(), val=1),
                 self._ind(dp=(1013, 1020), t=(0.0, -0.5), red=(), val=0),
                 self._ind(dp=(1015, 1016), t=(0.0, -0.5), red=("r0", "r1", "r2"), val=0)]
        for ind in cases:
            for lang, (_, txt) in self._both(ind).items():
                self.assertNotRegex(txt, self.WORDS, f"{lang}: {txt}")


class ErklaerseiteTest(unittest.TestCase):
    def test_page_renders_both_languages_with_constants(self):
        from web import app
        c = app.test_client()
        en = c.get("/foehn?lang=en")
        de = c.get("/foehn?lang=de")
        self.assertEqual((en.status_code, de.status_code), (200, 200))
        self.assertIn(f"from {fi.KARTE_WIND_KMH} km/h", en.get_data(as_text=True))
        self.assertIn(f"ab {fi.KARTE_WIND_KMH} km/h", de.get_data(as_text=True))
        self.assertIn("so zählen wir", de.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
