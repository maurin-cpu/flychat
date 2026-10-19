"""Fronten-Block nach Zeichen (Briefing Block 2, 17.10.2026).

Regeln aus den Vorgaben: zuerst die DWD-Karte ohne Uhrzeit, dann die Modellzeichen
mit Tageszeit; jedes Label kommt im Text vor; Zeichen vom Vorabend zählen nicht;
nie "die Front kommt" und nie "Flugfenster".
"""
import csv
import re
import unittest
from datetime import datetime, timedelta

import config
import front_indicators as fi
import i18n
from scripts import briefing_v3_context as bc

DAY = "2026-10-17"


def _spot(t850=None, precip=None, dir700=None, cloud=None):
    """Startplatz mit Stundenreihe von 18 Uhr am Vortag bis 23 Uhr. Die Funktionen
    bekommen die Stunde relativ zum Tagesbeginn (h=-6 ... 23) und liefern den Wert."""
    hd, pl = {}, {}
    start = datetime.fromisoformat(DAY) - timedelta(hours=6)
    for i in range(30):
        h = i - 6
        t = (start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00")
        hd[t] = {"precipitation": precip(h) if precip else 0.0,
                 "cloud_cover_mid": cloud(h) if cloud else 20, "cloud_cover_high": 0}
        pl[t] = {"temperature_850hPa": t850(h) if t850 else 5.0,
                 "wind_direction_700hPa": dir700(h) if dir700 else 240.0, "wind_speed_700hPa": 30.0}
    return {"hourly_data": hd, "pressure_level_data": pl}


def _rows(spot):
    return fi._series(spot, DAY)


class ZoneSignsTest(unittest.TestCase):
    def test_cooling_rain_and_wind_shift(self):
        s = _spot(t850=lambda h: 5.0 if h < 12 else 1.0,
                  precip=lambda h: 1.0 if h >= 16 else 0.0,
                  dir700=lambda h: 240.0 if h < 20 else 320.0)
        first = fi._zone_signs([_rows(s)] * 3)
        self.assertEqual(first["kaelter"], 12)
        self.assertEqual(first["regen"], 16)
        self.assertEqual(first["dauerregen"], 18)
        self.assertEqual(first["dreh"], 20)
        self.assertEqual(first["luft"], 12)

    def test_cloud_is_a_change_not_a_state(self):
        # den ganzen Tag bedeckt -> keine "Verdichtung"
        steady = fi._zone_signs([_rows(_spot(cloud=lambda h: 95))] * 3)
        self.assertNotIn("wolken", steady)
        rising = fi._zone_signs([_rows(_spot(cloud=lambda h: 20 if h < 8 else 95))] * 3)
        self.assertEqual(rising["wolken"], 8)

    def test_share_of_spots(self):
        wet = _spot(precip=lambda h: 1.0 if h >= 10 else 0.0)
        dry = _spot()
        self.assertNotIn("regen", fi._zone_signs([_rows(wet)] + [_rows(dry)] * 3))   # 25 %
        self.assertEqual(fi._zone_signs([_rows(wet)] * 2 + [_rows(dry)] * 3)["regen"], 10)  # 40 %


class EvaluateTest(unittest.TestCase):
    def test_type_from_dwd_and_carried_over(self):
        zones = {"alpennordhang": {"kaelter": 0, "regen": 16, "dreh": 22}}
        ev = fi.evaluate_front_signs(zones, {"typ": "kalt", "zone_hours": {"alpennordhang": 14}})
        self.assertEqual(ev["typ"], "kalt")
        self.assertEqual(ev["carried"], ["kaelter"])
        self.assertEqual(ev["n_on"], 3)            # DWD + Regen + Winddrehung
        self.assertEqual(ev["from_hour"], 16)

    def test_type_from_data_without_dwd(self):
        ev = fi.evaluate_front_signs({"tessin": {"waermer": 9, "wolken": 5}}, None)
        self.assertEqual(ev["typ"], "warm")
        self.assertIsNone(ev["first"]["dwd"])
        self.assertEqual(ev["n_on"], 2)


class BlockTextTest(unittest.TestCase):
    FORBIDDEN = re.compile(r"(?i)\b(front (comes|arrives|reaches|crosses|passes)|flying window|"
                           r"Flugfenster|kommt die Front|zieht durch)\b")

    def _block(self, zones, dwd_typ="", hours=None, lang="en"):
        fb = {"dwd": bool(dwd_typ), "dwd_typ": dwd_typ, "dwd_zone_hours": hours or {}}
        with i18n.lang_override(lang):
            return bc._front_signs_block(fb, zones)

    def test_dwd_without_time_and_every_label_explained(self):
        zones = {"alpennordhang": {"kaelter": 6, "regen": 22}}
        kind, pill, facts, txt = self._block(zones, "kalt", {"alpennordhang": 14})
        self.assertTrue(txt.startswith("DWD forecast map: cold front."))
        self.assertNotIn("14:00", txt)                               # keine DWD-Uhrzeit
        self.assertEqual(pill, "Front signs: 3 of 4 · from ~06:00")
        self.assertIn("from about 06:00", txt)
        self.assertIn("Not in the data: a wind shift aloft", txt)     # fehlendes Label erklärt
        for word in ("colder air at 1500 m", "rain", "wind shift aloft"):
            self.assertIn(word, txt)
        self.assertEqual([f["on"] for f in facts], [True, True, False, True])
        self.assertEqual(kind, "warn")

    def test_no_front_on_map_only_the_dwd_sentence(self):
        # Modellzeichen ohne DWD-Front sind keine Frontzeichen (User 19.10.2026)
        kind, pill, facts, txt = self._block({"tessin": {"waermer": 3, "regen": 9}})
        self.assertEqual(txt, "DWD forecast map: no front forecast.")
        self.assertEqual((kind, pill, facts), ("neutral", "DWD map: no front", []))
        _, pill_de, _, txt_de = self._block({}, lang="de")
        self.assertEqual(txt_de, "DWD-Prognosekarte: keine Front prognostiziert.")
        self.assertEqual(pill_de, "DWD-Karte: keine Front")

    def test_carried_over_is_named_not_counted(self):
        kind, pill, facts, txt = self._block({"alpennordhang": {"kaelter": 0}}, "kalt")
        self.assertEqual(pill, "Front signs: 1 of 4")
        self.assertIn("Carried over from the day before: colder air at 1500 m", txt)
        self.assertIn("(day before)", facts[1]["v"])

    def test_direction_only_from_dwd_line(self):
        zones = {"alpennordhang": {"regen": 15}, "tessin": {"regen": 18}}
        _, _, _, txt = self._block(zones, "kalt", {"alpennordhang": 13, "tessin": 17})
        self.assertIn("spreading from north to south", txt)
        _, _, _, same = self._block(zones, "kalt", {"alpennordhang": 13, "tessin": 14})
        self.assertNotIn("spreading", same)

    def test_wording_rules_both_languages(self):
        cases = [({"alpennordhang": {"kaelter": 6, "regen": 22, "dreh": 23}}, "kalt"),
                 ({"tessin": {"wolken": 8, "waermer": 12, "dauerregen": 16}}, "warm"),
                 ({}, ""), ({"wallis": {"regen": 1}}, "")]
        for zones, typ in cases:
            for lang in ("en", "de"):
                _, _, _, txt = self._block(zones, typ, lang=lang)
                self.assertNotRegex(txt, self.FORBIDDEN, f"{lang}: {txt}")
        _, pill, _, txt = self._block({"alpennordhang": {"regen": 9}}, "kalt", lang="de")
        self.assertTrue(txt.startswith("DWD-Prognosekarte: Kaltfront."))
        self.assertIn("ab ~09 Uhr", pill)


class DetectTest(unittest.TestCase):
    def test_spots_grouped_by_zone(self):
        regions = list(csv.DictReader(open(config.PROJECT_ROOT / "data" / "regionen.csv", encoding="utf-8")))
        nord = next(r["region_name"] for r in regions if r["zone"] == "alpennordhang")
        cache = {"_meta": {}, **{f"S{i}": _spot(precip=lambda h: 1.0 if h >= 13 else 0.0) for i in range(3)}}
        out = fi.detect_front_signs(cache, [DAY], spot_region={f"S{i}": nord for i in range(3)})
        self.assertEqual(out["per_day"][0]["zones"]["alpennordhang"]["regen"], 13)


if __name__ == "__main__":
    unittest.main()
