"""Tests fuer engine/fronten.py — Auswahl der DWD-Frontkarte zu einem Zeitpunkt."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from engine import fronten


def _write(base: Path, rel: str, typ: str = "kalt") -> None:
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"typ": typ},
         "geometry": {"type": "LineString", "coordinates": [[0, 45], [5, 47]]}}]}),
        encoding="utf-8")


def _utc(y, mo, d, h):
    return datetime(y, mo, d, h, tzinfo=timezone.utc)


class TestSelectFrontMap(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_today_takes_the_nearest_analysis(self):
        _write(self.base, "analyse/dwdc_202609160000.geojson")
        _write(self.base, "analyse/dwdc_202609161200.geojson")
        out = fronten.select_front_map(_utc(2026, 9, 16, 10), self.base)
        self.assertEqual((out["kind"], out["valid"]), ("analyse", "2026-09-16T12:00:00+00:00"))

    def test_later_day_takes_the_forecast(self):
        _write(self.base, "analyse/dwdc_202609160000.geojson")
        _write(self.base, "vorhersage/dwd_fronten_202609160000_036.geojson")
        _write(self.base, "vorhersage/dwd_fronten_202609160000_060.geojson")
        out = fronten.select_front_map(_utc(2026, 9, 17, 10), self.base)
        self.assertEqual((out["kind"], out["lead_h"]), ("vorhersage", 36))

    def test_only_the_latest_run_counts(self):
        _write(self.base, "vorhersage/dwd_fronten_202609150000_060.geojson")   # gueltig 17.09. 12 UTC
        _write(self.base, "vorhersage/dwd_fronten_202609160000_036.geojson")   # gueltig 17.09. 12 UTC
        maps = fronten.available_front_maps(self.base)
        self.assertEqual([m["path"].name for m in maps],
                         ["dwd_fronten_202609160000_036.geojson"])

    def test_tie_prefers_the_analysis(self):
        _write(self.base, "analyse/dwdc_202609171200.geojson")
        _write(self.base, "vorhersage/dwd_fronten_202609160000_036.geojson")   # auch 17.09. 12 UTC
        out = fronten.select_front_map(_utc(2026, 9, 17, 12), self.base)
        self.assertEqual(out["kind"], "analyse")

    def test_too_far_away_means_no_fronts(self):
        """Eine Front von einem ganz anderen Zeitpunkt waere falsch, nicht ungenau."""
        _write(self.base, "analyse/dwdc_202609160000.geojson")
        self.assertIsNone(fronten.select_front_map(_utc(2026, 9, 18, 12), self.base))

    def test_empty_archive(self):
        self.assertIsNone(fronten.select_front_map(_utc(2026, 9, 16, 12), self.base))

    def test_naive_target_rejected(self):
        with self.assertRaises(ValueError):
            fronten.select_front_map(datetime(2026, 9, 16, 12), self.base)

    def test_geojson_is_returned(self):
        _write(self.base, "analyse/dwdc_202609160000.geojson", typ="okklusion")
        out = fronten.select_front_map(_utc(2026, 9, 16, 6), self.base)
        self.assertEqual(out["geojson"]["features"][0]["properties"]["typ"], "okklusion")
        self.assertEqual(out["offset_h"], 6.0)


class TestSelectForTimestep(unittest.TestCase):
    def test_local_timestep_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write(base, "analyse/dwdc_202609161200.geojson")
            out = fronten.select_for_timestep("2026-09-16T12:00", base)
            self.assertEqual(out["kind"], "analyse")

    def test_garbage_timestep(self):
        self.assertIsNone(fronten.select_for_timestep("gestern"))


class TestAvailableTimes(unittest.TestCase):
    def test_local_timestep_strings_sorted_unique(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write(base, "analyse/dwdc_202609161200.geojson")
            _write(base, "analyse/dwdc_202609160000.geojson")
            _write(base, "vorhersage/dwd_fronten_202609160000_036.geojson")   # 17.09. 12 UTC
            out = fronten.available_valid_times_local(base)
        self.assertEqual(len(out), 3)
        self.assertEqual(out, sorted(out))
        for v in out:
            self.assertRegex(v, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")

    def test_times_api(self):
        from unittest import mock
        import web
        with mock.patch("engine.fronten.available_valid_times_local",
                        return_value=["2026-09-16T02:00", "2026-09-16T14:00"]):
            body = web.app.test_client().get("/api/synoptic/fronts/times").get_json()
        self.assertEqual(body["valid"], ["2026-09-16T02:00", "2026-09-16T14:00"])
        self.assertEqual(body["tolerance_h"], 3)


class TestFrontsApi(unittest.TestCase):
    """Der Endpunkt liefert Linie + Typ, aber keine Serverpfade."""

    def test_api_strips_archive_paths(self):
        from unittest import mock
        import web
        sel = {"geojson": {"type": "FeatureCollection",
                           "properties": {"copyright": "\u00a9 DWD",
                                          "quelle_url": "/home/deploy/flychat/data/x.png"},
                           "features": [
                               {"type": "Feature",
                                "properties": {"typ": "kalt",
                                               "quelle_url": "/home/deploy/flychat/data/x.png"},
                                "geometry": {"type": "LineString",
                                             "coordinates": [[0, 45], [5, 47]]}},
                               {"type": "Feature", "properties": {"typ": "unbekannt"},
                                "geometry": {"type": "LineString", "coordinates": [[0, 1], [1, 2]]}}]},
               "kind": "analyse", "valid": "2026-09-16T00:00:00+00:00", "lead_h": 0}
        with mock.patch("engine.fronten.select_for_timestep", return_value=sel):
            r = web.app.test_client().get("/api/synoptic/fronts?ts=2026-09-16T12:00")
        body = r.get_json()
        self.assertTrue(body["success"])
        self.assertEqual(len(body["fronts"]["features"]), 1)
        self.assertEqual(body["fronts"]["features"][0]["properties"], {"typ": "kalt"})
        self.assertNotIn("/home/deploy", r.get_data(as_text=True))
        self.assertEqual(body["copyright"], "\u00a9 DWD")

    def test_api_without_fronts(self):
        from unittest import mock
        import web
        with mock.patch("engine.fronten.select_for_timestep", return_value=None):
            body = web.app.test_client().get("/api/synoptic/fronts?ts=x").get_json()
        self.assertEqual(body, {"success": True, "fronts": None})


if __name__ == "__main__":
    unittest.main()
