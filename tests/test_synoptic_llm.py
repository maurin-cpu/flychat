"""Tests fuer engine/synoptic_llm.py — Validierung, Finalisierung, Payload.

Deckt Halluzinations-Schutz und den Korrektur-Loop-Vertrag ab:
  - _validate erkennt Verbotsbegriffe, erfundene Regionen, Schema-Fehler,
    fehlende flight_hints, Foehn-Lee-Inversionen — und liefert eine
    Fehlerliste (loescht selbst NICHTS)
  - _finalize baut das Kompatibilitaets-Format (short/long/long_with_sources),
    setzt Wochentag-Praefixe autoritativ, prune=True entfernt chirurgisch
  - Provenance wird vor LLM-Uebergabe gestrippt

LLM-Calls selbst werden NICHT getestet (Integration).
"""
import unittest

import config
from engine import synoptic_llm as sl


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


def _parsed(lead="Ruhige Hochdrucklage praegt die Tage.", days=None, n_days=2):
    if days is None:
        days = [{"text": f"Tag {i+1} stabil und sonnig.",
                 "flight_hint": "Gute Thermik erwartet."} for i in range(n_days)]
    return {"lead": lead, "days": days}


class TestValidate(unittest.TestCase):
    def test_accept_clean_output(self):
        errors = sl._validate(_parsed(), _ctx())
        self.assertEqual(errors, [])

    def test_reject_kaltfront_in_lead(self):
        errors = sl._validate(_parsed(lead="Eine Kaltfront zieht durch."), _ctx())
        self.assertTrue(any(e["kind"] == "forbidden_term" and e["scope"] == "lead"
                            for e in errors))

    def test_reject_hpa_value_in_day(self):
        days = [{"text": "Der Druck steigt auf 1025 hPa.",
                 "flight_hint": "Ruhiger Tag."},
                {"text": "Stabil.", "flight_hint": "Gut fliegbar."}]
        errors = sl._validate(_parsed(days=days), _ctx())
        self.assertTrue(any(e["kind"] == "forbidden_term"
                            and e["scope"] == "days[0]" for e in errors))

    def test_reject_trog_and_geopotential(self):
        errors = sl._validate(
            _parsed(lead="Das Geopotential zeigt einen Trog."), _ctx())
        self.assertTrue(any(e["kind"] == "forbidden_term" for e in errors))

    def test_reject_invalid_region(self):
        # "Island" ist im Grid, aber NICHT detektiert
        errors = sl._validate(
            _parsed(lead="Ein Hoch ueber Island setzt sich durch."), _ctx())
        self.assertTrue(any(e["kind"] == "invalid_region" for e in errors))

    def test_accept_valid_region(self):
        errors = sl._validate(
            _parsed(lead="Ein Hoch ueber den Azoren reicht zur Schweiz."),
            _ctx(centers=("Azoren",)))
        self.assertEqual(errors, [])

    def test_reject_missing_lead(self):
        errors = sl._validate({"days": _parsed()["days"]}, _ctx())
        self.assertTrue(any(e["scope"] == "lead" and e["kind"] == "schema"
                            for e in errors))

    def test_reject_day_count_mismatch(self):
        errors = sl._validate(_parsed(n_days=1), _ctx())
        self.assertTrue(any(e["scope"] == "days" and e["kind"] == "schema"
                            for e in errors))

    def test_reject_missing_flight_hint(self):
        days = [{"text": "Stabil und sonnig."},
                {"text": "Weiter stabil.", "flight_hint": "Gut fliegbar."}]
        errors = sl._validate(_parsed(days=days), _ctx())
        self.assertTrue(any(e["scope"] == "days[0]" and e["kind"] == "schema"
                            for e in errors))

    def test_reject_lead_too_long(self):
        errors = sl._validate(_parsed(lead="Wort " * 200), _ctx())
        self.assertTrue(any(e["kind"] == "too_long" for e in errors))

    def test_reject_praise_on_blown_out_day(self):
        ctx = _ctx()
        ctx["wind_pattern"] = {"per_day": [
            {"date": "2026-07-05",
             "alpennord": {"wind_class": "verblasen"},
             "alpensued": {"wind_class": "stark_eingeschraenkt"}},
            {"date": "2026-07-06",
             "alpennord": {"wind_class": "unauffaellig"},
             "alpensued": {"wind_class": "unauffaellig"}},
        ]}
        days = [{"text": "Sonnig und trocken.",
                 "flight_hint": "Gute Flugbedingungen, ideal für XC."},
                {"text": "Stabil.", "flight_hint": "Gut fliegbar."}]
        errors = sl._validate(_parsed(days=days), ctx)
        self.assertTrue(any(e["kind"] == "wind_contradiction"
                            and e["scope"] == "days[0]" for e in errors))
        # Tag 2 ist unauffaellig — Lob dort erlaubt
        self.assertFalse(any(e["kind"] == "wind_contradiction"
                             and e["scope"] == "days[1]" for e in errors))

    def test_praise_allowed_when_one_side_ok(self):
        ctx = _ctx()
        ctx["wind_pattern"] = {"per_day": [
            {"date": "2026-07-05",
             "alpennord": {"wind_class": "verblasen"},
             "alpensued": {"wind_class": "unauffaellig"}},
            {"date": "2026-07-06",
             "alpennord": {"wind_class": "windig"},
             "alpensued": {"wind_class": "windig"}},
        ]}
        days = [{"text": "Nordseite verblasen, Tessin ideal.",
                 "flight_hint": "Suedseite gute Flugbedingungen."},
                {"text": "Stabil.", "flight_hint": "Gut fliegbar."}]
        errors = sl._validate(_parsed(days=days), ctx)
        self.assertFalse(any(e["kind"] == "wind_contradiction" for e in errors))

    def test_reject_foehn_lee_inversion(self):
        foehn = {"per_day": [
            {"date": "2026-07-05", "nord_active": False, "sued_active": False},
            {"date": "2026-07-06", "nord_active": True, "sued_active": False},
        ]}
        days = [{"text": "Stabil.", "flight_hint": "Gut fliegbar."},
                {"text": "Das Tessin bleibt windgeschuetzt und ruhig.",
                 "flight_hint": "Gut fliegbar."}]
        errors = sl._validate(_parsed(days=days), _ctx(foehn=foehn))
        self.assertTrue(any(e["kind"] == "foehn_lee_inversion"
                            and e["scope"] == "days[1]" for e in errors))


class TestFinalize(unittest.TestCase):
    def test_compat_format_and_weekday_prefixes(self):
        out = sl._finalize(_parsed(), _ctx(), attempts=1, unresolved=[])
        self.assertEqual(out["short"], "Ruhige Hochdrucklage praegt die Tage.")
        self.assertEqual(len(out["long_with_sources"]), 2)
        # 2026-07-05 = Sonntag, 2026-07-06 = Montag — autoritativ gesetzt
        self.assertTrue(out["long_with_sources"][0]["text"].startswith("Sonntag: "))
        self.assertTrue(out["long_with_sources"][1]["text"].startswith("Montag: "))
        self.assertEqual(out["attempts"], 1)
        self.assertEqual(out["unresolved"], [])

    def test_wrong_prefix_corrected(self):
        days = [{"text": "Heute: stabil.", "flight_hint": "Gut."},
                {"text": "Dienstag: stabil.", "flight_hint": "Gut."}]
        out = sl._finalize(_parsed(days=days), _ctx(), attempts=1, unresolved=[])
        self.assertTrue(out["long_with_sources"][0]["text"].startswith("Sonntag: "))
        self.assertTrue(out["long_with_sources"][1]["text"].startswith("Montag: "))

    def test_parenthetical_and_stacked_prefixes_stripped(self):
        # Der 05.07.-Fall: LLM schrieb "Sonntag (Sunday):" → frueher wurde
        # "Sonntag: " nochmal davor gesetzt. Auch gestapelte + EN-Praefixe.
        days = [{"text": "Sonntag (Sunday): High pressure settles in.",
                 "flight_hint": "Gut."},
                {"text": "Montag: Montag (Monday): A foehn affects the south.",
                 "flight_hint": "Gut."}]
        out = sl._finalize(_parsed(days=days), _ctx(), attempts=1, unresolved=[])
        self.assertEqual(out["long_with_sources"][0]["text"],
                         "Sonntag: High pressure settles in.")
        self.assertEqual(out["long_with_sources"][1]["text"],
                         "Montag: A foehn affects the south.")

    def test_english_prefix_replaced(self):
        days = [{"text": "Sunday: sunny.", "flight_hint": "Gut."},
                {"text": "Tomorrow: windy.", "flight_hint": "Gut."}]
        out = sl._finalize(_parsed(days=days), _ctx(), attempts=1, unresolved=[])
        self.assertEqual(out["long_with_sources"][0]["text"], "Sonntag: sunny.")
        self.assertEqual(out["long_with_sources"][1]["text"], "Montag: windy.")

    def test_prune_removes_violating_day_keeps_rest(self):
        days = [{"text": "Eine Kaltfront zieht durch.", "flight_hint": "Gut."},
                {"text": "Stabil und sonnig.", "flight_hint": "Gut fliegbar."}]
        out = sl._finalize(_parsed(days=days), _ctx(), attempts=3,
                           unresolved=[sl._verr("days[0]", "forbidden_term", "x")],
                           prune=True)
        self.assertEqual(len(out["long_with_sources"]), 1)
        # Der ueberlebende Eintrag behaelt seinen korrekten Wochentag (Montag)
        self.assertTrue(out["long_with_sources"][0]["text"].startswith("Montag: "))
        self.assertEqual(len(out["unresolved"]), 1)

    def test_prune_strips_bad_hint_keeps_entry(self):
        days = [{"text": "Stabil.", "flight_hint": "Kaltfront beachten."},
                {"text": "Sonnig.", "flight_hint": "Gut fliegbar."}]
        out = sl._finalize(_parsed(days=days), _ctx(), attempts=3,
                           unresolved=[], prune=True)
        self.assertEqual(len(out["long_with_sources"]), 2)
        self.assertNotIn("flight_hint", out["long_with_sources"][0])
        self.assertEqual(out["long_with_sources"][1]["flight_hint"],
                         "Gut fliegbar.")

    def test_all_invalid_returns_none(self):
        days = [{"text": "Kaltfront!", "flight_hint": "x"}]
        out = sl._finalize({"lead": "Trog ueber Europa.", "days": days},
                           _ctx(dates=("2026-07-05",)), attempts=3,
                           unresolved=[], prune=True)
        self.assertIsNone(out)


class TestCorrectionMessage(unittest.TestCase):
    def test_contains_errors_and_keywords(self):
        errors = [sl._verr("lead", "forbidden_term", "enthaelt Kaltfront"),
                  sl._verr("days[2]", "schema", "flight_hint fehlt")]
        msg = sl._build_correction_message(errors)
        self.assertIn("KORREKTUR NOETIG", msg)
        self.assertIn("CORRECTION REQUIRED", msg)
        self.assertIn("[lead]", msg)
        self.assertIn("[days[2]]", msg)
        self.assertIn("KOMPLETTE JSON", msg)


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
                "alpennord": {"peak_mm": 0.0, "wet_share": 0.0,
                              "max_cape": 100, "max_coverage": 0.0, "n_spots": 50},
                "alpensued": {"peak_mm": 0.0, "wet_share": 0.0,
                              "max_cape": 80, "max_coverage": 0.0, "n_spots": 30},
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


class TestPayloadPrecipRawValues(unittest.TestCase):
    """Pure-LLM-Variante: precip_pattern uebergibt Rohwerte (peak_mm,
    wet_share, max_cape, max_coverage), KEINE deterministische Klassifikation."""

    def test_payload_has_raw_precip_values(self):
        ctx = {
            "forecast_dates": ["2026-05-17"],
            "precip_pattern": {"per_day": [{
                "date": "2026-05-17",
                "alpennord": {"peak_mm": 3.2, "wet_share": 0.04,
                              "max_cape": 2300, "max_coverage": 0.67,
                              "n_spots": 50},
                "alpensued": {"peak_mm": 0.0, "wet_share": 0.0,
                              "max_cape": 80, "max_coverage": 0.0,
                              "n_spots": 30},
            }]},
        }
        payload = sl._build_llm_payload(ctx)
        # Rohwerte muessen drin sein
        self.assertIn("peak_mm", payload)
        self.assertIn("wet_share", payload)
        self.assertIn("max_cape", payload)
        # Konkrete Werte
        self.assertIn("3.2", payload)
        self.assertIn("2300", payload)
        # KEIN char-Feld mehr
        self.assertNotIn('"char"', payload)
        self.assertNotIn('"value"', payload.split("precip_pattern")[1] if "precip_pattern" in payload else "")


if __name__ == "__main__":
    unittest.main()
