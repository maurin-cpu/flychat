# -*- coding: utf-8 -*-
"""Tageskachel-Hoehenwind (05.11.2026): Richtung je Region, "Schwacher Wind ·
Richtung unklar" bei wenig Wind, Foehn-Block ohne Windzeilen bei 0 Zeichen.
Validierung: validation/hoehenwind/PATTERNS.md."""
import math
import unittest

import i18n
from engine import synoptic_context as sc
from scripts import briefing_v3_context as bc

DATE = "2026-11-05"


def _cache(regions: dict) -> tuple[dict, dict]:
    """{Region: [(kmh, dir), ...]} -> (Wetter-Cache, Spot->Region)."""
    cache, rmap = {}, {}
    for reg, vals in regions.items():
        for i, (kmh, d) in enumerate(vals):
            name = f"{reg}_{i}"
            cache[name] = {"pressure_level_data": {f"{DATE}T12:00": {
                "wind_speed_700hPa": kmh, "wind_direction_700hPa": d}}}
            rmap[name] = reg
    return cache, rmap


def _tile(regions: dict) -> dict:
    cache, rmap = _cache(regions)
    return sc.decide_flow_tile(cache, [DATE], rmap)["per_day"][0]


class FlowTileTest(unittest.TestCase):
    def test_direction_from_windy_regions_only(self):
        """Schwache Regionen aus Nord zaehlen nicht; die Richtung kommt aus den
        Regionen mit Wind (SW)."""
        day = _tile({"A": [(25, 225)] * 3, "B": [(30, 225)] * 3, "C": [(20, 225)] * 3,
                     "D": [(4, 0)] * 3})
        self.assertFalse(day["calm"])
        self.assertEqual(day["dir_deg"], 225)
        self.assertEqual((day["n_wind"], day["n_regions"]), (3, 4))

    def test_calm_when_fewer_than_20_percent_of_regions_have_wind(self):
        day = _tile({"A": [(25, 225)] * 3, "B": [(5, 90)] * 3, "C": [(6, 180)] * 3,
                     "D": [(3, 0)] * 3, "E": [(8, 270)] * 3, "F": [(7, 45)] * 3})
        self.assertTrue(day["calm"])            # 1 von 6 = 17 %
        self.assertIsNone(day["dir_deg"])

    def test_spot_outlier_does_not_drive_a_region(self):
        """Median der Komponenten: ein 90er-Spot macht eine schwache Region nicht windig."""
        day = _tile({"A": [(4, 200), (5, 210), (90, 20)], "B": [(20, 270)] * 3})
        self.assertEqual(day["n_wind"], 1)
        self.assertEqual(day["dir_deg"], 270)

    def test_region_with_too_few_spots_is_skipped(self):
        day = _tile({"A": [(20, 180)] * 3, "B": [(40, 0)] * 2})
        self.assertEqual((day["n_regions"], day["dir_deg"]), (1, 180))

    def test_north_wrap_around(self):
        day = _tile({"A": [(20, 350)] * 3, "B": [(20, 10)] * 3})
        self.assertIn(day["dir_deg"], (0, 360))


class StripTest(unittest.TestCase):
    def _wl(self, calm, dir_deg=None):
        return {"flow_overhead": {"per_day": [{"date": DATE, "sector": "Nord", "dir_deg": 0,
                                               "speed_kmh": 6, "strength": "schwach"}]},
                "flow_tile": {"per_day": [{"date": DATE, "calm": calm, "dir_deg": dir_deg,
                                           "n_regions": 21, "n_wind": 3 if calm else 18}]}}

    def test_calm_day_has_no_arrow(self):
        for lang, head, note in (("de", "Schwacher Wind", "Richtung unklar"),
                                 ("en", "Light wind", "direction unclear")):
            with i18n.lang_override(lang):
                s = bc._strip_synoptik(self._wl(True), [DATE])[DATE]
            self.assertEqual(s["wind_arrow"], "〰")
            self.assertEqual(s["wind_deg"], "")
            self.assertTrue(s["wind_calm"])
            self.assertEqual((s["wind_calm_head"], s["wind_calm_note"]), (head, note))
            self.assertEqual(s["wind_sector"], f"{head} · {note}")    # Mail: ein Ausdruck
            self.assertEqual(s["wind_strength"], "")

    def test_direction_comes_from_flow_tile_not_the_swiss_mean(self):
        with i18n.lang_override("en"):
            s = bc._strip_synoptik(self._wl(False, 180), [DATE])[DATE]
        self.assertEqual(s["wind_sector"], "S")      # nicht "N" aus dem Vektor-Mittel
        self.assertEqual(s["wind_strength"], "")     # keine Stärke oben (07.11.2026)
        self.assertFalse(s["wind_hot"])
        self.assertEqual(s["wind_deg"], "180°")
        self.assertFalse(s["wind_calm"])

    def test_old_cache_without_flow_tile_keeps_the_mean(self):
        wl = self._wl(False, 180)
        del wl["flow_tile"]
        with i18n.lang_override("en"):
            s = bc._strip_synoptik(wl, [DATE])[DATE]
        self.assertEqual(s["wind_sector"], "N")

    def test_tile_carries_calm_fields(self):
        with i18n.lang_override("de"):
            s = bc._strip_synoptik(self._wl(True), [DATE])[DATE]
        tile = bc._day_tile({}, [], s)
        self.assertTrue(tile["wind_calm"])
        self.assertIsNone(tile["wind_dir_deg"])
        self.assertEqual((tile["wind_calm_head"], tile["wind_calm_note"]), ("Schwacher Wind", "Richtung unklar"))


class FoehnZeroSignsTest(unittest.TestCase):
    def test_only_pressure_row_without_signs(self):
        ind = {"n_on": 0, "side": "nord",
               "pressure": {"on": False, "hpa": 3.4, "high_side": "nord"},
               "wind_map": {"on": False, "side": "nord", "n": 0, "total": 29},
               "luv_cooler": {"on": False, "side": "nord", "cooler_k": 0.2},
               "valleys": {"on": False, "n": 0, "total": 23}}
        with i18n.lang_override("de"):
            kind, pill, facts = bc._foehn_indicator_status(ind)
        self.assertEqual(kind, "neutral")
        self.assertEqual(pill, "Föhn-Indikatoren: 0 von 4")
        self.assertEqual([f["k"] for f in facts], ["Druckdiff."])
        self.assertFalse(any("Nordwind" in f["k"] for f in facts))


if __name__ == "__main__":
    unittest.main()
