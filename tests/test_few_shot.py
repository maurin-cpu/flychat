"""Tests fuer engine/labeled_examples.py Few-Shot-Pipeline Schritt 2.

Deckt ab:
  - _extract_features_from_label (vollstaendig / unvollstaendig)
  - retrieve_similar (Tier-Filter, Nachbar-Fallback, leerer Pool, Distanz-Sortierung)
  - format_for_prompt (struktur + Korrektur-Anzeige)
  - build_few_shot_block (Decision-Tag + leerer Block)
"""
import unittest
from unittest.mock import patch

from engine import labeled_examples
from engine.labeled_examples import (
    _extract_features_from_label,
    retrieve_similar,
    format_for_prompt,
    build_few_shot_block,
    TIER_NEIGHBOURS,
)


def _make_label(*, tier="hochalpin", peak=2.0, prod_h=4, low=30, mid=40,
                rating_llm=2, label="zu_pessimistisch", corr=4,
                entity_type="region", entity_id="testregion",
                date="2026-05-17"):
    """Hilfsfunktion: minimaler Label-Eintrag im JSONL-Format."""
    return {
        "analysis_id": f"{entity_type}_{entity_id}_{date}",
        "spot_or_region_id": entity_id,
        "entity_type": entity_type,
        "terrain_tier": tier,
        "target_date": date,
        "timestamp": "2026-05-15T10:00:00",
        "weather_input": {
            "aggregates": {
                "sustained_peak_mps": peak,
                "productive_h_strict": prod_h,
                "low_cloud_max": low,
                "mid_cloud_max": mid,
                "cloud_structure": "mixed",
            },
        },
        "llm_output_full": {"experience_rating": rating_llm},
        "user_feedback": {
            "label": label,
            "corrected_experience_rating": corr,
            "correction_text": None,
        },
    }


class ExtractFeaturesTests(unittest.TestCase):
    def test_complete_label_extracts_features(self):
        label = _make_label(tier="hochalpin", peak=2.4, prod_h=5, low=20, mid=60)
        feats = _extract_features_from_label(label)
        self.assertIsNotNone(feats)
        self.assertEqual(feats["tier"], "hochalpin")
        self.assertEqual(feats["peak"], 2.4)
        self.assertEqual(feats["prod_h"], 5.0)
        self.assertEqual(feats["low"], 20.0)
        self.assertEqual(feats["mid"], 60.0)

    def test_missing_peak_returns_none(self):
        label = _make_label()
        label["weather_input"]["aggregates"]["sustained_peak_mps"] = None
        self.assertIsNone(_extract_features_from_label(label))

    def test_missing_prod_h_returns_none(self):
        label = _make_label()
        label["weather_input"]["aggregates"]["productive_h_strict"] = None
        self.assertIsNone(_extract_features_from_label(label))

    def test_missing_tier_returns_none(self):
        label = _make_label()
        label["terrain_tier"] = ""
        self.assertIsNone(_extract_features_from_label(label))

    def test_missing_cloud_defaults_to_zero(self):
        label = _make_label(low=None, mid=None)
        feats = _extract_features_from_label(label)
        self.assertEqual(feats["low"], 0.0)
        self.assertEqual(feats["mid"], 0.0)


class RetrieveSimilarTests(unittest.TestCase):
    def _patch_index(self, labels):
        """Patcht _load_label_index() um vorgegebene Labels statt JSONL zu nutzen."""
        index = []
        for lbl in labels:
            feats = _extract_features_from_label(lbl)
            if feats:
                index.append({"entry": lbl, "features": feats})
        return patch.object(labeled_examples, "_load_label_index", return_value=index)

    def test_empty_pool_returns_empty(self):
        with self._patch_index([]):
            result = retrieve_similar({"tier": "hochalpin", "peak": 2.0,
                                       "prod_h": 4, "low": 30, "mid": 40})
        self.assertEqual(result, [])

    def test_tier_filter_keeps_only_matching_tier(self):
        labels = [
            _make_label(tier="hochalpin", entity_id="reg_a", peak=2.4),
            _make_label(tier="hochalpin", entity_id="reg_b", peak=2.0),
            _make_label(tier="hochalpin", entity_id="reg_c", peak=1.5),
            _make_label(tier="mittelland", entity_id="reg_d", peak=2.4),
        ]
        with self._patch_index(labels):
            result = retrieve_similar(
                {"tier": "hochalpin", "peak": 2.0, "prod_h": 4, "low": 30, "mid": 40},
                top_k=5,
            )
        # 3 hochalpine, keine mittelland
        self.assertEqual(len(result), 3)
        self.assertTrue(all(r["terrain_tier"] == "hochalpin" for r in result))

    def test_neighbour_fallback_when_pool_too_small(self):
        labels = [
            _make_label(tier="hochalpin", entity_id="hp1"),
            _make_label(tier="alpen", entity_id="al1"),
            _make_label(tier="alpen", entity_id="al2"),
            _make_label(tier="mittelland", entity_id="ml1"),
        ]
        # hochalpin hat nur 1 Label, MIN_TIER_POOL=3 → erweitert auf alpen.
        with self._patch_index(labels):
            result = retrieve_similar(
                {"tier": "hochalpin", "peak": 2.0, "prod_h": 4, "low": 30, "mid": 40},
                top_k=3,
            )
        # Mit Fallback: hp1 + alpen-Nachbarn (al1, al2). Mittelland NICHT (kein Nachbar).
        self.assertEqual(len(result), 3)
        tiers = {r["terrain_tier"] for r in result}
        self.assertIn("hochalpin", tiers)
        self.assertIn("alpen", tiers)
        self.assertNotIn("mittelland", tiers)

    def test_distance_sort_returns_closest_peak_first(self):
        labels = [
            _make_label(tier="hochalpin", entity_id="far", peak=3.5),
            _make_label(tier="hochalpin", entity_id="near", peak=2.1),
            _make_label(tier="hochalpin", entity_id="middle", peak=2.8),
        ]
        with self._patch_index(labels):
            result = retrieve_similar(
                {"tier": "hochalpin", "peak": 2.0, "prod_h": 4, "low": 30, "mid": 40},
                top_k=3,
            )
        self.assertEqual(result[0]["spot_or_region_id"], "near")
        self.assertEqual(result[1]["spot_or_region_id"], "middle")
        self.assertEqual(result[2]["spot_or_region_id"], "far")

    def test_entity_type_filter_separates_region_from_spot(self):
        labels = [
            _make_label(entity_type="region", entity_id="r1"),
            _make_label(entity_type="region", entity_id="r2"),
            _make_label(entity_type="spot", entity_id="s1"),
        ]
        with self._patch_index(labels):
            r_only = retrieve_similar(
                {"tier": "hochalpin", "peak": 2.0, "prod_h": 4, "low": 30, "mid": 40},
                entity_type="region",
            )
        self.assertEqual(len(r_only), 2)
        self.assertTrue(all(r["entity_type"] == "region" for r in r_only))

    def test_empty_tier_returns_empty(self):
        labels = [_make_label(tier="hochalpin", entity_id="hp1")]
        with self._patch_index(labels):
            result = retrieve_similar(
                {"tier": "", "peak": 2.0, "prod_h": 4, "low": 30, "mid": 40},
            )
        self.assertEqual(result, [])


class FormatForPromptTests(unittest.TestCase):
    def test_empty_labels_returns_empty_string(self):
        self.assertEqual(format_for_prompt([]), "")

    def test_block_contains_required_fields(self):
        labels = [_make_label(tier="hochalpin", entity_id="surselva",
                              peak=2.4, prod_h=5, low=18, mid=67,
                              rating_llm=2, label="zu_pessimistisch", corr=4)]
        block = format_for_prompt(labels)
        self.assertIn("KALIBRIERUNGS-BEISPIELE", block)
        self.assertIn("surselva", block)
        self.assertIn("hochalpin", block)
        self.assertIn("2.4 m/s", block)
        self.assertIn("ZU PESSIMISTISCH", block)
        self.assertIn("Korrigiertes Rating:   4", block)
        self.assertIn("experience_rating = 2", block)

    def test_richtig_label_does_not_show_correction(self):
        labels = [_make_label(label="richtig", corr=None, rating_llm=3)]
        block = format_for_prompt(labels)
        self.assertIn("RICHTIG", block)
        self.assertNotIn("Korrigiertes Rating", block)

    def test_optimistisch_without_rating_correction_shown(self):
        labels = [_make_label(label="zu_optimistisch", corr=None, rating_llm=4)]
        block = format_for_prompt(labels)
        self.assertIn("ZU OPTIMISTISCH", block)
        self.assertIn("keine konkrete Rating-Korrektur", block)


class BuildFewShotBlockTests(unittest.TestCase):
    def test_empty_pool_returns_empty_block_with_none_tag(self):
        with patch.object(labeled_examples, "_load_label_index", return_value=[]):
            block, tag = build_few_shot_block(
                {"tier": "hochalpin", "peak": 2.0, "prod_h": 4, "low": 30, "mid": 40},
            )
        self.assertEqual(block, "")
        self.assertIn("FewShot:none", tag)
        self.assertIn("hochalpin", tag)

    def test_with_labels_returns_block_and_count_tag(self):
        labels = [
            _make_label(tier="hochalpin", entity_id=f"reg_{i}", peak=2.0 + i * 0.1)
            for i in range(5)
        ]
        index = [{"entry": l, "features": _extract_features_from_label(l)} for l in labels]
        with patch.object(labeled_examples, "_load_label_index", return_value=index):
            block, tag = build_few_shot_block(
                {"tier": "hochalpin", "peak": 2.0, "prod_h": 4, "low": 30, "mid": 40},
                top_k=3,
            )
        self.assertIn("KALIBRIERUNGS-BEISPIELE", block)
        self.assertIn("FewShot:hochalpin,3 examples", tag)


class TierNeighbourTests(unittest.TestCase):
    def test_all_tiers_have_neighbours_defined(self):
        # Schutz gegen Tippfehler in regionen.csv: alle Tier-Werte muessen im
        # Map sein, sonst gibt's silent fallback auf [] (kein Fallback moeglich).
        expected = {"mittelland", "jura", "voralpen", "alpen", "hochalpin"}
        self.assertEqual(set(TIER_NEIGHBOURS.keys()), expected)


if __name__ == "__main__":
    unittest.main()
