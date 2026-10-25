"""Tests fuer engine/synoptic_llm.py — die Gefahren-Schalter (hazard_checks)
und die Tagesform (_day_shape). Der LLM-Teil (Validator, Finalisierung,
Payload) ist seit 25.10.2026 entfernt, seine Tests mit ihm.
"""
import unittest

import config
from engine import synoptic_llm as sl

ZONES = list(config.SYNOPTIC_ZONES)


def _ctx(dates=("2026-07-05", "2026-07-06"), centers=("Azoren",), foehn=None):
    """Minimales Strukturfeld fuer Validierungs-Tests."""
    return {
        "forecast_dates": list(dates),
        "pressure_centers_per_day": [{
            "date": dates[0],
            "centers": [{"type": "Hoch", "region_label": c} for c in centers],
        }],
        "foehn": foehn or {},
    }


def _wind_zones(dates, class_by_zone_per_day):
    """wind_zones-Strukturfeld: [{zone: wind_class}] pro Tag."""
    return {"per_day": [
        {"date": d,
         "zones": {z: {"wind_class": cls} for z, cls in per_day.items()}}
        for d, per_day in zip(dates, class_by_zone_per_day)
    ]}


# ============================================================================
# Gefahren schweizweit (hazards)
# ============================================================================

def _hz_ctx(dates=("2026-07-05", "2026-07-06")):
    """Ruhiges Strukturfeld: keine Gefahr aktiv, alle Felder vorhanden."""
    ctx = _ctx(dates=dates)
    ctx["precip_zones"] = {"per_day": [
        {"date": d, "zones": {z: {"day": {"wet_share": 0.0, "p90_mm": 0.0,
                                          "gewitter_share": 0.0}} for z in ZONES}}
        for d in dates]}
    ctx["wind_zones"] = _wind_zones(dates, [{z: "unauffaellig" for z in ZONES}
                                            for _ in dates])
    return ctx


def _set_rain(ctx, i, zone, share, p90=1.5, windows=None):
    """windows: {fenster: wet_share} — ohne das bleibt der Tag pauschal."""
    ctx["precip_zones"]["per_day"][i]["zones"][zone]["day"].update(
        {"wet_share": share, "p90_mm": p90})
    if windows:
        ctx["precip_zones"]["per_day"][i]["zones"][zone]["windows"] = {
            w: {"wet_share": v} for w, v in windows.items()}


def _set_wind(ctx, i, zone, cls="verblasen", windows=None):
    """windows: {fenster: share_wind_crit}."""
    z = ctx["wind_zones"]["per_day"][i]["zones"][zone]
    z["wind_class"] = cls
    if windows:
        z["windows"] = {w: {"share_wind_crit": v} for w, v in windows.items()}


RAIN_TEXT = "Regen erfasst ab Mittag den Alpennordhang von Westen her."


class TestHazardChecks(unittest.TestCase):
    def test_all_inactive_on_calm_day(self):
        checks = sl.hazard_checks(_hz_ctx())
        self.assertEqual(len(checks), 2)
        for c in checks:
            self.assertFalse(any(v["active"] for v in c["checks"].values()))

    def test_rain_above_threshold_lists_zones(self):
        ctx = _hz_ctx()
        _set_rain(ctx, 0, "alpennordhang", 0.5)
        checks = sl.hazard_checks(ctx)
        self.assertTrue(checks[0]["checks"]["RAIN"]["active"])
        self.assertEqual(checks[0]["checks"]["RAIN"]["zones"], ["alpennordhang"])
        self.assertEqual(checks[0]["checks"]["RAIN"]["facts"]["wet_share"], 0.5)
        self.assertFalse(checks[1]["checks"]["RAIN"]["active"])

    def test_rain_below_threshold_inactive(self):
        ctx = _hz_ctx()
        _set_rain(ctx, 0, "tessin", 0.1)
        self.assertFalse(sl.hazard_checks(ctx)[0]["checks"]["RAIN"]["active"])

    def test_thunder_from_gewitter_share_or_konvektion(self):
        ctx = _hz_ctx()
        ctx["precip_zones"]["per_day"][0]["zones"]["wallis"]["day"]["gewitter_share"] = 0.1
        ctx["konvektion"] = {"per_day": [
            {}, {"zones": {"tessin": {"gewitter": [["Sopraceneri", "14:00-16:00"]]}}}]}
        checks = sl.hazard_checks(ctx)
        self.assertEqual(checks[0]["checks"]["THUNDER"]["zones"], ["wallis"])
        self.assertEqual(checks[1]["checks"]["THUNDER"]["zones"], ["tessin"])
        self.assertEqual(checks[0]["checks"]["THUNDER"]["level"], "stop")

    def test_foehn_side_level_and_lee_zones(self):
        ctx = _hz_ctx()
        ctx["foehn"] = {"per_day": [{"date": "2026-07-05", "nord_active": True,
                                     "peak_nord": "danger", "nord_hours": 6}]}
        f = sl.hazard_checks(ctx)[0]["checks"]["FOEHN"]
        self.assertTrue(f["active"])
        self.assertEqual(f["level"], "stop")
        self.assertEqual(f["zones"], ["tessin"])
        self.assertEqual(f["facts"]["side"], "nord")
        self.assertEqual(f["facts"]["hours"], 6)

    def test_bise_is_no_hazard(self):
        # User 12.10.2026: Bise ist kein Briefing-Thema, auch wenn erkannt.
        ctx = _hz_ctx()
        ctx["bise"] = {"per_day": [{"date": "2026-07-06", "active": True,
                                    "strength": "maessig", "delta_p_hpa": 3.1}]}
        checks = sl.hazard_checks(ctx)
        self.assertNotIn("BISE", checks[1]["checks"])
        self.assertNotIn("BISE", sl.HAZARD_TOPICS)

    def test_wind_verblasen_is_stop(self):
        ctx = _hz_ctx()
        ctx["wind_zones"]["per_day"][0]["zones"]["alpennordhang"]["wind_class"] = "verblasen"
        ctx["wind_zones"]["per_day"][1]["zones"]["wallis"]["wind_class"] = "stark_eingeschraenkt"
        checks = sl.hazard_checks(ctx)
        self.assertEqual(checks[0]["checks"]["WIND"]["level"], "stop")
        self.assertEqual(checks[1]["checks"]["WIND"]["level"], "warn")
        self.assertEqual(checks[1]["checks"]["WIND"]["zones"], ["wallis"])

    def test_old_cache_without_fields(self):
        checks = sl.hazard_checks(_ctx())
        self.assertFalse(any(v["active"] for c in checks for v in c["checks"].values()))


WIND_TEXT = "Am Alpennordhang verblasen durch kraeftigen Hoehenwind."


# ============================================================================
# Tagesverlauf und Folgetag — die Warnung darf keine Tagespauschale sein
# ============================================================================

class TestDayShape(unittest.TestCase):
    def test_none_without_window_data(self):
        self.assertIsNone(sl._day_shape({}))

    def test_ganztags(self):
        sh = sl._day_shape({"tessin": ["morning", "midday", "afternoon", "evening"]})
        self.assertEqual(sh["shape"], "ganztags")

    def test_ab_nachmittag(self):
        sh = sl._day_shape({"alpennordhang": ["afternoon", "evening"]})
        self.assertEqual((sh["shape"], sh["from"]), ("ab", "afternoon"))

    def test_bis_mittag(self):
        sh = sl._day_shape({"alpennordhang": ["morning", "midday"]})
        self.assertEqual((sh["shape"], sh["to"]), ("bis", "midday"))

    def test_nur_ein_fenster(self):
        self.assertEqual(sl._day_shape({"wallis": ["midday"]})["shape"], "nur")

    def test_spanne_in_der_tagesmitte(self):
        sh = sl._day_shape({"wallis": ["midday", "afternoon"]})
        self.assertEqual((sh["shape"], sh["from"], sh["to"]),
                         ("spanne", "midday", "afternoon"))

    def test_luecke_ist_wechselnd(self):
        sh = sl._day_shape({"wallis": ["morning", "evening"]})
        self.assertEqual(sh["shape"], "wechselnd")

    def test_zonen_werden_vereinigt(self):
        sh = sl._day_shape({"alpennordhang": ["midday"],
                            "tessin": ["afternoon", "evening"]})
        self.assertEqual(sh["hit"], ["midday", "afternoon", "evening"])

    def test_unterschiedliche_zonen_sind_gemischt_nicht_ganztags(self):
        """Vorfall 16.09.2026: Alpennordhang ganztags, Wallis nur morgens und
        abends — die Vereinigung hiess 'ganztags', die KI schrieb 'all day'."""
        full = ["morning", "midday", "afternoon", "evening"]
        sh = sl._day_shape({"alpennordhang": full,
                            "wallis": ["morning", "evening"]})
        self.assertEqual(sh["shape"], "gemischt")

    def test_gleicher_verlauf_bleibt_eine_form(self):
        sh = sl._day_shape({"alpennordhang": ["afternoon", "evening"],
                            "tessin": ["afternoon", "evening"]})
        self.assertEqual((sh["shape"], sh["from"]), ("ab", "afternoon"))


class TestHazardWindows(unittest.TestCase):
    def test_rain_windows_per_zone(self):
        ctx = _hz_ctx()
        _set_rain(ctx, 0, "alpennordhang", 0.6,
                  windows={"morning": 0.0, "midday": 0.3, "afternoon": 0.7,
                           "evening": 0.5})
        f = sl.hazard_checks(ctx)[0]["checks"]["RAIN"]["facts"]
        self.assertEqual(f["windows"],
                         {"alpennordhang": ["midday", "afternoon", "evening"]})
        self.assertEqual(f["day_shape"]["shape"], "ab")
        self.assertEqual(f["day_shape"]["from"], "midday")

    def test_dry_morning_is_not_in_the_window_list(self):
        ctx = _hz_ctx()
        _set_rain(ctx, 0, "wallis", 0.5,
                  windows={"morning": 0.05, "midday": 0.6, "afternoon": 0.6,
                           "evening": 0.6})
        f = sl.hazard_checks(ctx)[0]["checks"]["RAIN"]["facts"]
        self.assertNotIn("morning", f["windows"]["wallis"])

    def test_wind_windows_use_share_wind_crit(self):
        ctx = _hz_ctx()
        _set_wind(ctx, 0, "alpennordhang", "verblasen",
                  windows={"morning": 0.1, "midday": 0.4, "afternoon": 0.8,
                           "evening": 0.9})
        f = sl.hazard_checks(ctx)[0]["checks"]["WIND"]["facts"]
        self.assertEqual(f["windows"],
                         {"alpennordhang": ["midday", "afternoon", "evening"]})
        self.assertEqual(f["day_shape"]["shape"], "ab")

    def test_thunder_windows_from_konvektion_time_span(self):
        ctx = _hz_ctx()
        ctx["konvektion"] = {"per_day": [
            {"zones": {"tessin": {"gewitter": [["Sopraceneri", "14:00-16:00"]]}}},
            {}]}
        f = sl.hazard_checks(ctx)[0]["checks"]["THUNDER"]["facts"]
        self.assertEqual(f["windows"], {"tessin": ["afternoon"]})
        self.assertEqual(f["day_shape"]["shape"], "nur")

    def test_no_windows_in_old_cache(self):
        ctx = _hz_ctx()
        _set_rain(ctx, 0, "tessin", 0.4)
        f = sl.hazard_checks(ctx)[0]["checks"]["RAIN"]["facts"]
        self.assertEqual(f["windows"], {})
        self.assertIsNone(f["day_shape"])


class TestFoehnCourse(unittest.TestCase):
    """Foehn: Tagesverlauf, Staerke und die Spur in den Winddaten."""

    def _ctx(self, win_hours, peak="caution"):
        """win_hours: {fenster: stunden} fuer Nordfoehn an Tag 0."""
        ctx = _hz_ctx()
        ctx["foehn"] = {"per_day": [{
            "date": "2026-07-05", "nord_active": True, "peak_nord": peak,
            "nord_hours": sum(win_hours.values()),
            "nord_windows": {w: {"hours": h, "peak": peak if h else "none"}
                             for w, h in win_hours.items()},
        }]}
        return ctx

    def test_windows_map_to_the_lee_zone(self):
        f = sl.hazard_checks(self._ctx({"morning": 0, "midday": 2,
                                        "afternoon": 4, "evening": 3})
                             )[0]["checks"]["FOEHN"]["facts"]
        self.assertEqual(f["windows"], {"tessin": ["midday", "afternoon", "evening"]})
        self.assertEqual(f["day_shape"]["shape"], "ab")

    def test_course_increases_towards_evening(self):
        f = sl.hazard_checks(self._ctx({"morning": 1, "midday": 1,
                                        "afternoon": 4, "evening": 4})
                             )[0]["checks"]["FOEHN"]["facts"]
        self.assertEqual(f["course"], "zunehmend")

    def test_course_eases_off(self):
        f = sl.hazard_checks(self._ctx({"morning": 4, "midday": 4,
                                        "afternoon": 1, "evening": 0})
                             )[0]["checks"]["FOEHN"]["facts"]
        self.assertEqual(f["course"], "abflauend")

    def test_course_steady(self):
        f = sl.hazard_checks(self._ctx({"morning": 3, "midday": 3,
                                        "afternoon": 3, "evening": 3})
                             )[0]["checks"]["FOEHN"]["facts"]
        self.assertEqual(f["course"], "gleich")

    def test_danger_peak_beats_hours(self):
        """Eine Stunde 'danger' am Nachmittag wiegt schwerer als vier
        Stunden 'caution' am Morgen — sonst heisst ein Tag, der erst
        gefaehrlich wird, 'abflauend'."""
        ctx = self._ctx({"morning": 4, "midday": 0, "afternoon": 1, "evening": 0})
        wins = ctx["foehn"]["per_day"][0]["nord_windows"]
        wins["morning"]["peak"] = "caution"
        wins["afternoon"]["peak"] = "danger"
        f = sl.hazard_checks(ctx)[0]["checks"]["FOEHN"]["facts"]
        self.assertEqual(f["course"], "zunehmend")

    def test_lee_gusts_come_from_the_wind_windows(self):
        ctx = self._ctx({"morning": 0, "midday": 2, "afternoon": 4, "evening": 2})
        ctx["wind_zones"]["per_day"][0]["zones"]["tessin"]["windows"] = {
            "midday": {"p90_gust_kmh": 38.0}, "afternoon": {"p90_gust_kmh": 55.4}}
        f = sl.hazard_checks(ctx)[0]["checks"]["FOEHN"]["facts"]
        self.assertEqual(f["lee_gust_kmh"], 55)

    def test_old_cache_without_foehn_windows(self):
        ctx = _hz_ctx()
        ctx["foehn"] = {"per_day": [{"date": "2026-07-05", "nord_active": True,
                                     "peak_nord": "caution", "nord_hours": 3}]}
        f = sl.hazard_checks(ctx)[0]["checks"]["FOEHN"]["facts"]
        self.assertEqual(f["windows"], {})
        self.assertIsNone(f["day_shape"])
        self.assertIsNone(f["course"])


class TestHazardOutlook(unittest.TestCase):
    def test_hazard_over_tomorrow(self):
        ctx = _hz_ctx()
        _set_rain(ctx, 0, "alpennordhang", 0.6)
        tm = sl.hazard_checks(ctx)[0]["checks"]["RAIN"]["facts"]["tomorrow"]
        self.assertEqual(tm, {"active": False, "trend": "vorbei"})

    def test_increasing_and_easing(self):
        ctx = _hz_ctx(dates=("2026-07-05", "2026-07-06", "2026-07-07"))
        _set_rain(ctx, 0, "alpennordhang", 0.3)
        _set_rain(ctx, 1, "alpennordhang", 0.9)
        _set_rain(ctx, 2, "alpennordhang", 0.3)
        checks = sl.hazard_checks(ctx)
        self.assertEqual(
            checks[0]["checks"]["RAIN"]["facts"]["tomorrow"]["trend"], "zunehmend")
        self.assertEqual(
            checks[1]["checks"]["RAIN"]["facts"]["tomorrow"]["trend"], "abklingend")

    def test_same_strength_is_gleich(self):
        ctx = _hz_ctx()
        _set_rain(ctx, 0, "alpennordhang", 0.5)
        _set_rain(ctx, 1, "alpennordhang", 0.5)
        self.assertEqual(
            sl.hazard_checks(ctx)[0]["checks"]["RAIN"]["facts"]["tomorrow"]["trend"],
            "gleich")

    def test_last_day_has_no_outlook(self):
        ctx = _hz_ctx()
        _set_rain(ctx, 1, "alpennordhang", 0.5)
        self.assertIsNone(
            sl.hazard_checks(ctx)[1]["checks"]["RAIN"]["facts"]["tomorrow"])

    def test_wind_trend_counts_zones(self):
        ctx = _hz_ctx()
        _set_wind(ctx, 0, "alpennordhang")
        _set_wind(ctx, 1, "alpennordhang")
        _set_wind(ctx, 1, "wallis")
        self.assertEqual(
            sl.hazard_checks(ctx)[0]["checks"]["WIND"]["facts"]["tomorrow"]["trend"],
            "zunehmend")


if __name__ == "__main__":
    unittest.main()
