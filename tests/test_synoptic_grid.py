"""Tests fuer engine/synoptic_grid.py — dichtes Druckraster der Synoptik-Karte.

Deckt ab:
  - Raster-Geometrie: build_grid_meta, _grid_points (row-major ab NW)
  - Fetch: Multi-Location-Parsing (gemockt), Chunk-Fehler -> None
  - Zentren-Detektion: synthetisches Tief, Suppression, schwaches Feld,
    Rand-Ausschluss
"""
import math
import unittest
from unittest.mock import patch, MagicMock

import config
from engine import synoptic_grid as sg


def _flat_field(meta, value=1015.0):
    return [value] * (meta["ny"] * meta["nx"])


def _add_gaussian(meta, vals, j0, i0, amplitude, sigma_cells=2.0):
    """Addiert eine Gauss-Delle/-Beule (amplitude negativ = Tief) aufs Feld."""
    out = list(vals)
    for j in range(meta["ny"]):
        for i in range(meta["nx"]):
            d2 = (j - j0) ** 2 + (i - i0) ** 2
            out[j * meta["nx"] + i] += amplitude * math.exp(-d2 / (2 * sigma_cells ** 2))
    return out


class TestGridMeta(unittest.TestCase):
    def test_dimensions(self):
        meta = sg.build_grid_meta()
        self.assertEqual(meta["ny"], 23)
        self.assertEqual(meta["nx"], 36)
        self.assertEqual(meta["lat0"], 75.0)
        self.assertEqual(meta["lon0"], -65.0)
        self.assertEqual(meta["dlat"], -2.5)
        self.assertEqual(meta["dlon"], 3.5)

    def test_grid_points_row_major_from_nw(self):
        meta = sg.build_grid_meta()
        points = sg._grid_points(meta)
        self.assertEqual(len(points), 828)
        self.assertEqual(points[0], (75.0, -65.0))    # NW-Ecke
        self.assertEqual(points[1], (75.0, -61.5))    # eine Spalte weiter oestlich
        self.assertEqual(points[-1], (20.0, 57.5))    # SE-Ecke


class TestFetchGridPressure(unittest.TestCase):
    def _make_response(self, n_locations, times, msl_value=1013.37):
        """Baut ein Open-Meteo-Multi-Location-Payload (Liste von Locations)."""
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = [
            {"hourly": {"time": times, "pressure_msl": [msl_value] * len(times)}}
            for _ in range(n_locations)
        ]
        return resp

    def test_parses_chunked_payload(self):
        dates = ["2026-07-05"]
        times = [f"2026-07-05T{h:02d}:00" for h in (0, 6, 12, 18)]
        meta = sg.build_grid_meta()
        n = meta["ny"] * meta["nx"]
        chunk = config.SYNOPTIC_GRID_CHUNK_SIZE
        n_chunks = -(-n // chunk)
        responses = []
        for k in range(n_chunks):
            size = min(chunk, n - k * chunk)
            responses.append(self._make_response(size, times))

        with patch("engine.synoptic_grid.requests.get", side_effect=responses) as mget:
            result = sg.fetch_grid_pressure(dates)

        self.assertIsNotNone(result)
        self.assertEqual(mget.call_count, n_chunks)
        self.assertEqual(result["timesteps"],
                         ["2026-07-05T00:00", "2026-07-05T06:00",
                          "2026-07-05T12:00", "2026-07-05T18:00"])
        for ts in result["timesteps"]:
            self.assertEqual(len(result["values"][ts]), n)
            self.assertEqual(result["values"][ts][0], 1013.4)  # gerundet auf 1 Dezimale

    def test_missing_timestep_dropped(self):
        # Nur 12 UTC vorhanden -> 00/06/18 duerfen nicht als all-None auftauchen
        dates = ["2026-07-05"]
        times = ["2026-07-05T12:00"]
        meta = sg.build_grid_meta()
        n = meta["ny"] * meta["nx"]
        chunk = config.SYNOPTIC_GRID_CHUNK_SIZE
        n_chunks = -(-n // chunk)
        responses = [self._make_response(min(chunk, n - k * chunk), times)
                     for k in range(n_chunks)]

        with patch("engine.synoptic_grid.requests.get", side_effect=responses):
            result = sg.fetch_grid_pressure(dates)

        self.assertIsNotNone(result)
        self.assertEqual(result["timesteps"], ["2026-07-05T12:00"])

    def test_chunk_failure_returns_none(self):
        import requests as _requests
        dates = ["2026-07-05"]
        with patch("engine.synoptic_grid.requests.get",
                   side_effect=_requests.RequestException("boom")):
            result = sg.fetch_grid_pressure(dates)
        self.assertIsNone(result)

    def test_empty_dates_returns_none(self):
        self.assertIsNone(sg.fetch_grid_pressure([]))


class TestFindGridPressureCenters(unittest.TestCase):
    def setUp(self):
        self.meta = sg.build_grid_meta()

    def test_synthetic_low_detected(self):
        j0, i0 = 8, 12  # Mitte des Rasters
        vals = _add_gaussian(self.meta, _flat_field(self.meta), j0, i0, -20.0)
        centers = sg.find_grid_pressure_centers(self.meta, vals)
        self.assertEqual(len(centers), 1)
        c = centers[0]
        self.assertEqual(c["type"], "Tief")
        exp_lat, exp_lon = sg._cell_latlon(self.meta, j0, i0)
        self.assertAlmostEqual(c["lat"], exp_lat, places=1)
        self.assertAlmostEqual(c["lon"], exp_lon, places=1)
        self.assertAlmostEqual(c["msl_hpa"], 995.0, delta=0.2)

    def test_synthetic_high_detected(self):
        vals = _add_gaussian(self.meta, _flat_field(self.meta), 8, 12, +15.0)
        centers = sg.find_grid_pressure_centers(self.meta, vals)
        self.assertEqual(len(centers), 1)
        self.assertEqual(centers[0]["type"], "Hoch")

    def test_nearby_weaker_center_suppressed(self):
        # Zwei Tiefs 2 Zellen auseinander (~400-500 km) -> nur das staerkere
        vals = _flat_field(self.meta)
        vals = _add_gaussian(self.meta, vals, 8, 12, -20.0)
        vals = _add_gaussian(self.meta, vals, 8, 14, -10.0)
        centers = sg.find_grid_pressure_centers(self.meta, vals)
        lows = [c for c in centers if c["type"] == "Tief"]
        self.assertEqual(len(lows), 1)

    def test_weak_field_yields_nothing(self):
        # 1-hPa-Ripple liegt unter der Gradient-Schwelle
        vals = _add_gaussian(self.meta, _flat_field(self.meta), 8, 12, -1.0)
        self.assertEqual(sg.find_grid_pressure_centers(self.meta, vals), [])

    def test_border_extremum_excluded(self):
        # Extremum in der Ecke (Randring) darf nicht gemeldet werden
        vals = _add_gaussian(self.meta, _flat_field(self.meta), 0, 0, -25.0,
                             sigma_cells=1.5)
        centers = sg.find_grid_pressure_centers(self.meta, vals)
        for c in centers:
            self.assertNotAlmostEqual(c["lat"], self.meta["lat0"], places=1)

    def test_none_values_tolerated(self):
        vals = _add_gaussian(self.meta, _flat_field(self.meta), 8, 12, -20.0)
        vals[0] = None
        vals[3 * self.meta["nx"] + 5] = None
        centers = sg.find_grid_pressure_centers(self.meta, vals)
        self.assertEqual(len(centers), 1)


if __name__ == "__main__":
    unittest.main()
