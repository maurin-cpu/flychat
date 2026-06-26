"""Tests fuer engine/decision_engine.py — Stage-Inversion-Pipeline.

Deckt ab:
  - Foehn (compute_foehn_decision + apply_foehn_decision)
  - Wind-OK=0
  - Aloft-NotSafe / Aloft-Conditional
  - Gust-Floor
  - Overclaim-Relax (DEMOTIERT not_safe → conditional)
  - Wind-Strong-Mehrheit (Region)
  - Flyability-Mech-Danger (einzige verbleibende Flyability-Decision, v1.5)

Mit RATING_CONCEPT v1.5 entfernt: `decide_flyability_low_reward`,
`decide_flyability_upgrade`, `decide_flyability_region_gate`,
`compute_legacy_flyability_tier`, `_compute_rating_from_subratings`,
`_compute_experience_score`, `_compute_experience_stars`,
`_compute_experience_rating` — LLM setzt rating + tier direkt.
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
    decide_flyability_mech_danger,
    compute_safety_band,
)
from engine._common import (
    _compute_safety_rating,
    _compute_safety_score,
    derive_status_from_subs,
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


class TestFlyabilityMechDanger(unittest.TestCase):
    """RATING_CONCEPT v1.5: nur noch mech_danger als Safety-Eskalation.
    LowReward / Upgrade / RegionGate entfernt — LLM setzt Tier direkt."""

    def test_mech_danger_fires_and_escalates_safety(self):
        result = {"flyability_tier": "green", "fly_status": "green",
                  "safety_status": "safe", "caution_notes": []}
        tq = {"thermal_hours_total": 6, "rough_danger_h": 4,
              "peak_climb_proxy": 1.5, "productive_thermal_h": 4}
        tag = decide_flyability_mech_danger(result, tq, "X/Y")
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


# ════════════════════════════════════════════════════════════════════
# Vorab-Fix #2: is_conditional deterministisch (RATING_CONCEPT v1.3, A2-Logik)
# ════════════════════════════════════════════════════════════════════
# A2-Logik:
#   - safety_status == "conditional"  → is_conditional = True  (Engine-Override)
#   - safety_status == "not_safe"     → is_conditional = False (Sanity-Clamp)
#   - safety_status == "safe"         → LLM behaelt Hand (Trigger 1+2 aus
#                                       _safety_experience.md: Wolkenbasis,
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
# ════════════════════════════════════════════════════════════════════
# Vorab-Fix #4: Safety-Sub-Ratings (8 Felder, Weakest-Link-Aggregation)
# ════════════════════════════════════════════════════════════════════
# Acht LLM-Sub-Ratings (wind/gust/aloft/foehn/rain/thunderstorm/cape/visibility,
# je 1-10) werden via MIN zu 0-10 safety_rating aggregiert und × 10 zu
# safety_score (0-100).
class TestSafetyRating(unittest.TestCase):
    def _result(self, wind=5, gust=5, aloft=5, foehn=5,
                rain=5, thunderstorm=5, cape=5, visibility=5):
        return {
            "wind_safety_rating": wind,
            "gust_safety_rating": gust,
            "aloft_safety_rating": aloft,
            "foehn_safety_rating": foehn,
            "rain_safety_rating": rain,
            "thunderstorm_safety_rating": thunderstorm,
            "cape_safety_rating": cape,
            "visibility_safety_rating": visibility,
        }

    # ── Weakest-Link-Aggregation (MIN) ──
    def test_all_mid_yields_5(self):
        self.assertEqual(_compute_safety_rating(self._result()), 5.0)

    def test_all_max_yields_10(self):
        self.assertEqual(_compute_safety_rating(self._result(10, 10, 10, 10, 10, 10, 10, 10)), 10.0)

    def test_all_min_yields_1(self):
        self.assertEqual(_compute_safety_rating(self._result(1, 1, 1, 1, 1, 1, 1, 1)), 1.0)

    def test_min_dominates_single_low_wind(self):
        # 7 perfekte Ratings + 1 niedriger Wind → MIN vom niedrigsten
        self.assertEqual(_compute_safety_rating(self._result(wind=2)), 2.0)

    def test_min_dominates_single_low_rain(self):
        # Klassischer Fall: alles top, aber Regen eingekesselt → safety = 2
        # Verhindert dass perfekter Wind ein Regen-Risiko "wegmittelt"
        self.assertEqual(_compute_safety_rating(self._result(rain=2)), 2.0)

    def test_min_dominates_single_low_thunderstorm(self):
        self.assertEqual(_compute_safety_rating(self._result(thunderstorm=2)), 2.0)

    def test_min_dominates_single_low_foehn(self):
        self.assertEqual(_compute_safety_rating(self._result(foehn=3)), 3.0)

    # ── Defaults bei fehlenden / ungueltigen Feldern ──
    def test_missing_fields_default_to_5(self):
        # Komplett leerer Result → Default 5 fuer jedes → MIN = 5
        self.assertEqual(_compute_safety_rating({}), 5.0)

    def test_invalid_field_falls_back_to_5(self):
        result = {"wind_safety_rating": "invalid", "gust_safety_rating": None,
                  "aloft_safety_rating": 5, "foehn_safety_rating": 5,
                  "rain_safety_rating": 5}
        # Invalid/None → ignoriert, Rest 5 → MIN = 5
        self.assertEqual(_compute_safety_rating(result), 5.0)

    def test_partial_missing_takes_min(self):
        # nur rain=2, andere fehlen → werden ignoriert, MIN = 2
        self.assertEqual(_compute_safety_rating({"rain_safety_rating": 2}), 2.0)

    def test_zero_or_negative_excluded(self):
        # Werte <=0 sind "nicht bewertbar" und werden aus dem MIN ausgeschlossen.
        # Wenn ALLE Sub-Ratings <=0 → Fallback 5.0 (neutral).
        self.assertEqual(_compute_safety_rating(self._result(0, 0, 0, 0, 0, 0, 0, 0)), 5.0)

    def test_region_no_gust_data(self):
        # Region-Szenario: Skill-Schema setzt gust_safety_rating=0 weil
        # Regionen keine Boeen-Daten haben. 0 darf NICHT das Min vergiften.
        result = self._result(wind=10, gust=0, aloft=9, foehn=10, rain=10,
                              thunderstorm=10, cape=10, visibility=10)
        self.assertEqual(_compute_safety_rating(result), 9.0)

    def test_clamp_above_ten(self):
        # Werte > 10 werden auf 10 geclampt → MIN = 10
        self.assertEqual(_compute_safety_rating(self._result(15, 15, 15, 15, 15, 15, 15, 15)), 10.0)

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
# Phase 1: compute_safety_band — DEPRECATED in RATING_ARCHITECTURE v2.0
# ════════════════════════════════════════════════════════════════════
# safety_band wurde entfernt — FE leitet Farbe direkt aus safety_status ab.
# Tests bleiben skipped fuer Historie.
@unittest.skip("RATING_ARCHITECTURE v2.0: safety_band wurde entfernt, FE mappt aus safety_status")
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


# ════════════════════════════════════════════════════════════════════
# Phase 4 (RATING_CONCEPT v1.4 §9.7): compute_legacy_flyability_tier
# Compat-View — leitet flyability_tier aus (safety_band, experience_rating 0-10) ab
# ════════════════════════════════════════════════════════════════════
class TestWindWrongIsNotHazard(unittest.TestCase):
    """Regression: WIND-WRONG ist Startbarkeits-Filter, kein Hazard.

    Es darf NICHT im Hauptgefahren-Histogramm (`major_tags_order`) auftauchen
    und NICHT in `tag_counts` für die Tagesprofil-Auswertung gezählt werden.
    Sonst interpretiert das LLM es als Sicherheits- oder Flyability-Warnung
    und erzeugt falsche caution_notes / no_go_reasons.
    """
    def setUp(self):
        from pathlib import Path
        self.src = Path("engine/weather_context.py").read_text(encoding="utf-8")

    def test_wind_wrong_not_in_major_tags_order(self):
        # major_tags_order ist die Liste der Hazards im TAGESPROFIL-Histogramm.
        # WIND-WRONG gehoert dort nicht hin (ist ein Filter, kein Hazard).
        # Listenelemente erkennen wir am Trailing-Komma: `"[WIND-WRONG]",`.
        # Die Definitions-Zeile `wind_status = ... else "[WIND-WRONG]"` ist OK.
        for line_no, line in enumerate(self.src.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if stripped == '"[WIND-WRONG]",' or stripped.endswith('"[WIND-WRONG]",'):
                self.fail(
                    f"WIND-WRONG darf nicht in major_tags_order/tag_counts-Listen "
                    f"erscheinen — es ist ein Startbarkeits-Filter, kein Hazard. "
                    f"Gefunden in Zeile {line_no}: {stripped}"
                )

    def test_wind_wrong_not_incremented_into_tag_counts(self):
        # Das Pattern `tag_counts[wind_status]` (oder day_state["tag_counts"][wind_status])
        # wuerde im Spot-Pfad WIND-WRONG-Stunden ins Histogramm zaehlen.
        # Nach dem Fix darf dieses Pattern im Spot-Pfad nicht mehr existieren.
        forbidden_patterns = [
            "tag_counts[wind_status]",
            'tag_counts["[WIND-WRONG]"]',
            'day_state["tag_counts"][wind_status]',
        ]
        for pattern in forbidden_patterns:
            self.assertNotIn(
                pattern, self.src,
                f"Pattern `{pattern}` wuerde WIND-WRONG ins Hazard-Histogramm "
                f"zaehlen. WIND-WRONG ist Startbarkeits-Filter, kein Hazard."
            )

    def test_tagesfenster_block_present(self):
        # TAGESFENSTER-Header muss im Datenblock-Output stehen sobald Stunden
        # vor Tagesbeginn weggefiltert werden — damit das LLM die Slicing-
        # Begruendung sieht statt Stunden zu halluzinieren. Filter/Hazard-
        # Trennung lebt jetzt im Skill `_tagesfenster.md`, nicht im Datenblock.
        self.assertIn("═══ TAGESFENSTER", self.src)
        self.assertIn("Tag aktiv ab", self.src)


# ════════════════════════════════════════════════════════════════════
# DERIVE_STATUS_FROM_SUBS — Konsistenz-Bruecke LLM-Status ↔ Sub-Ratings
# ════════════════════════════════════════════════════════════════════

class TestDeriveStatusFromSubs(unittest.TestCase):
    def _r(self, wind=10, gust=10, aloft=10, foehn=10,
           rain=10, thunderstorm=10, cape=10, visibility=10):
        return {
            "wind_safety_rating": wind,
            "gust_safety_rating": gust,
            "aloft_safety_rating": aloft,
            "foehn_safety_rating": foehn,
            "rain_safety_rating": rain,
            "thunderstorm_safety_rating": thunderstorm,
            "cape_safety_rating": cape,
            "visibility_safety_rating": visibility,
        }

    def test_all_high_safe(self):
        self.assertEqual(derive_status_from_subs(self._r()), "safe")

    def test_min_4_still_safe(self):
        # Schwelle: m >= 4 -> safe. Bei m == 4 noch safe.
        self.assertEqual(derive_status_from_subs(self._r(wind=4)), "safe")

    def test_min_3_conditional(self):
        # m == 3 -> conditional (Skill-Anker: 3 = grenzwertig)
        self.assertEqual(derive_status_from_subs(self._r(gust=3)), "conditional")

    def test_min_2_not_safe(self):
        # m <= 2 -> not_safe (akut gefaehrlich, vor Hard-Override)
        self.assertEqual(derive_status_from_subs(self._r(rain=2)), "not_safe")

    def test_min_1_not_safe(self):
        self.assertEqual(derive_status_from_subs(self._r(foehn=1)), "not_safe")

    def test_zero_excluded_other_subs_decide(self):
        # gust=0 (z.B. Region ohne Gust-Daten) wird ignoriert, MIN ueber Rest.
        self.assertEqual(derive_status_from_subs(self._r(gust=0)), "safe")

    def test_zero_excluded_low_sub_still_wins(self):
        self.assertEqual(
            derive_status_from_subs(self._r(gust=0, aloft=2)),
            "not_safe",
        )

    def test_all_zero_returns_none(self):
        # Keine bewertbaren Subs -> None (Aufrufer ueberschreibt nichts).
        r = self._r(wind=0, gust=0, aloft=0, foehn=0,
                    rain=0, thunderstorm=0, cape=0, visibility=0)
        self.assertIsNone(derive_status_from_subs(r))

    def test_missing_subs_returns_none(self):
        self.assertIsNone(derive_status_from_subs({}))

    def test_partial_subs_works(self):
        # Region: foehn/gust fehlt, andere vorhanden — funktioniert trotzdem.
        r = {
            "wind_safety_rating": 8,
            "aloft_safety_rating": 3,
            "rain_safety_rating": 9,
        }
        self.assertEqual(derive_status_from_subs(r), "conditional")

    def test_non_numeric_treated_as_missing(self):
        r = self._r(wind="abc", gust=4)
        # wind invalid -> ausgeschlossen, gust=4 -> safe
        self.assertEqual(derive_status_from_subs(r), "safe")

    def test_value_clamped_above_10(self):
        # Werte ueber 10 werden geklemmt, MIN bleibt min der anderen.
        self.assertEqual(derive_status_from_subs(self._r(wind=15)), "safe")

    # Monte-Lema-Reproduzent (User-Bug 2026-05-05):
    # LLM gab status=safe + summary "sicher", aber wind_safety=3 wegen falscher
    # Richtung. Erwartetes Verhalten: derived = "conditional" -> Engine eskaliert.
    def test_monte_lema_drift_pattern(self):
        r = self._r(wind=3, gust=8, aloft=8, foehn=10, rain=9)
        self.assertEqual(derive_status_from_subs(r), "conditional")


class TestValidateLlmTags(unittest.TestCase):
    """Tests fuer validate_llm_tags — Hybrid v5 (siehe docs/TAGS.md)."""

    def test_accepts_whitelist_topic(self):
        from engine.decision_engine import validate_llm_tags
        result = {"peak_climb_rate": 2.0, "avg_low_mid": 30}
        out = validate_llm_tags(
            [{"topic": "THERMAL", "severity": "good", "label": "Thermik", "value": "peak 2.0 m/s"}],
            result,
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["topic"], "THERMAL")

    def test_drops_topic_not_in_whitelist(self):
        from engine.decision_engine import validate_llm_tags
        out = validate_llm_tags([{"topic": "WIND_GROUND", "severity": "warn"}], {})
        self.assertEqual(out, [])

    def test_drops_stop_severity(self):
        from engine.decision_engine import validate_llm_tags
        out = validate_llm_tags(
            [{"topic": "THERMAL", "severity": "stop", "label": "Thermik"}],
            {"peak_climb_rate": 2.0},
        )
        self.assertEqual(out, [])

    def test_drops_warn_severity(self):
        """WARN ist Sicherheits-Hoheit (Backend-only) — LLM darf nicht."""
        from engine.decision_engine import validate_llm_tags
        out = validate_llm_tags(
            [{"topic": "CLOUDS", "severity": "warn", "label": "Bewoelkung"}],
            {},
        )
        self.assertEqual(out, [])

    def test_drops_info_severity_legacy(self):
        """info ist Legacy-Severity — LLM muss reducer nutzen."""
        from engine.decision_engine import validate_llm_tags
        out = validate_llm_tags(
            [{"topic": "INVERSION", "severity": "info"}],
            {},
        )
        self.assertEqual(out, [])

    def test_drops_invalid_severity(self):
        from engine.decision_engine import validate_llm_tags
        out = validate_llm_tags([{"topic": "CLOUDS", "severity": "danger"}], {})
        self.assertEqual(out, [])

    def test_drops_thermal_good_with_low_peak(self):
        """Sanity: LLM darf nicht THERMAL=good behaupten wenn peak < 1.0."""
        from engine.decision_engine import validate_llm_tags
        out = validate_llm_tags(
            [{"topic": "THERMAL", "severity": "good", "label": "Thermik"}],
            {"peak_climb_rate": 0.5},
        )
        self.assertEqual(out, [])

    def test_keeps_thermal_reducer_with_low_peak(self):
        """reducer ist erlaubt — schwache Thermik darf als Fliegbarkeits-Minderer markiert werden."""
        from engine.decision_engine import validate_llm_tags
        out = validate_llm_tags(
            [{"topic": "THERMAL", "severity": "reducer", "label": "Thermik"}],
            {"peak_climb_rate": 0.5},
        )
        self.assertEqual(len(out), 1)

    def test_drops_clouds_good_with_high_low_mid(self):
        from engine.decision_engine import validate_llm_tags
        out = validate_llm_tags(
            [{"topic": "CLOUDS", "severity": "good", "label": "Bewoelkung"}],
            {"avg_low_mid": 80},
        )
        self.assertEqual(out, [])

    def test_dedupe_topic_first_wins(self):
        from engine.decision_engine import validate_llm_tags
        out = validate_llm_tags(
            [
                {"topic": "BASE", "severity": "reducer", "label": "Wolkenbasis"},
                {"topic": "BASE", "severity": "good", "label": "Wolkenbasis"},
            ],
            {"min_cloud_base_active_h": 1500, "elevation_m": 1100, "peak_height_m": 2000},
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["severity"], "reducer")

    def test_handles_non_list(self):
        from engine.decision_engine import validate_llm_tags
        self.assertEqual(validate_llm_tags(None, {}), [])
        self.assertEqual(validate_llm_tags("nope", {}), [])

    def test_drops_non_dict_items(self):
        from engine.decision_engine import validate_llm_tags
        # BASE braucht cloud_base/peak_height_m fuer Sanity — daher SUNSHINE
        # als simpler Whitelist-Tag ohne extra Datenanforderung.
        out = validate_llm_tags(
            ["not a tag", {"topic": "SUNSHINE", "severity": "good"}],
            {},
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["topic"], "SUNSHINE")

    def test_accepts_new_llm_topics(self):
        from engine.decision_engine import validate_llm_tags
        out = validate_llm_tags(
            [
                {"topic": "INVERSION", "severity": "reducer"},
                {"topic": "BASE", "severity": "good"},
                {"topic": "WINDOW", "severity": "reducer"},
                {"topic": "SUNSHINE", "severity": "good"},
                {"topic": "CONVERGENCE", "severity": "good"},
            ],
            {"min_cloud_base_active_h": 3000, "elevation_m": 800, "peak_height_m": 2000},
        )
        self.assertEqual(len(out), 5)

    # ── Pro-Topic-Severity-Matrix (LLM_TAG_TOPIC_SEVERITY) ────────────

    def test_drops_inversion_good(self):
        """INVERSION darf nur reducer (limitiert Thermik), nie good."""
        from engine.decision_engine import validate_llm_tags
        out = validate_llm_tags(
            [{"topic": "INVERSION", "severity": "good"}], {},
        )
        self.assertEqual(out, [])

    def test_drops_convergence_reducer(self):
        """CONVERGENCE ist nur ein Booster — reducer macht keinen Sinn."""
        from engine.decision_engine import validate_llm_tags
        out = validate_llm_tags(
            [{"topic": "CONVERGENCE", "severity": "reducer"}], {},
        )
        self.assertEqual(out, [])

    def test_drops_xc_reducer(self):
        """XC ist nur Pluspunkt — reducer/warn unzulaessig."""
        from engine.decision_engine import validate_llm_tags
        out = validate_llm_tags(
            [{"topic": "XC", "severity": "reducer"}], {},
        )
        self.assertEqual(out, [])

    def test_accepts_xc_good(self):
        from engine.decision_engine import validate_llm_tags
        out = validate_llm_tags(
            [{"topic": "XC", "severity": "good", "label": "XC"}], {},
        )
        self.assertEqual(len(out), 1)

    # ── BASE-Sanity (cloud_base relativ zu elevation_m / peak_height_m) ──

    def test_drops_base_reducer_when_base_high(self):
        """BASE reducer nur wenn Basis weniger als 600m ueber Startplatz."""
        from engine.decision_engine import validate_llm_tags
        out = validate_llm_tags(
            [{"topic": "BASE", "severity": "reducer"}],
            {"min_cloud_base_active_h": 2500, "elevation_m": 1000},  # 1500m Differenz
        )
        self.assertEqual(out, [])

    def test_keeps_base_reducer_when_base_low(self):
        from engine.decision_engine import validate_llm_tags
        out = validate_llm_tags(
            [{"topic": "BASE", "severity": "reducer"}],
            {"min_cloud_base_active_h": 1400, "elevation_m": 1000},  # 400m Differenz
        )
        self.assertEqual(len(out), 1)

    def test_drops_base_good_when_base_close_to_peak(self):
        """BASE good nur wenn Basis mehr als 800m ueber Gipfel."""
        from engine.decision_engine import validate_llm_tags
        out = validate_llm_tags(
            [{"topic": "BASE", "severity": "good"}],
            {"min_cloud_base_active_h": 2300, "peak_height_m": 2000},  # 300m
        )
        self.assertEqual(out, [])

    def test_keeps_base_good_when_base_high_above_peak(self):
        from engine.decision_engine import validate_llm_tags
        out = validate_llm_tags(
            [{"topic": "BASE", "severity": "good"}],
            {"min_cloud_base_active_h": 3500, "peak_height_m": 2000},  # 1500m
        )
        self.assertEqual(len(out), 1)

    def test_drops_base_when_no_cloud_base_data(self):
        from engine.decision_engine import validate_llm_tags
        out = validate_llm_tags(
            [{"topic": "BASE", "severity": "reducer"}],
            {"elevation_m": 1000},  # cloud_base fehlt
        )
        self.assertEqual(out, [])


class TestMergeTopicTags(unittest.TestCase):
    """Tests fuer merge_topic_tags — Hybrid v5."""

    def test_merges_disjoint(self):
        from engine.decision_engine import merge_topic_tags
        backend = [{"topic": "WIND_GROUND", "severity": "warn", "label": "Wind", "value": "", "time": ""}]
        llm = [{"topic": "THERMAL", "severity": "good", "label": "Thermik", "value": "", "time": ""}]
        out = merge_topic_tags(backend, llm)
        self.assertEqual([t["topic"] for t in out], ["WIND_GROUND", "THERMAL"])

    def test_dedupes_topic_max_severity_wins(self):
        from engine.decision_engine import merge_topic_tags
        backend = [{"topic": "FOEHN", "severity": "warn", "label": "Foehn", "value": "", "time": ""}]
        llm = [{"topic": "FOEHN", "severity": "good", "label": "Foehn", "value": "", "time": ""}]
        out = merge_topic_tags(backend, llm)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["severity"], "warn")

    def test_orders_by_topic_order(self):
        from engine.decision_engine import merge_topic_tags
        out = merge_topic_tags(
            [{"topic": "TURBULENCE", "severity": "reducer"}, {"topic": "WIND_GROUND", "severity": "warn"}],
            [{"topic": "THERMAL", "severity": "good"}, {"topic": "FOEHN", "severity": "warn"}],
        )
        self.assertEqual(
            [t["topic"] for t in out],
            ["WIND_GROUND", "FOEHN", "THERMAL", "TURBULENCE"],
        )

    def test_legacy_info_severity_outranked_by_reducer(self):
        """info ist Legacy-Severity. Wenn Backend reducer und Cache info liefert,
        gewinnt der hoehere Severity-Rang (oder gleich; first wins)."""
        from engine.decision_engine import merge_topic_tags
        out = merge_topic_tags(
            [{"topic": "TURBULENCE", "severity": "info"}],
            [],
        )
        # Legacy "info" wird durchgereicht (Cache-Migration), aber Rang = reducer.
        self.assertEqual(len(out), 1)

    def test_handles_empty_inputs(self):
        from engine.decision_engine import merge_topic_tags
        self.assertEqual(merge_topic_tags([], []), [])
        self.assertEqual(merge_topic_tags(None, None), [])


class TestBuildTopicTagsClouds(unittest.TestCase):
    """Tests fuer CLOUDS-Sicherheits-Branch (siehe docs/TAGS.md)."""

    def _gust(self, **overrides):
        base = {
            "gust_warn_hours": 0, "gust_danger_hours": 0,
            "wind_warn_hours": 0, "wind_danger_hours": 0,
            "wind_ok_count": 5, "wind_wrong_count": 0,
            "max_surface_gust": 0,
            "aloft_warn_hours": 0, "aloft_danger_hours": 0,
            "aloft_gust_warn_hours": 0, "aloft_gust_danger_hours": 0,
            "rain_hours": 0, "thunderstorm_hours": 0,
            "elevation_m": 1500,
            "cloud_at_or_below_takeoff_h": 0,
            "cloud_near_takeoff_h": 0,
            "min_cloud_base_active_h": None,
        }
        base.update(overrides)
        return base

    def test_clouds_stop_when_base_at_or_below_takeoff(self):
        """Wolkenbasis ≤ Startplatz mit hoher Bedeckung in 2+ Stunden → STOP."""
        from engine.decision_engine import build_topic_tags
        tags = build_topic_tags(
            {"foehn_risk": "none"},
            self._gust(
                cloud_at_or_below_takeoff_h=4,
                min_cloud_base_active_h=1450,  # unter elev 1500
            ),
            {},
        )
        clouds = [t for t in tags if t["topic"] == "CLOUDS"]
        self.assertEqual(len(clouds), 1)
        self.assertEqual(clouds[0]["severity"], "stop")

    def test_clouds_reducer_when_base_near_takeoff(self):
        """Wolkenrand knapp ueber Startplatz → REDUCER (fliegbar/gruen, kein Downgrade)."""
        from engine.decision_engine import build_topic_tags
        tags = build_topic_tags(
            {"foehn_risk": "none"},
            self._gust(
                cloud_near_takeoff_h=2,
                min_cloud_base_active_h=1700,  # 200m ueber elev 1500
            ),
            {},
        )
        clouds = [t for t in tags if t["topic"] == "CLOUDS"]
        self.assertEqual(len(clouds), 1)
        self.assertEqual(clouds[0]["severity"], "reducer")

    def test_clouds_no_tag_when_base_high(self):
        """Hohe Basis → kein Backend-CLOUDS-Tag (REDUCER/GOOD ist LLM-Sache)."""
        from engine.decision_engine import build_topic_tags
        tags = build_topic_tags(
            {"foehn_risk": "none"},
            self._gust(min_cloud_base_active_h=3000),
            {},
        )
        clouds = [t for t in tags if t["topic"] == "CLOUDS"]
        self.assertEqual(clouds, [])

    def test_clouds_stop_below_2h_does_not_trigger(self):
        """Unter 2h Schwelle → kein STOP."""
        from engine.decision_engine import build_topic_tags
        tags = build_topic_tags(
            {"foehn_risk": "none"},
            self._gust(cloud_at_or_below_takeoff_h=1, min_cloud_base_active_h=1450),
            {},
        )
        clouds = [t for t in tags if t["topic"] == "CLOUDS"]
        self.assertEqual(clouds, [])


class TestBuildTopicTagsTurbulence(unittest.TestCase):
    """TURBULENCE wurde von info → reducer migriert (siehe docs/TAGS.md)."""

    def test_turbulence_severity_is_reducer(self):
        from engine.decision_engine import build_topic_tags
        tags = build_topic_tags(
            {"foehn_risk": "none"},
            {
                "wind_ok_count": 5, "wind_wrong_count": 0,
                "elevation_m": 1500, "min_cloud_base_active_h": None,
                "cloud_at_or_below_takeoff_h": 0, "cloud_near_takeoff_h": 0,
                "gust_warn_hours": 0, "gust_danger_hours": 0,
                "wind_warn_hours": 0, "wind_danger_hours": 0,
                "aloft_warn_hours": 0, "aloft_danger_hours": 0,
                "aloft_gust_warn_hours": 0, "aloft_gust_danger_hours": 0,
            },
            {"rough_danger_h": 4},
        )
        turb = [t for t in tags if t["topic"] == "TURBULENCE"]
        self.assertEqual(len(turb), 1)
        self.assertEqual(turb[0]["severity"], "reducer")


class TestCalmWindDirectionBypass(unittest.TestCase):
    """I-013 Hebel A: bei Flaute (< WIND_DIRECTION_IRRELEVANT_BELOW_KMH km/h) ist
    die Windrichtung bedeutungsloses Rauschen -> immer WIND-OK. Sichtbar gemacht
    via [WIND-CALM]-Marker + FLAUTE-STARTBAR-Hinweis, damit die Flugeinschaetzung
    es erwaehnt (Boeen koennen aus beliebiger Richtung kommen).
    """
    def setUp(self):
        from pathlib import Path
        from chat_engine import WingcastEngine
        # __new__: _is_wind_in_range braucht nur config + _parse_wind_range,
        # kein teurer __init__/CSV-Load noetig.
        self.eng = WingcastEngine.__new__(WingcastEngine)
        self.src = Path("engine/weather_context.py").read_text(encoding="utf-8")

    def test_calm_wind_overrides_wrong_direction(self):
        import config
        sector = "SW"  # ~180-270 grad
        thr = config.WIND_DIRECTION_IRRELEVANT_BELOW_KMH
        # Richtung klar ausserhalb (N=0 grad), aber Flaute -> WIND-OK
        self.assertTrue(self.eng._is_wind_in_range(0, sector, wind_speed=thr - 1))
        # gleiche falsche Richtung, aber Wind >= Schwelle -> WIND-WRONG (altes Verhalten)
        self.assertFalse(self.eng._is_wind_in_range(0, sector, wind_speed=thr + 1))
        # Schwelle ist strikt (<): genau thr zaehlt die Richtung schon wieder
        self.assertFalse(self.eng._is_wind_in_range(0, sector, wind_speed=thr))
        # ohne wind_speed -> unveraendertes Richtungs-only-Verhalten
        self.assertFalse(self.eng._is_wind_in_range(0, sector))
        self.assertTrue(self.eng._is_wind_in_range(225, sector))

    def test_calm_override_surfaced_for_flight_assessment(self):
        # Der Flaute-Override muss LLM-sichtbar sein (Marker + Hinweis), sonst
        # kann die Flugeinschaetzung ihn nicht erwaehnen.
        self.assertIn("calm_dir_override", self.src)
        self.assertIn("[WIND-CALM]", self.src)
        self.assertIn("FLAUTE-STARTBAR", self.src)


if __name__ == "__main__":
    unittest.main()
