"""Tests fuer engine/synoptic_llm.py — Post-Filter und Payload-Builder.

Deckt Halluzinations-Schutz ab:
  - Verbotsbegriffe werden verworfen (Kaltfront, Trog, hPa-Werte, ...)
  - Ungueltige Source-Tags fuehren zur Ablehnung
  - Erfundene Region-Labels werden erkannt
  - Provenance wird vor LLM-Uebergabe gestrippt

LLM-Calls selbst werden NICHT getestet (Integration).
"""
import unittest

import config
from engine import synoptic_llm as sl


class TestFilterStatements(unittest.TestCase):
    def setUp(self):
        self.valid_centers = {"Schottland", "Azoren"}

    def test_accept_clean_statement(self):
        statements = [{
            "text": "Hochdruck dominiert die Woche.",
            "sources": ["pressure_influence"],
        }]
        out = sl._filter_statements(statements, self.valid_centers)
        self.assertEqual(len(out), 1)

    def test_reject_kaltfront(self):
        statements = [{
            "text": "Eine Kaltfront zieht Mittwoch durch.",
            "sources": ["pressure_influence"],
        }]
        out = sl._filter_statements(statements, self.valid_centers)
        self.assertEqual(out, [])

    def test_reject_hpa_value(self):
        statements = [{
            "text": "Der Druck steigt auf 1025 hPa.",
            "sources": ["pressure_influence"],
        }]
        out = sl._filter_statements(statements, self.valid_centers)
        self.assertEqual(out, [])

    def test_reject_trog(self):
        statements = [{
            "text": "Ein Trog ueber Westeuropa bringt Wechsel.",
            "sources": ["pressure_centers_per_day"],
        }]
        out = sl._filter_statements(statements, self.valid_centers)
        self.assertEqual(out, [])

    def test_reject_geopotential(self):
        statements = [{
            "text": "Das Geopotential auf 500 hPa zeigt einen Trog.",
            "sources": ["flow_overhead"],
        }]
        out = sl._filter_statements(statements, self.valid_centers)
        self.assertEqual(out, [])

    def test_reject_invalid_source(self):
        statements = [{
            "text": "Hochdruck dominiert.",
            "sources": ["pressure_influence", "made_up_source"],
        }]
        out = sl._filter_statements(statements, self.valid_centers)
        self.assertEqual(out, [])

    def test_reject_no_sources(self):
        statements = [{"text": "Schoenes Wetter.", "sources": []}]
        out = sl._filter_statements(statements, self.valid_centers)
        self.assertEqual(out, [])

    def test_reject_invalid_region(self):
        # "Island" ist im Grid, aber NICHT in valid_centers (nicht detektiert)
        statements = [{
            "text": "Ein Hoch ueber Island setzt sich durch.",
            "sources": ["pressure_centers_per_day"],
        }]
        out = sl._filter_statements(statements, self.valid_centers)
        self.assertEqual(out, [])

    def test_accept_valid_region(self):
        statements = [{
            "text": "Ein Hoch ueber den Azoren reicht zur Schweiz.",
            "sources": ["pressure_centers_per_day"],
        }]
        out = sl._filter_statements(statements, self.valid_centers)
        self.assertEqual(len(out), 1)

    def test_accept_multiple_sources(self):
        statements = [{
            "text": "Hochdruck bleibt stabil mit Westströmung.",
            "sources": ["pressure_influence", "flow_overhead"],
        }]
        out = sl._filter_statements(statements, self.valid_centers)
        self.assertEqual(len(out), 1)


class TestStripProvenance(unittest.TestCase):
    def test_strips_internal_fields(self):
        field = {
            "value": "Hochdruck",
            "trend": "stabil",
            "decided_by": "decide_pressure_influence",
            "inputs": {"msl_by_day": [1023, 1024]},
            "thresholds": {"hoch_hpa": 1020},
        }
        out = sl._strip_provenance(field)
        self.assertIn("value", out)
        self.assertIn("trend", out)
        self.assertNotIn("decided_by", out)
        self.assertNotIn("inputs", out)
        self.assertNotIn("thresholds", out)

    def test_none_input(self):
        self.assertIsNone(sl._strip_provenance(None))


class TestBuildLlmPayload(unittest.TestCase):
    def test_no_raw_numbers_in_payload(self):
        ctx = {
            "forecast_dates": ["2026-05-17"],
            "lage_label": {"value": "Hochdrucklage", "decided_by": "x"},
            "pressure_influence": {"value": "Hochdruck", "trend": "stabil",
                                   "inputs": {"msl_by_day": [1023]}},
            "flow_overhead": {"value": "West", "strength": "schwach"},
            "t850_trend": {"value": "stabil"},
            "pressure_centers_per_day": [{
                "date": "2026-05-17",
                "centers": [{"type": "Hoch", "region_label": "Azoren",
                             "msl_hpa": 1027.0, "gradient_hpa": 12.9}],
            }],
            "bise": {"value": "nicht aktiv", "active_any_day": False},
            "vb_lage": {"value": "nicht aktiv"},
            "foehn": {"value": "nicht aktiv"},
            "precip_pattern": {"per_day": [{
                "date": "2026-05-17",
                "alpennord": {"value": "trocken"},
                "alpensued": {"value": "trocken"},
            }]},
            "schneefallgrenze": {"value": 2300, "per_day": []},
            "confidence_per_day": [{"date": "2026-05-17", "level": "high"}],
        }
        payload = sl._build_llm_payload(ctx)
        # Rohzahlen aus inputs sollten NICHT im Payload sein
        self.assertNotIn("msl_by_day", payload)
        # Center-Details (msl_hpa, gradient_hpa) auch nicht
        self.assertNotIn("1027", payload)
        self.assertNotIn("gradient_hpa", payload)
        # Aber das Lage-Label und der Druckeinfluss schon
        self.assertIn("Hochdrucklage", payload)
        self.assertIn("Hochdruck", payload)


class TestLabelVariants(unittest.TestCase):
    def test_simple_label(self):
        v = sl._label_variants("Schottland")
        self.assertIn("schottland", v)

    def test_slashed_label(self):
        v = sl._label_variants("Norditalien / Genua")
        self.assertIn("norditalien", v)
        self.assertIn("genua", v)


if __name__ == "__main__":
    unittest.main()
