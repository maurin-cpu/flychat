"""Tests fuer den Modellvergleich v2 (engine.synoptic_context) und seinen
Briefing-Satz (scripts.briefing_v3_context._modelle_block).

Regeln (docs/BRIEFING.md, Block 8): Klassenraster je Groesse, uneinig ab
zwei Klassen Abstand, Urteil je Region und Tagesfenster, Zone uneinig ab
einem Drittel uneiniger Regionen. Der Satz erzaehlt in denselben Klassen,
in denen gemessen wird — ein "uneinig" mit nur einer Modell-Gruppe (Vorfall
24.09.2026: "uneinig, aber alle sehen bedeckt") darf nicht mehr vorkommen.
"""
import unittest

import config
from engine import synoptic_context as sc
from scripts import briefing_v3_context as bc

DATE = "2026-09-25"
MODELS = list(sc.MODEL_COMPARE_MODELS)


def _hourly(per_model: dict) -> dict:
    """per_model: {modell: {"speed": x, "dir": d, "gust": g, "rain": mm/h,
    "cloud": %, "low": %}} — konstant ueber den Tag."""
    times = [f"{DATE}T{h:02d}:00" for h in range(24)]
    h = {"time": times}
    for m, v in per_model.items():
        h[f"wind_speed_10m_{m}"] = [v.get("speed", 15)] * 24
        h[f"wind_direction_10m_{m}"] = [v.get("dir", 0)] * 24
        h[f"wind_gusts_10m_{m}"] = [v.get("gust", 20)] * 24
        h[f"precipitation_{m}"] = [v.get("rain", 0.0)] * 24
        h[f"cloud_cover_{m}"] = [v.get("cloud", 50)] * 24
        h[f"cloud_cover_low_{m}"] = [v.get("low", 10)] * 24
    return h


def _icon(**kw):
    """Alle vier ICON-Modelle gleich, GFS wie ICON-EU."""
    return {m: dict(kw) for m in MODELS}


def _points(zone, regions: dict) -> list:
    """regions: {name: per_model} -> ein Punkt je Region."""
    return [{"zone": zone, "region": r, "hourly": _hourly(pm)} for r, pm in regions.items()]


def _param(mv, zone, param):
    return mv["per_day"][0]["zones"][zone]["params"][param]


class TestKlassen(unittest.TestCase):
    def test_boeen_klassen_bis_80(self):
        self.assertEqual(sc._mc_class("gust", 14), 0)
        self.assertEqual(sc._mc_class("gust", 30), 2)
        self.assertEqual(sc._mc_class("gust", 79), 4)
        self.assertEqual(sc._mc_class("gust", 80), 5)

    def test_sektoren(self):
        self.assertEqual(sc._mc_sector(350), 0)     # Nord
        self.assertEqual(sc._mc_sector(300), 7)     # Nordwest
        self.assertEqual(sc._mc_sector_gap(7, 0), 1)   # NW/N sind Nachbarn
        self.assertEqual(sc._mc_sector_gap(7, 4), 3)   # NW/S


class TestUrteil(unittest.TestCase):
    def test_nachbarklasse_ist_einig(self):
        pm = _icon(gust=24)
        pm["icon_eu"]["gust"] = 26
        mv = sc.modell_vergleich_aus_punkten(_points("wallis", {"a": pm}), [DATE])
        self.assertFalse(_param(mv, "wallis", "gust")["disagree"])

    def test_30_gegen_80_ist_uneinig(self):
        pm = _icon(gust=30)
        pm["icon_eu"]["gust"] = 80
        mv = sc.modell_vergleich_aus_punkten(_points("wallis", {"a": pm}), [DATE])
        g = _param(mv, "wallis", "gust")
        self.assertTrue(g["disagree"])
        self.assertEqual(g["windows"][g["worst_window"]]["regions"], ["a"])

    def test_gfs_zaehlt_bei_wind_nicht(self):
        pm = _icon(gust=30)
        pm["gfs_seamless"]["gust"] = 5
        mv = sc.modell_vergleich_aus_punkten(_points("wallis", {"a": pm}), [DATE])
        self.assertFalse(_param(mv, "wallis", "gust")["disagree"])

    def test_richtung_nachbarsektor_einig_gegenueber_uneinig(self):
        pm = _icon(dir=315, speed=15)              # NW
        pm["icon_eu"]["dir"] = 350                 # N -> Nachbar
        mv = sc.modell_vergleich_aus_punkten(_points("tessin", {"a": pm}), [DATE])
        self.assertFalse(_param(mv, "tessin", "dir")["disagree"])
        pm["icon_eu"]["dir"] = 180                 # S
        mv = sc.modell_vergleich_aus_punkten(_points("tessin", {"a": pm}), [DATE])
        self.assertTrue(_param(mv, "tessin", "dir")["disagree"])

    def test_richtung_bei_flaute_nicht_bewertet(self):
        pm = _icon(dir=315, speed=3)
        pm["icon_eu"]["dir"] = 180
        mv = sc.modell_vergleich_aus_punkten(_points("tessin", {"a": pm}), [DATE])
        self.assertNotIn("dir", mv["per_day"][0]["zones"]["tessin"]["params"])

    def test_regen_manche_nass_andere_trocken(self):
        pm = _icon(rain=0.0)
        pm["gfs_seamless"]["rain"] = 0.5           # 4 h Fenster -> 2 mm
        mv = sc.modell_vergleich_aus_punkten(_points("wallis", {"a": pm}), [DATE])
        self.assertTrue(_param(mv, "wallis", "rain")["disagree"])

    def test_zone_erst_ab_drittel_der_regionen(self):
        einig = _icon(cloud=50)
        streit = _icon(cloud=10)
        streit["icon_eu"]["cloud"] = 90
        mv = sc.modell_vergleich_aus_punkten(
            _points("alpennordhang", {"a": streit, "b": einig, "c": einig, "d": einig}), [DATE])
        self.assertFalse(_param(mv, "alpennordhang", "cloud")["disagree"])
        mv = sc.modell_vergleich_aus_punkten(
            _points("alpennordhang", {"a": streit, "b": streit, "c": einig, "d": einig}), [DATE])
        self.assertTrue(_param(mv, "alpennordhang", "cloud")["disagree"])

    def test_tagesfenster_getrennt(self):
        """Sturm am Vormittag (CH1) vs. Sturm am Nachmittag (EU): dieselbe
        Tagesspitze, aber Streit in beiden Fenstern."""
        pm = _icon(gust=20)
        h = _hourly(pm)
        h["wind_gusts_10m_meteoswiss_icon_ch1"] = [70 if hh < 10 else 20 for hh in range(24)]
        h["wind_gusts_10m_icon_eu"] = [70 if hh >= 14 else 20 for hh in range(24)]
        mv = sc.modell_vergleich_aus_punkten([{"zone": "wallis", "region": "a", "hourly": h}], [DATE])
        w = _param(mv, "wallis", "gust")["windows"]
        self.assertTrue(w["morning"]["disagree"])
        self.assertFalse(w["midday"]["disagree"])
        self.assertTrue(w["afternoon"]["disagree"])


class TestSatz(unittest.TestCase):
    def setUp(self):
        self._lang = config.LANG

    def tearDown(self):
        config.LANG = self._lang

    def _block(self, points, lang="de"):
        config.LANG = lang
        mv = sc.modell_vergleich_aus_punkten(points, [DATE])
        return bc._modelle_block({"modell_vergleich": mv}, DATE)

    def test_einig(self):
        b = self._block(_points("wallis", {"a": _icon()}))
        self.assertEqual(b["verdict"], "agree")
        self.assertEqual(len(b["agree"]), 6)

    def test_uneinig_hat_immer_zwei_gruppen_und_keine_schluessel(self):
        pm = _icon(gust=30)
        pm["icon_eu"]["gust"] = 80
        b = self._block(_points("wallis", {"a": pm}))
        self.assertEqual(b["verdict"], "partial")
        self.assertIn("ICON-CH1, ICON-CH2, ICON-D2 und GFS sehen stark (25–40 km/h)", b["fazit"])
        self.assertIn("ICON-EU sieht schweren Sturm (über 80 km/h)", b["fazit"])
        self.assertIn("1 von 1 Regionen", b["fazit"])
        self.assertNotIn("md_", b["fazit"])

    def test_englisch(self):
        pm = _icon(gust=30)
        pm["icon_eu"]["gust"] = 80
        b = self._block(_points("wallis", {"a": pm}), lang="en")
        self.assertIn("gusts in Valais", b["fazit"])
        self.assertIn("ICON-EU sees severe storm (over 80 km/h)", b["fazit"])

    def test_gruppen_aus_der_streitenden_region(self):
        """Mediane ueber einige Regionen wuerden den Streit verwischen —
        der Satz muss trotzdem zwei Gruppen zeigen."""
        a = _icon(cloud=10); a["icon_eu"]["cloud"] = 90
        b_ = _icon(cloud=90); b_["icon_eu"]["cloud"] = 10
        b = self._block(_points("tessin", {"a": a, "b": b_}))
        self.assertEqual(b["verdict"], "partial")
        self.assertIn("wenig Wolken (0–20 %)", b["fazit"])
        self.assertIn("bedeckt (80–100 %)", b["fazit"])

    def test_altes_format_wird_ignoriert(self):
        self.assertEqual(bc._modelle_block({"modell_vergleich": {"per_day": []}}, DATE), {})


if __name__ == "__main__":
    unittest.main()
