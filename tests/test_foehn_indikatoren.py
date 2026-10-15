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


def _station(p_nord, p_sued, t_nord, t_sued):
    return ({"time": TIMES, "pressure_msl": [p_nord] * 24, "temperature_800hPa": [t_nord] * 24},
            {"time": TIMES, "pressure_msl": [p_sued] * 24, "temperature_800hPa": [t_sued] * 24})


def _karte(red_regions=(), direction=170.0, n_per_region=4, regions=None):
    """Raster: je Region n Punkte; Regionen in red_regions zeigen den ganzen Tag
    35 km/h aus `direction`, die übrigen 10 km/h."""
    regions = regions or [(f"r{i}", f"Region {i}", ("sued", "nord")) for i in range(6)]
    punkte = []
    for rid, name, sides in regions:
        for _ in range(n_per_region):
            strong = rid in red_regions
            punkte.append({"region_id": rid, "region": name, "sides": sides,
                           "hourly": {"wind_speed_10m": [35.0 if strong else 10.0] * 24,
                                      "wind_direction_10m": [direction] * 24,
                                      "wind_gusts_10m": [55.0 if strong else 20.0] * 24}})
    return {"time": TIMES, "punkte": punkte}


def _taeler(n_on=0, total=23, tal="Reusstal / Urnerland", gust=60):
    rows = [{"tal": tal, "dir_dry": True, "all_gust_max_kmh": gust}] * n_on
    return {"sued": {"n_total": total, "taeler": rows}, "nord": None}


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
    def _ind(self, dp=(1013, 1020), t=(0.0, -4.0), red=("r0", "r1", "r2"), val=3):
        nh, sh = _station(dp[0], dp[1], t[0], t[1])
        return fi.evaluate_indicators(nh, sh, IDX, _karte(red_regions=red), DATE, _taeler(val))

    def test_all_four(self):
        ind = self._ind()
        self.assertEqual(ind["n_on"], 4)
        self.assertEqual(ind["pressure"]["high_side"], "sued")
        self.assertEqual(ind["luv_cooler"], {"on": True, "cooler_k": 4.0, "side": "sued"})

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
        self.assertIn("shallow foehn is often missed", txt)
        self.assertNotRegex(txt, r"(?i)\bno foehn\b(?! pattern)")
        self.assertNotRegex(r["de"][1], r"(?i)\bkein Föhn\b")

    def test_local_valley_sign(self):
        r = self._both(self._ind(dp=(1015, 1016), t=(0.0, -0.5), red=(), val=1))
        (kind, pill, facts), txt = r["en"]
        self.assertEqual(kind, "warn")
        self.assertTrue(txt.startswith("Only a local sign: Reusstal shows dry wind"))
        self.assertIn("from 4 hPa", txt)
        self.assertIn("Inner-Alpine foehn", txt)

    def test_setup_without_wind(self):
        r = self._both(self._ind(dp=(1013, 1020), t=(0.0, -0.5), red=(), val=0))
        (kind, _, _), txt = r["en"]
        self.assertEqual(kind, "info")
        self.assertTrue(txt.startswith("The pressure difference points to south foehn"))
        self.assertIn("Rule of thumb", txt)

    def test_all_four_names_strongest_valley(self):
        r = self._both(self._ind())
        (kind, pill, _), txt = r["en"]
        self.assertEqual((kind, pill), ("warn", "Foehn indicators: 4 of 4"))
        self.assertTrue(txt.startswith("All four foehn signs agree and point to south foehn"))
        self.assertIn("Reusstal (gusts up to 60 km/h)", txt)

    def test_labels_marked_and_same_numbers_as_text(self):
        (kind, pill, facts), txt = self._both(self._ind(val=3))["en"]
        self.assertEqual([f["on"] for f in facts], [True, True, True, True])
        self.assertEqual(facts[0]["v"], "7 hPa (south higher)")
        self.assertEqual(facts[3]["v"], "3/23 valleys")
        self.assertIn("in 3 valleys", txt)

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
