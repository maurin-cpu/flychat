"""Tests fuer engine/decision_engine.py — Stage-Inversion-Pipeline.

Deckt ab:
  - Foehn (compute_foehn_decision + apply_foehn_decision)
  - Wind-OK=0
  - Aloft-NotSafe / Aloft-Conditional
  - Gust-Floor
  - Overclaim-Relax (DEMOTIERT not_safe → conditional)
  - Wind-Strong-Mehrheit (Region)
  - Flyability-Downgrade / Upgrade / Region-Gate
"""
import unittest

from engine.decision_engine import (
    FoehnDecision,
    compute_foehn_decision,
    apply_foehn_decision,
    FOEHN_KEYWORDS,
    decide_wind_ok_zero,
    decide_aloft_not_safe,
    decide_aloft_conditional,
    decide_gust_floor,
    decide_overclaim_relax,
    decide_wind_strong_majority,
    decide_flyability_downgrade,
    decide_flyability_upgrade,
    decide_flyability_region_gate,
)


class TestComputeFoehnDecision(unittest.TestCase):
    def test_empty_eval_returns_none(self):
        d = compute_foehn_decision({})
        self.assertEqual(d.risk, "none")
        self.assertIsNone(d.forces_status)
        self.assertIsNone(d.caution_note)
        self.assertIsNone(d.no_go_reason)

    def test_level_none_returns_none(self):
        d = compute_foehn_decision({"level": "none", "delta_p_hpa": 1.2, "direction": "Süd"})
        self.assertEqual(d.risk, "none")
        self.assertIsNone(d.forces_status)

    def test_level_none_irrelevant_direction(self):
        # Format: _format_foehn_info setzt level="none", obwohl Foehn aktiv ist,
        # wenn die Richtung fuer den Standort irrelevant ist.
        d = compute_foehn_decision({"level": "none", "delta_p_hpa": 4.5, "direction": "Nord"})
        self.assertEqual(d.risk, "none")
        self.assertIsNone(d.forces_status)
        # delta_p + direction werden trotzdem fuer Logging mitgegeben
        self.assertEqual(d.delta_p_hpa, 4.5)
        self.assertEqual(d.direction, "Nord")

    def test_level_caution_returns_moderate(self):
        d = compute_foehn_decision({"level": "caution", "delta_p_hpa": 4.5, "direction": "Süd"})
        self.assertEqual(d.risk, "moderate")
        self.assertEqual(d.forces_status, "conditional_min")
        self.assertIsNotNone(d.caution_note)
        self.assertIn("4.5", d.caution_note)
        self.assertIn("Süd", d.caution_note)
        self.assertIsNone(d.no_go_reason)

    def test_level_danger_returns_high(self):
        d = compute_foehn_decision({"level": "danger", "delta_p_hpa": 9.5, "direction": "Süd"})
        self.assertEqual(d.risk, "high")
        self.assertEqual(d.forces_status, "not_safe")
        self.assertIsNotNone(d.no_go_reason)
        self.assertEqual(d.primary_no_go, "FOEHN")
        self.assertIsNone(d.caution_note)


class TestApplyFoehnDecision(unittest.TestCase):
    def _baseline_result(self):
        return {
            "safety_status": "safe",
            "safe_window": "10:00-16:00",
            "foehn_risk": "none",
            "caution_notes": [],
            "no_go_reasons": [],
            "primary_no_go": None,
        }

    def test_caution_lifts_safe_to_conditional(self):
        result = self._baseline_result()
        d = compute_foehn_decision({"level": "caution", "delta_p_hpa": 4.5, "direction": "Süd"})
        tag = apply_foehn_decision(result, d)
        self.assertEqual(result["safety_status"], "conditional")
        self.assertEqual(result["foehn_risk"], "moderate")
        self.assertEqual(len(result["caution_notes"]), 1)
        self.assertIn("4.5", result["caution_notes"][0])
        self.assertEqual(tag, "FoehnCaution(4.5)")

    def test_caution_does_not_demote_not_safe(self):
        result = self._baseline_result()
        result["safety_status"] = "not_safe"
        result["safe_window"] = "keins"
        d = compute_foehn_decision({"level": "caution", "delta_p_hpa": 5.0, "direction": "Süd"})
        apply_foehn_decision(result, d)
        # Status bleibt not_safe, da forces_status="conditional_min" nur ANHEBT
        self.assertEqual(result["safety_status"], "not_safe")
        self.assertEqual(result["foehn_risk"], "moderate")

    def test_danger_overrides_safe_to_not_safe(self):
        result = self._baseline_result()
        d = compute_foehn_decision({"level": "danger", "delta_p_hpa": 10, "direction": "Süd"})
        tag = apply_foehn_decision(result, d)
        self.assertEqual(result["safety_status"], "not_safe")
        self.assertEqual(result["foehn_risk"], "high")
        self.assertEqual(result["primary_no_go"], "FOEHN")
        self.assertEqual(result["safe_window"], "keins")
        self.assertEqual(len(result["no_go_reasons"]), 1)
        self.assertIn("10", result["no_go_reasons"][0])
        self.assertEqual(tag, "FoehnDanger(10)")

    def test_none_clears_foehn_risk(self):
        # LLM hatte foehn_risk="moderate" + caution_note geschrieben — Decision-Engine
        # bereinigt das, weil Cache "none" sagt (z.B. irrelevante Richtung).
        result = self._baseline_result()
        result["foehn_risk"] = "moderate"
        result["caution_notes"] = ["Foehn-Vorsicht: Delta-P 4.5 hPa erkannt"]
        d = compute_foehn_decision({"level": "none", "delta_p_hpa": 4.5, "direction": "Nord"})
        tag = apply_foehn_decision(result, d)
        self.assertEqual(result["foehn_risk"], "none")
        self.assertEqual(result["caution_notes"], [])
        self.assertIsNone(tag)

    def test_dedupes_llm_foehn_entries_before_inserting_canonical(self):
        # LLM hatte bereits eine eigene (nicht-kanonische) Foehn-Caution geschrieben.
        # Decision-Engine entfernt die LLM-Variante und ersetzt sie durch ihren eigenen Text.
        result = self._baseline_result()
        result["caution_notes"] = [
            "Achtung: Druckgradient von 4.5 hPa erkannt",  # LLM-Eintrag
            "Wind boeig nachmittags",  # nicht-Foehn, soll bleiben
        ]
        d = compute_foehn_decision({"level": "caution", "delta_p_hpa": 4.5, "direction": "Süd"})
        apply_foehn_decision(result, d)
        # Nicht-Foehn-Note bleibt erhalten
        self.assertIn("Wind boeig nachmittags", result["caution_notes"])
        # Genau eine Foehn-Note vorhanden, kanonisches Format
        foehn_notes = [n for n in result["caution_notes"] if any(k in n.lower() for k in FOEHN_KEYWORDS)]
        self.assertEqual(len(foehn_notes), 1)
        self.assertIn("Foehn-Vorsicht", foehn_notes[0])


class TestWindOkZero(unittest.TestCase):
    def _baseline(self):
        return {"safety_status": "safe", "safe_window": "10:00-16:00", "no_go_reasons": []}

    def test_fires_when_wind_ok_zero(self):
        result = self._baseline()
        tag = decide_wind_ok_zero(result, {"wind_ok_count": 0}, "X/Y")
        self.assertEqual(result["safety_status"], "not_safe")
        self.assertEqual(result["safe_window"], "keins")
        self.assertEqual(tag, "WindOk0")
        self.assertTrue(any("Windrichtung" in r for r in result["no_go_reasons"]))

    def test_does_not_fire_when_wind_ok_positive(self):
        result = self._baseline()
        tag = decide_wind_ok_zero(result, {"wind_ok_count": 5}, "X/Y")
        self.assertIsNone(tag)
        self.assertEqual(result["safety_status"], "safe")

    def test_does_not_fire_when_already_not_safe(self):
        result = {"safety_status": "not_safe", "no_go_reasons": ["andere Begründung"]}
        tag = decide_wind_ok_zero(result, {"wind_ok_count": 0}, "X/Y")
        self.assertIsNone(tag)


class TestAloftDecisions(unittest.TestCase):
    def _baseline(self):
        return {
            "safety_status": "safe",
            "safe_window": "10:00-16:00",
            "caution_notes": [],
            "no_go_reasons": [],
            "primary_no_go": None,
        }

    def test_aloft_not_safe_fires_at_threshold(self):
        result = self._baseline()
        gust_info = {"aloft_danger_hours": 6, "aloft_pattern": None}  # 6 ≥ default 4
        tag = decide_aloft_not_safe(result, gust_info, "X/Y")
        self.assertEqual(result["safety_status"], "not_safe")
        self.assertEqual(result["primary_no_go"], "ALOFT_DANGER")
        self.assertTrue(tag.startswith("AloftNotSafe"))

    def test_aloft_not_safe_pattern_durchgehend_danger(self):
        result = self._baseline()
        gust_info = {"aloft_danger_hours": 1, "aloft_pattern": {"pattern_label": "DURCHGEHEND_DANGER", "max_calm_gap": 0}}
        tag = decide_aloft_not_safe(result, gust_info, "X/Y")
        self.assertEqual(result["safety_status"], "not_safe")
        self.assertTrue(tag is not None)

    def test_aloft_conditional_fires_when_safe(self):
        result = self._baseline()
        gust_info = {"aloft_danger_hours": 3, "aloft_gust_danger_hours": 0, "aloft_pattern": None}
        tag = decide_aloft_conditional(result, gust_info, "X/Y")
        self.assertEqual(result["safety_status"], "conditional")
        self.assertEqual(len(result["caution_notes"]), 1)
        self.assertTrue(tag.startswith("AloftConditional"))

    def test_aloft_conditional_skips_when_already_conditional(self):
        result = self._baseline()
        result["safety_status"] = "conditional"
        gust_info = {"aloft_danger_hours": 3, "aloft_gust_danger_hours": 0, "aloft_pattern": None}
        tag = decide_aloft_conditional(result, gust_info, "X/Y")
        self.assertIsNone(tag)


class TestGustFloor(unittest.TestCase):
    def test_fires_at_threshold(self):
        result = {"safety_status": "safe", "caution_notes": []}
        gust_info = {
            "gust_warn_hours": 5, "aloft_gust_warn_hours": 0,
            "gust_danger_hours": 0, "aloft_gust_danger_hours": 0,
            "max_surface_gust": 35,
        }
        tag = decide_gust_floor(result, gust_info, "X/Y")
        self.assertEqual(result["safety_status"], "conditional")
        self.assertEqual(tag, "GustFloor")
        self.assertTrue(any("Boeen" in n for n in result["caution_notes"]))

    def test_skips_below_threshold(self):
        result = {"safety_status": "safe", "caution_notes": []}
        gust_info = {
            "gust_warn_hours": 1, "aloft_gust_warn_hours": 0,
            "gust_danger_hours": 0, "aloft_gust_danger_hours": 0,
            "max_surface_gust": 25,
        }
        tag = decide_gust_floor(result, gust_info, "X/Y")
        self.assertIsNone(tag)


class TestOverclaimRelax(unittest.TestCase):
    def test_demotes_not_safe_to_conditional(self):
        result = {
            "safety_status": "not_safe",
            "no_go_reasons": ["ueberzogene LLM-Begruendung"],
            "caution_notes": [],
        }
        gust_info = {"hard_warning_hours": 0, "clean_hours_count": 6}
        tag = decide_overclaim_relax(result, gust_info, "X/Y")
        self.assertEqual(result["safety_status"], "conditional")
        self.assertEqual(result["no_go_reasons"], [])
        self.assertTrue(any("Automatische Korrektur" in n for n in result["caution_notes"]))
        self.assertTrue(tag.startswith("OverclaimRelax"))

    def test_skips_when_hard_warnings_exist(self):
        result = {"safety_status": "not_safe", "no_go_reasons": [], "caution_notes": []}
        gust_info = {"hard_warning_hours": 2, "clean_hours_count": 6}
        tag = decide_overclaim_relax(result, gust_info, "X/Y")
        self.assertIsNone(tag)
        self.assertEqual(result["safety_status"], "not_safe")

    def test_skips_when_too_few_clean_hours(self):
        result = {"safety_status": "not_safe", "no_go_reasons": [], "caution_notes": []}
        gust_info = {"hard_warning_hours": 0, "clean_hours_count": 3}
        tag = decide_overclaim_relax(result, gust_info, "X/Y")
        self.assertIsNone(tag)


class TestRegionDecisions(unittest.TestCase):
    def test_wind_strong_majority_fires(self):
        result = {
            "safety_status": "safe",
            "wind_strong_count": 5, "wind_calm_count": 0, "wind_moderate_count": 2,
            "no_go_reasons": [],
        }
        tag = decide_wind_strong_majority(result, "Region/Y")
        self.assertEqual(result["safety_status"], "not_safe")
        self.assertTrue(tag.startswith("WindStrongMajority"))

    def test_wind_strong_majority_skips_with_calm(self):
        result = {
            "safety_status": "safe",
            "wind_strong_count": 5, "wind_calm_count": 1, "wind_moderate_count": 2,
            "no_go_reasons": [],
        }
        tag = decide_wind_strong_majority(result, "Region/Y")
        self.assertIsNone(tag)


class TestFlyabilityDecisions(unittest.TestCase):
    def test_downgrade_no_thermals(self):
        result = {"flyability_tier": "green", "fly_status": "green"}
        tq = {"thermal_hours_total": 0, "rough_danger_h": 0, "peak_climb_proxy": 0, "productive_thermal_h": 0}
        tag = decide_flyability_downgrade(result, tq, "X/Y")
        self.assertEqual(result["flyability_tier"], "gray")
        self.assertTrue(tag.startswith("FlyabilityDowngrade"))

    def test_downgrade_rough_majority(self):
        result = {"flyability_tier": "green", "fly_status": "green"}
        tq = {"thermal_hours_total": 6, "rough_danger_h": 4, "peak_climb_proxy": 1.5, "productive_thermal_h": 4}
        tag = decide_flyability_downgrade(result, tq, "X/Y")
        self.assertEqual(result["flyability_tier"], "gray")
        self.assertTrue(tag.startswith("FlyabilityDowngrade"))

    def test_downgrade_skips_when_data_ok(self):
        result = {"flyability_tier": "green", "fly_status": "green"}
        tq = {"thermal_hours_total": 6, "rough_danger_h": 1, "peak_climb_proxy": 1.5, "productive_thermal_h": 5}
        tag = decide_flyability_downgrade(result, tq, "X/Y")
        self.assertIsNone(tag)

    def test_upgrade_gray_to_green(self):
        result = {"flyability_tier": "gray", "fly_status": "gray"}
        tq = {"thermal_hours_total": 6, "rough_danger_h": 1, "peak_climb_proxy": 1.8, "productive_thermal_h": 5}
        tag = decide_flyability_upgrade(result, tq, "X/Y")
        self.assertEqual(result["flyability_tier"], "green")
        self.assertEqual(result["peak_climb_rate"], 1.8)
        self.assertEqual(result["flight_type"], "Thermikflug")
        self.assertTrue(tag.startswith("FlyabilityUpgrade"))

    def test_upgrade_skips_when_already_green(self):
        result = {"flyability_tier": "green", "fly_status": "green"}
        tq = {"thermal_hours_total": 6, "rough_danger_h": 0, "peak_climb_proxy": 1.5, "productive_thermal_h": 5}
        tag = decide_flyability_upgrade(result, tq, "X/Y")
        self.assertIsNone(tag)

    def test_region_gate_violet_to_green(self):
        result = {"flyability_tier": "violet", "fly_status": "violet"}
        region_result = {"flyability_tier": "green", "region": "Mittelland"}
        tag = decide_flyability_region_gate(result, region_result, "X/Y")
        self.assertEqual(result["flyability_tier"], "green")
        self.assertEqual(tag, "FlyabilityRegionGate(violet→green)")

    def test_region_gate_keeps_violet_when_region_violet(self):
        result = {"flyability_tier": "violet", "fly_status": "violet"}
        region_result = {"flyability_tier": "violet", "region": "Mittelland"}
        tag = decide_flyability_region_gate(result, region_result, "X/Y")
        self.assertIsNone(tag)
        self.assertEqual(result["flyability_tier"], "violet")

    def test_region_gate_no_region(self):
        result = {"flyability_tier": "violet", "fly_status": "violet"}
        tag = decide_flyability_region_gate(result, None, "X/Y")
        self.assertIsNone(tag)


if __name__ == "__main__":
    unittest.main()
