"""Sprach-Waechter (engine/lang_guard.py) + sprachabhaengige Code-Texte.

Befund 10.10.2026 (Server-Cache EN): 55 % der Spot-Analysen trugen deutsche
Woerter in sichtbaren Feldern. Die Tests halten fest: EN-Texte werden
englisch, der DE-Pfad bleibt Wort fuer Wort wie vorher.
"""
import i18n
from engine._common import _sanitize_llm_text
from engine.decision_engine import compute_foehn_decision
from engine.lang_guard import englishify_analysis_tree, englishify_text, english_label


def test_sanitizer_uses_english_terms_in_en_mode():
    with i18n.lang_override("en"):
        out = _sanitize_llm_text("no rain, no THUNDERSTORM, triggering OVERCAST-DANGER for 5 hours")
    assert out == "no rain, no thunderstorm, triggering dense cloud cover for 5 hours"


def test_sanitizer_german_path_unchanged():
    with i18n.lang_override("de"):
        out = _sanitize_llm_text("kein THUNDERSTORM, OVERCAST-DANGER ab 13 Uhr")
    assert out == "kein Gewitter, dichte Wolkendecke ab 13 Uhr"


def test_foehn_caution_note_per_language():
    ev = {"level": "caution", "delta_p_hpa": 5.8, "direction": "Nord"}
    with i18n.lang_override("de"):
        de = compute_foehn_decision(ev).caution_note
    with i18n.lang_override("en"):
        en = compute_foehn_decision(ev).caution_note
    assert de == "Foehn-Warnhinweis: Nordfoehn ΔP 5.8 hPa — Boeen an exponierten Stellen."
    assert en == "Foehn alert: north foehn ΔP 5.8 hPa — gusts at exposed spots."


def test_guard_translates_old_cached_texts():
    with i18n.lang_override("en"):
        assert englishify_text(
            "Foehn-Warnhinweis: Nordfoehn ΔP 5.7 hPa — Boeen an exponierten Stellen."
        ) == "Foehn alert: north foehn ΔP 5.7 hPa — gusts at exposed spots."
        assert englishify_text(
            "Upper wind 28-31 km/h, gefaehrlicher Hoehenwind every hour, no Gewitters"
        ) == "Upper wind 28-31 km/h, dangerous upper wind every hour, no thunderstorms"
        assert englishify_text("Dichte Wolkendecke from 13:00") == "Dense cloud cover from 13:00"


def test_guard_leaves_place_names_alone():
    with i18n.lang_override("en"):
        assert englishify_text("The Waadtländer Alpen and Prättigau stay calm.") == \
            "The Waadtländer Alpen and Prättigau stay calm."


def test_tag_labels():
    with i18n.lang_override("en"):
        assert english_label("Thermik") == "Thermal"
        assert english_label("Bewoelkung") == "Clouds"
        assert english_label("Upper wind") == "Upper wind"
    with i18n.lang_override("de"):
        assert english_label("Thermik") == "Thermik"


def test_tree_does_nothing_in_german_mode():
    tree = {"Spot": {"2026-10-10": {"summary": "kein Gewitter", "tags": [{"label": "Thermik"}]}}}
    with i18n.lang_override("de"):
        assert englishify_analysis_tree(tree) == 0
    assert tree["Spot"]["2026-10-10"]["summary"] == "kein Gewitter"


def test_tree_fixes_cache_in_english_mode():
    tree = {"Spot": {"2026-10-10": {
        "spot": "Regenalp",
        "safety": {"summary": "no rain, Gewitter, or CAPE build-up"},
        "tags": [{"topic": "THERMAL", "label": "Thermik", "value": "peak 2.0 m/s"}],
    }}}
    with i18n.lang_override("en"):
        assert englishify_analysis_tree(tree) == 1
    res = tree["Spot"]["2026-10-10"]
    assert res["safety"]["summary"] == "no rain, thunderstorm, or CAPE build-up"
    assert res["tags"][0]["label"] == "Thermal"
    assert res["spot"] == "Regenalp"
