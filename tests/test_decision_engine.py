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
    decide_is_conditional,
    decide_wind_strong_majority,
    decide_flyability_low_reward,
    decide_flyability_mech_danger,
    decide_flyability_upgrade,
    decide_flyability_region_gate,
    compute_safety_band,
)
from engine._common import (
    _compute_experience_score,
    _compute_experience_stars,
    _compute_safety_rating,
    _compute_safety_score,
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
    # ── Low-Reward (Sub-Trigger A: keine Thermik, C: zu wenig produktiv) ──
    def test_low_reward_no_thermals(self):
        # Sub-Trigger A: peak < 0.3 ODER thermal_hours_total == 0
        result = {"flyability_tier": "green", "fly_status": "green",
                  "safety_status": "safe", "caution_notes": []}
        tq = {"thermal_hours_total": 0, "rough_danger_h": 0,
              "peak_climb_proxy": 0, "productive_thermal_h": 0}
        tag = decide_flyability_low_reward(result, tq, "X/Y")
        self.assertEqual(result["flyability_tier"], "gray")
        self.assertEqual(result["fly_status"], "gray")
        # Low-Reward darf safety NICHT anfassen
        self.assertEqual(result["safety_status"], "safe")
        self.assertEqual(result["caution_notes"], [])
        self.assertTrue(tag.startswith("FlyabilityLowReward"))
        self.assertIn("no_thermals", tag)

    def test_low_reward_low_productive(self):
        # Sub-Trigger C: prod_h < threshold, kein Rough-Problem
        result = {"flyability_tier": "green", "fly_status": "green",
                  "safety_status": "safe", "caution_notes": []}
        tq = {"thermal_hours_total": 6, "rough_danger_h": 1,
              "peak_climb_proxy": 1.5, "productive_thermal_h": 1}
        tag = decide_flyability_low_reward(result, tq, "X/Y")
        self.assertEqual(result["flyability_tier"], "gray")
        self.assertEqual(result["safety_status"], "safe")  # safety unangetastet
        self.assertTrue(tag.startswith("FlyabilityLowReward"))
        self.assertIn("low_productive", tag)

    def test_low_reward_skips_on_rough_majority(self):
        # rough_pct > 50 ist mech_danger-Domain, NICHT low_reward
        result = {"flyability_tier": "green", "fly_status": "green",
                  "safety_status": "safe", "caution_notes": []}
        tq = {"thermal_hours_total": 6, "rough_danger_h": 4,
              "peak_climb_proxy": 1.5, "productive_thermal_h": 4}
        tag = decide_flyability_low_reward(result, tq, "X/Y")
        self.assertIsNone(tag)
        self.assertEqual(result["flyability_tier"], "green")  # tier unveraendert

    def test_low_reward_skips_when_already_gray(self):
        result = {"flyability_tier": "gray", "fly_status": "gray",
                  "safety_status": "safe", "caution_notes": []}
        tq = {"thermal_hours_total": 0, "rough_danger_h": 0,
              "peak_climb_proxy": 0, "productive_thermal_h": 0}
        tag = decide_flyability_low_reward(result, tq, "X/Y")
        self.assertIsNone(tag)

    # ── Mech-Danger (Sub-Trigger B: rough_pct > 50, Safety-Achse) ──
    def test_mech_danger_fires_and_escalates_safety(self):
        # rough_pct = 4/6 ≈ 67% > 50 → flippt safety + setzt tier=gray
        result = {"flyability_tier": "green", "fly_status": "green",
                  "safety_status": "safe", "caution_notes": []}
        tq = {"thermal_hours_total": 6, "rough_danger_h": 4,
              "peak_climb_proxy": 1.5, "productive_thermal_h": 4}
        tag = decide_flyability_mech_danger(result, tq, "X/Y")
        # Cross-cutting: tier UND safety werden geaendert
        self.assertEqual(result["flyability_tier"], "gray")
        self.assertEqual(result["fly_status"], "gray")
        self.assertEqual(result["safety_status"], "conditional")
        self.assertTrue(any("Klappern" in n for n in result["caution_notes"]))
        self.assertTrue(tag.startswith("FlyabilityMechDanger"))

    def test_mech_danger_skips_at_boundary(self):
        # rough_pct = 50 exakt → kein Trigger (>50 ist Schwelle)
        result = {"flyability_tier": "green", "fly_status": "green",
                  "safety_status": "safe", "caution_notes": []}
        tq = {"thermal_hours_total": 6, "rough_danger_h": 3,
              "peak_climb_proxy": 1.5, "productive_thermal_h": 4}
        tag = decide_flyability_mech_danger(result, tq, "X/Y")
        self.assertIsNone(tag)
        self.assertEqual(result["safety_status"], "safe")

    def test_mech_danger_preserves_not_safe(self):
        # Bereits not_safe → mech_danger eskaliert nicht (kein Demote)
        result = {"flyability_tier": "gray", "fly_status": "gray",
                  "safety_status": "not_safe", "caution_notes": []}
        tq = {"thermal_hours_total": 6, "rough_danger_h": 4,
              "peak_climb_proxy": 1.5, "productive_thermal_h": 4}
        tag = decide_flyability_mech_danger(result, tq, "X/Y")
        # Tag wird trotzdem emittiert (caution_note relevant), aber safety bleibt
        self.assertEqual(result["safety_status"], "not_safe")

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


# ════════════════════════════════════════════════════════════════════
# Vorab-Fix #2: is_conditional deterministisch (RATING_CONCEPT v1.3, A2-Logik)
# ════════════════════════════════════════════════════════════════════
# A2-Logik:
#   - safety_status == "conditional"  → is_conditional = True  (Engine-Override)
#   - safety_status == "not_safe"     → is_conditional = False (Sanity-Clamp)
#   - safety_status == "safe"         → LLM behaelt Hand (Trigger 3+4 aus
#                                       _flyability_tiers.md: Wolkenbasis,
#                                       Hoehen-Turbulenz)
class TestIsConditional(unittest.TestCase):
    def _baseline(self, safety_status="safe", is_cond=False, reason=""):
        return {
            "safety_status": safety_status,
            "is_conditional": is_cond,
            "conditional_reason": reason,
        }

    def test_sets_true_when_safety_conditional(self):
        result = self._baseline(safety_status="conditional", is_cond=False)
        tag = decide_is_conditional(result, "X/Y")
        self.assertTrue(result["is_conditional"])
        self.assertTrue(tag.startswith("IsConditional"))

    def test_keeps_true_when_already_true_and_conditional(self):
        # LLM hat is_conditional bereits korrekt gesetzt — Decision idempotent
        result = self._baseline(safety_status="conditional", is_cond=True, reason="Foehn-Vorsicht")
        tag = decide_is_conditional(result, "X/Y")
        self.assertTrue(result["is_conditional"])
        self.assertEqual(result["conditional_reason"], "Foehn-Vorsicht")
        self.assertIsNone(tag)  # kein Tag — Engine hat nichts geaendert

    def test_clamps_false_on_not_safe(self):
        # LLM-Fehler: not_safe + is_conditional=True → Engine korrigiert
        result = self._baseline(safety_status="not_safe", is_cond=True, reason="LLM-Uebermut")
        tag = decide_is_conditional(result, "X/Y")
        self.assertFalse(result["is_conditional"])
        self.assertEqual(result["conditional_reason"], "")
        self.assertIsNone(tag)  # Clamp emittiert keinen Tag — ist nur Cleanup

    def test_no_change_on_not_safe_when_already_false(self):
        result = self._baseline(safety_status="not_safe", is_cond=False)
        tag = decide_is_conditional(result, "X/Y")
        self.assertFalse(result["is_conditional"])
        self.assertIsNone(tag)

    def test_safe_preserves_llm_true(self):
        # Trigger 3 (Wolkenbasis) oder 4 (Hoehen-Turbulenz): safety_status bleibt
        # safe, aber LLM flaggt Soft-Warnung. Engine darf NICHT ueberschreiben.
        result = self._baseline(safety_status="safe", is_cond=True, reason="tiefe Wolkenbasis")
        tag = decide_is_conditional(result, "X/Y")
        self.assertTrue(result["is_conditional"])
        self.assertEqual(result["conditional_reason"], "tiefe Wolkenbasis")
        self.assertIsNone(tag)

    def test_safe_preserves_llm_false(self):
        result = self._baseline(safety_status="safe", is_cond=False)
        tag = decide_is_conditional(result, "X/Y")
        self.assertFalse(result["is_conditional"])
        self.assertIsNone(tag)

    def test_idempotent_double_run(self):
        # Zweiter Aufruf darf keine Aenderung mehr emittieren
        result = self._baseline(safety_status="conditional", is_cond=False)
        tag1 = decide_is_conditional(result, "X/Y")
        tag2 = decide_is_conditional(result, "X/Y")
        self.assertTrue(result["is_conditional"])
        self.assertTrue(tag1.startswith("IsConditional"))
        self.assertIsNone(tag2)  # idempotent


# ════════════════════════════════════════════════════════════════════
# Vorab-Fix #3: experience_score + experience_stars (RATING_CONCEPT v1.3 §3.2)
# ════════════════════════════════════════════════════════════════════
# Skaliert das bestehende 0-10 rating × 10 → 0-100 experience_score, mappt
# auf 0-5 Sterne via Schwellen aus §8.3 (untere Stufe gewinnt am Grenzwert).
class TestExperienceScore(unittest.TestCase):
    # ── Score-Skalierung (rating × 10) ──
    def test_score_zero_when_rating_zero(self):
        self.assertEqual(_compute_experience_score(0.0), 0)

    def test_score_75_when_rating_7_5(self):
        self.assertEqual(_compute_experience_score(7.5), 75)

    def test_score_100_when_rating_10(self):
        self.assertEqual(_compute_experience_score(10.0), 100)

    def test_score_clamps_negative_and_overflow(self):
        self.assertEqual(_compute_experience_score(-1.0), 0)
        self.assertEqual(_compute_experience_score(11.0), 100)

    def test_score_handles_none_and_invalid(self):
        self.assertEqual(_compute_experience_score(None), 0)
        self.assertEqual(_compute_experience_score("invalid"), 0)

    # ── Sterne-Schwellen (§8.3, untere Stufe gewinnt) ──
    def test_stars_zero_at_boundary(self):
        self.assertEqual(_compute_experience_stars(0), 0)
        self.assertEqual(_compute_experience_stars(20), 0)  # 20 → 0★
        self.assertEqual(_compute_experience_stars(21), 1)  # 21 → 1★

    def test_stars_one_to_two_boundary(self):
        self.assertEqual(_compute_experience_stars(40), 1)  # 40 → 1★
        self.assertEqual(_compute_experience_stars(41), 2)  # 41 → 2★

    def test_stars_two_to_three_boundary(self):
        self.assertEqual(_compute_experience_stars(60), 2)  # 60 → 2★
        self.assertEqual(_compute_experience_stars(61), 3)  # 61 → 3★

    def test_stars_three_to_four_boundary(self):
        self.assertEqual(_compute_experience_stars(75), 3)  # 75 → 3★ (konservativ)
        self.assertEqual(_compute_experience_stars(76), 4)  # 76 → 4★

    def test_stars_four_to_five_boundary(self):
        self.assertEqual(_compute_experience_stars(89), 4)  # 89 → 4★
        self.assertEqual(_compute_experience_stars(90), 5)  # 90 → 5★

    def test_stars_at_max(self):
        self.assertEqual(_compute_experience_stars(100), 5)

    # ── Pipeline-Integration: not_safe Rating=0 → Score=0 → Stars=0 ──
    def test_not_safe_pipeline_yields_zero_stars(self):
        rating = 0.0  # _compute_rating_from_subratings forciert das bei not_safe
        score = _compute_experience_score(rating)
        stars = _compute_experience_stars(score)
        self.assertEqual(score, 0)
        self.assertEqual(stars, 0)


# ════════════════════════════════════════════════════════════════════
# Vorab-Fix #4: Safety-Sub-Ratings (RATING_CONCEPT v1.3 §3.5)
# ════════════════════════════════════════════════════════════════════
# Vier neue LLM-Sub-Ratings (wind/gust/aloft/foehn, je 1-10) werden
# deterministisch zu 0-10 safety_rating aggregiert (Gewichte 30/25/25/20)
# und × 10 zu safety_score (0-100).
class TestSafetyRating(unittest.TestCase):
    def _result(self, wind=5, gust=5, aloft=5, foehn=5, weather=5):
        return {
            "wind_safety_rating": wind,
            "gust_safety_rating": gust,
            "aloft_safety_rating": aloft,
            "foehn_safety_rating": foehn,
            "weather_safety_rating": weather,
        }

    # ── Weakest-Link-Aggregation (MIN) ──
    def test_all_mid_yields_5(self):
        self.assertEqual(_compute_safety_rating(self._result()), 5.0)

    def test_all_max_yields_10(self):
        self.assertEqual(_compute_safety_rating(self._result(10, 10, 10, 10, 10)), 10.0)

    def test_all_min_yields_1(self):
        self.assertEqual(_compute_safety_rating(self._result(1, 1, 1, 1, 1)), 1.0)

    def test_min_dominates_single_low_wind(self):
        # 4 perfekte Ratings + 1 niedriger Wind → score gefolgt vom niedrigsten
        self.assertEqual(_compute_safety_rating(self._result(2, 10, 10, 10, 10)), 2.0)

    def test_min_dominates_single_low_weather(self):
        # Klassischer Fall: Top-Wind, aber CAPE-WARN → safety = 2
        # Verhindert dass perfekter Wind ein Gewitter-Risiko "wegmittelt"
        self.assertEqual(_compute_safety_rating(self._result(9, 9, 9, 9, 2)), 2.0)

    def test_min_dominates_single_low_foehn(self):
        self.assertEqual(_compute_safety_rating(self._result(10, 10, 10, 3, 10)), 3.0)

    # ── Defaults bei fehlenden / ungueltigen Feldern ──
    def test_missing_fields_default_to_5(self):
        # Komplett leerer Result → Default 5 fuer jedes → MIN = 5
        self.assertEqual(_compute_safety_rating({}), 5.0)

    def test_invalid_field_falls_back_to_5(self):
        result = {"wind_safety_rating": "invalid", "gust_safety_rating": None,
                  "aloft_safety_rating": 5, "foehn_safety_rating": 5,
                  "weather_safety_rating": 5}
        # Invalid → 5, alle anderen 5 → MIN = 5
        self.assertEqual(_compute_safety_rating(result), 5.0)

    def test_partial_missing_takes_min(self):
        # nur weather=2, andere fehlen → defaults 5, MIN = 2
        self.assertEqual(_compute_safety_rating({"weather_safety_rating": 2}), 2.0)

    def test_clamp_below_one(self):
        # Werte < 1 werden auf 1 geclampt → MIN = 1
        self.assertEqual(_compute_safety_rating(self._result(0, 0, 0, 0, 0)), 1.0)

    def test_clamp_above_ten(self):
        # Werte > 10 werden auf 10 geclampt → MIN = 10
        self.assertEqual(_compute_safety_rating(self._result(15, 15, 15, 15, 15)), 10.0)

    # ── safety_score Skalierung ──
    def test_score_scaling(self):
        self.assertEqual(_compute_safety_score(0.0), 0)
        self.assertEqual(_compute_safety_score(5.0), 50)
        self.assertEqual(_compute_safety_score(7.5), 75)
        self.assertEqual(_compute_safety_score(10.0), 100)

    def test_score_clamps_invalid(self):
        self.assertEqual(_compute_safety_score(None), 0)
        self.assertEqual(_compute_safety_score("oops"), 0)
        self.assertEqual(_compute_safety_score(-5.0), 0)
        self.assertEqual(_compute_safety_score(15.0), 100)


# ════════════════════════════════════════════════════════════════════
# Phase 1: compute_safety_band (RATING_CONCEPT v1.3 §3.1)
# ════════════════════════════════════════════════════════════════════
# Hybrid: Decision-Engine-Hard-Overrides haben Vorrang vor safety_score.
# - safety_status="not_safe" oder FoehnDanger/AloftNotSafe → red
# - safety_status="conditional" oder FoehnCaution/GustFloor/AloftConditional → amber
# - sonst: safety_score-basierter Fallback (< 40 → amber, sonst green)
class TestSafetyBand(unittest.TestCase):
    def _result(self, status="safe", score=80, decisions=None, foehn_risk=0):
        return {
            "safety_status": status,
            "safety_score": score,
            "_decisions_applied": decisions or [],
            "foehn_risk": foehn_risk,
        }

    # ── Hard-Override → red ──
    def test_not_safe_status_yields_red(self):
        # safety_status=not_safe ist immer red, egal wie hoch score
        self.assertEqual(compute_safety_band(self._result(status="not_safe", score=100)), "red")

    def test_foehn_danger_yields_red(self):
        self.assertEqual(
            compute_safety_band(self._result(status="safe", score=90, decisions=["FoehnDanger(7.5)"])),
            "red"
        )

    def test_aloft_not_safe_yields_red(self):
        self.assertEqual(
            compute_safety_band(self._result(status="safe", score=90, decisions=["AloftNotSafe(45)"])),
            "red"
        )

    # ── Hard-Override → amber ──
    def test_conditional_status_yields_amber(self):
        # safety_status=conditional ist immer amber, egal wie hoch score
        self.assertEqual(compute_safety_band(self._result(status="conditional", score=85)), "amber")

    def test_foehn_caution_yields_amber(self):
        self.assertEqual(
            compute_safety_band(self._result(status="safe", score=85, decisions=["FoehnCaution(4.5)"])),
            "amber"
        )

    def test_high_foehn_risk_yields_amber(self):
        # foehn_risk >= 4.0 → amber auch ohne explizites Decision-Tag
        self.assertEqual(
            compute_safety_band(self._result(status="safe", score=85, foehn_risk=4.5)),
            "amber"
        )

    def test_gust_floor_yields_amber(self):
        self.assertEqual(
            compute_safety_band(self._result(status="safe", score=85, decisions=["GustFloor(3h)"])),
            "amber"
        )

    def test_aloft_conditional_yields_amber(self):
        self.assertEqual(
            compute_safety_band(self._result(status="safe", score=85, decisions=["AloftConditional(2h)"])),
            "amber"
        )

    def test_wind_strong_majority_yields_amber(self):
        self.assertEqual(
            compute_safety_band(self._result(status="safe", score=85, decisions=["WindStrongMajority(5)"])),
            "amber"
        )

    # ── Score-basiert (kein Override aktiv) ──
    def test_high_score_yields_green(self):
        self.assertEqual(compute_safety_band(self._result(status="safe", score=85)), "green")

    def test_low_score_yields_amber(self):
        # score < 40 → amber auch wenn keine Decision-Tags
        # Beispiel: weather_safety_rating=3, alle anderen 9 → MIN=3 → score=30
        self.assertEqual(compute_safety_band(self._result(status="safe", score=30)), "amber")

    def test_boundary_score_40_yields_green(self):
        # score == 40 → green (untere Schwelle ist exklusiv: score < 40 → amber)
        self.assertEqual(compute_safety_band(self._result(status="safe", score=40)), "green")

    def test_boundary_score_39_yields_amber(self):
        self.assertEqual(compute_safety_band(self._result(status="safe", score=39)), "amber")

    # ── Edge Cases ──
    def test_empty_result_defaults_safe_path(self):
        # Komplett leerer Result: status defaults to "" → kein Override → score=0 → amber
        self.assertEqual(compute_safety_band({}), "amber")

    def test_decisions_as_string_handled(self):
        # _decisions_applied kann manchmal als String kommen (Cache-Quirk)
        result = self._result(status="safe", score=85)
        result["_decisions_applied"] = "FoehnDanger(8.0)"  # String, kein List
        self.assertEqual(compute_safety_band(result), "red")


if __name__ == "__main__":
    unittest.main()
