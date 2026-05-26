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


class TestFilterDryDayPrecipClaims(unittest.TestCase):
    """Dry-day-Strip: bei `char == "trocken"` beidseitig sind Niederschlags-
    Begriffe im LLM-Output verboten. Decision-Layer ist autoritativ."""

    def setUp(self):
        self.forecast_dates = ["2026-05-25", "2026-05-26", "2026-05-27"]
        self.precip_dry = {"per_day": [
            {"date": "2026-05-25",
             "alpennord": {"value": "trocken"},
             "alpensued": {"value": "trocken"}},
            {"date": "2026-05-26",
             "alpennord": {"value": "trocken"},
             "alpensued": {"value": "trocken"}},
            {"date": "2026-05-27",
             "alpennord": {"value": "trocken"},
             "alpensued": {"value": "trocken"}},
        ]}

    def test_drops_text_with_schauer_on_dry_day(self):
        statements = [
            {"text": "Montag: stabil, vereinzelt Schauer beidseits.",
             "sources": ["precip_pattern.alpennord"]},
            {"text": "Dienstag: sonnig und trocken.",
             "sources": ["pressure_influence"]},
            {"text": "Mittwoch: Hochdruck haelt.",
             "sources": ["pressure_influence"]},
        ]
        out = sl._filter_dry_day_precip_claims(
            statements, self.precip_dry, self.forecast_dates,
        )
        self.assertEqual(len(out), 2)
        self.assertNotIn("Schauer", out[0]["text"])

    def test_drops_text_with_gewitter_on_dry_day(self):
        statements = [
            {"text": "Montag: Hochdrucklage, lokale Gewitter moeglich.",
             "sources": ["precip_pattern.alpennord"]},
        ]
        out = sl._filter_dry_day_precip_claims(
            statements, self.precip_dry, self.forecast_dates,
        )
        self.assertEqual(out, [])

    def test_drops_text_with_regen_on_dry_day(self):
        statements = [
            {"text": "Montag: trocken, aber etwas Regen am Abend.",
             "sources": ["precip_pattern.alpennord"]},
        ]
        out = sl._filter_dry_day_precip_claims(
            statements, self.precip_dry, self.forecast_dates,
        )
        self.assertEqual(out, [])

    def test_drops_flight_hint_but_keeps_entry(self):
        statements = [
            {"text": "Montag: stabil und sonnig.",
             "sources": ["pressure_influence"],
             "flight_hint": "Thermiktag, nur lokale Schauer beachten."},
        ]
        out = sl._filter_dry_day_precip_claims(
            statements, self.precip_dry, self.forecast_dates,
        )
        self.assertEqual(len(out), 1)
        self.assertNotIn("flight_hint", out[0])

    def test_keeps_clean_text_and_hint(self):
        statements = [
            {"text": "Montag: stabil und sonnig.",
             "sources": ["pressure_influence"],
             "flight_hint": "Stabiler Thermiktag mit guten Steigwerten."},
        ]
        out = sl._filter_dry_day_precip_claims(
            statements, self.precip_dry, self.forecast_dates,
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["flight_hint"], "Stabiler Thermiktag mit guten Steigwerten.")

    def test_keeps_shower_text_on_wet_day(self):
        precip_wet = {"per_day": [
            {"date": "2026-05-25",
             "alpennord": {"value": "Schauer"},
             "alpensued": {"value": "trocken"}},
        ]}
        statements = [
            {"text": "Montag: vereinzelte Schauer auf der Alpennordseite.",
             "sources": ["precip_pattern.alpennord"]},
        ]
        out = sl._filter_dry_day_precip_claims(
            statements, precip_wet, ["2026-05-25"],
        )
        self.assertEqual(len(out), 1)

    def test_keeps_shower_text_on_one_dry_one_wet(self):
        # Nur eine Seite trocken — Strip greift nicht
        precip_mixed = {"per_day": [
            {"date": "2026-05-25",
             "alpennord": {"value": "trocken"},
             "alpensued": {"value": "Gewitter wahrscheinlich"}},
        ]}
        statements = [
            {"text": "Montag: Alpennord trocken, im Tessin lokale Gewitter.",
             "sources": ["precip_pattern.alpensued"]},
        ]
        out = sl._filter_dry_day_precip_claims(
            statements, precip_mixed, ["2026-05-25"],
        )
        self.assertEqual(len(out), 1)

    def test_word_boundary_does_not_strip_segen(self):
        # "Regen" als Wort matchen, "Regentag" auch — aber "Segen" nicht
        statements = [
            {"text": "Montag: ein Segen fuer Piloten, stabile Lage.",
             "sources": ["pressure_influence"]},
        ]
        out = sl._filter_dry_day_precip_claims(
            statements, self.precip_dry, self.forecast_dates,
        )
        self.assertEqual(len(out), 1)


class TestFilterDryWeekShort(unittest.TestCase):
    """short-Block-Strip: wenn ALLE Tage beidseitig trocken sind,
    pauschal Niederschlags-Saetze droppen."""

    def test_drops_shower_in_short_when_all_dry(self):
        precip_all_dry = {"per_day": [
            {"date": "2026-05-25",
             "alpennord": {"value": "trocken"},
             "alpensued": {"value": "trocken"}},
            {"date": "2026-05-26",
             "alpennord": {"value": "trocken"},
             "alpensued": {"value": "trocken"}},
        ]}
        statements = [
            {"text": "Hochdrucklage mit Westwind.", "sources": ["pressure_influence"]},
            {"text": "Vereinzelt Schauer auf beiden Alpenseiten.",
             "sources": ["precip_pattern.alpennord"]},
            {"text": "Donnerstag und Freitag die Highlights.",
             "sources": ["pressure_influence"]},
        ]
        out = sl._filter_dry_week_short(statements, precip_all_dry)
        self.assertEqual(len(out), 2)
        self.assertNotIn("Schauer", " ".join(s["text"] for s in out))

    def test_keeps_short_when_one_day_wet(self):
        precip_mixed = {"per_day": [
            {"date": "2026-05-25",
             "alpennord": {"value": "trocken"},
             "alpensued": {"value": "trocken"}},
            {"date": "2026-05-26",
             "alpennord": {"value": "Schauer"},
             "alpensued": {"value": "trocken"}},
        ]}
        statements = [
            {"text": "Vereinzelt Schauer auf der Alpennordseite Dienstag.",
             "sources": ["precip_pattern.alpennord"]},
        ]
        out = sl._filter_dry_week_short(statements, precip_mixed)
        self.assertEqual(len(out), 1)

    def test_empty_per_day_keeps_statements(self):
        # Keine per_day-Daten → kein Strip
        precip_empty = {"per_day": []}
        statements = [
            {"text": "Schauer moeglich.", "sources": ["precip_pattern.alpennord"]},
        ]
        out = sl._filter_dry_week_short(statements, precip_empty)
        self.assertEqual(len(out), 1)


class TestIsDryBothSides(unittest.TestCase):
    def test_both_dry(self):
        self.assertTrue(sl._is_dry_both_sides({
            "alpennord": {"value": "trocken"},
            "alpensued": {"value": "trocken"},
        }))

    def test_one_wet(self):
        self.assertFalse(sl._is_dry_both_sides({
            "alpennord": {"value": "Schauer"},
            "alpensued": {"value": "trocken"},
        }))

    def test_none_input(self):
        self.assertFalse(sl._is_dry_both_sides(None))

    def test_missing_keys(self):
        self.assertFalse(sl._is_dry_both_sides({}))


if __name__ == "__main__":
    unittest.main()
