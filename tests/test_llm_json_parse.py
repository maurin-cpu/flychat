"""Tests fuer parse_llm_json — Fence-Artefakte und Pflichtfeld-Wache.

Hintergrund: DeepInfra (DeepSeek-V4-Flash) liefert im json_object-Modus
gelegentlich die Markdown-Fence mit. Das Ergebnis ist gueltiges JSON, aber
inhaltlich leer — ohne diese Wache landet es still als "error" in der
Produktion (gemessen 25.08.2026: 6 von 50 Antworten).
"""

import json

import pytest

from engine._common import parse_llm_json


def test_normale_antwort_geht_durch():
    roh = json.dumps({"safety_status": "not_safe", "summary": "Regen"})
    assert parse_llm_json(roh, "safety_status")["safety_status"] == "not_safe"


def test_markdown_fence_um_die_antwort():
    roh = '```json\n{"safety_status": "safe"}\n```'
    assert parse_llm_json(roh, "safety_status")["safety_status"] == "safe"


def test_objekt_als_string_unter_json_schluessel():
    """Der real beobachtete Fall: {"`json`": "{...}"}."""
    innen = json.dumps({"safety_status": "conditional", "safe_window": "13-15"})
    roh = json.dumps({"`json`": innen})
    ergebnis = parse_llm_json(roh, "safety_status")
    assert ergebnis["safety_status"] == "conditional"
    assert ergebnis["safe_window"] == "13-15"


def test_rumpf_als_schluessel_verunglueckt():
    """Zweiter realer Fall: der JSON-Rumpf wird selbst zum Schluessel."""
    roh = json.dumps({'"safety_status": "not_safe", "summary": "Gewitter"': ""})
    ergebnis = parse_llm_json(roh, "safety_status")
    assert ergebnis["safety_status"] == "not_safe"
    assert ergebnis["summary"] == "Gewitter"


def test_fehlendes_pflichtfeld_wirft():
    """Muss werfen, damit der Retry-Loop des Aufrufers greift."""
    roh = json.dumps({"summary": "irgendwas", "safe_window": "keins"})
    with pytest.raises(ValueError, match="safety_status"):
        parse_llm_json(roh, "safety_status")


def test_flyability_pflichtfeld():
    roh = json.dumps({"`json`": json.dumps({"experience_rating": 4})})
    assert parse_llm_json(roh, "experience_rating")["experience_rating"] == 4


def test_ohne_pflichtfeld_wird_trotzdem_entpackt():
    """Synoptik ruft ohne required_key auf — Wrapper muss trotzdem fallen."""
    innen = json.dumps({"wetterlage": "Westlage", "zonen": []})
    ergebnis = parse_llm_json(json.dumps({"`json`": innen}))
    assert ergebnis["wetterlage"] == "Westlage"


def test_kein_objekt_wirft():
    with pytest.raises(ValueError):
        parse_llm_json("[1, 2, 3]", "safety_status")


def test_kaputtes_json_wirft():
    with pytest.raises(ValueError):
        parse_llm_json("{nicht wirklich json", "safety_status")


def test_einzelfeld_antwort_bleibt_unangetastet():
    """Ein-Schluessel-Dict mit korrektem Pflichtfeld darf nicht entpackt werden."""
    roh = json.dumps({"safety_status": "safe"})
    assert parse_llm_json(roh, "safety_status") == {"safety_status": "safe"}
