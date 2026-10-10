"""Wortlaut-Waechter: Freigabe- und Urteilssprache wird zu beschreibender
Sprache (Alerts-Vokabular); Aussagen, Warnungen und das UI-Tag bleiben."""
from engine.wording_guard import soften_clearance


def test_english_clearance_phrases_are_softened():
    assert soften_clearance("You can fly at Niesen today.") == "Flying looks possible at Niesen today."
    assert soften_clearance("I recommend Fiesch.") == "I would favor Fiesch."
    assert soften_clearance("My recommendation: Fiesch.") == "My assessment: Fiesch."
    assert soften_clearance("Go ahead and launch early.") == "Conditions look workable to launch early."
    assert soften_clearance("Green light for the morning.") == "No alerts for the morning."


def test_english_verdicts_become_alert_findings():
    assert soften_clearance("It is safe to fly until 14:00.") == "It is without alerts for flying until 14:00."
    assert soften_clearance("The morning is safe, the afternoon is not safe.") == \
        "The morning is without alerts, the afternoon is severe alerts."
    assert soften_clearance("Fiesch is conditionally safe today.") == "Fiesch is with alerts today."
    assert soften_clearance("A safe window from 10 to 13.") == "A window without alerts from 10 to 13."
    assert soften_clearance("Perfect conditions all day.") == "Unremarkable conditions all day."
    assert soften_clearance("Unsafe after 15:00.") == "Severe alerts after 15:00."
    assert soften_clearance("The safe windows are too short for a safe flight.") == \
        "The windows without alerts are too short for a flight without alerts."
    assert soften_clearance("Conditional rather than safe; verdict: no-go.") == \
        "Conditional rather than without alerts; verdict: severe alert."
    assert soften_clearance("Gusts stay well within safe limits.") == "Gusts stay well within the limits."
    assert soften_clearance("The region is also rated safe; the day as safe overall.") == \
        "The region is also rated 'no alerts'; the day as 'no alerts' overall."
    assert soften_clearance("A 12h safe window, calm and safe.") == "A 12h window without alerts, calm and without alerts."


def test_negations_keep_their_meaning():
    assert soften_clearance("Not recommended today.") == "Not favored today."
    assert soften_clearance("I don't recommend flying.") == "I don't favor flying."


def test_warnings_are_left_alone():
    txt = "Dangerous gusts up to 55 km/h from 13:00 — severe alerts."
    assert soften_clearance(txt) == txt


def test_german_clearance_and_verdicts_are_softened():
    assert soften_clearance("Du kannst fliegen.") == "Fliegen sieht möglich aus."
    assert soften_clearance("Ich empfehle Fiesch.") == "Ich favorisiere Fiesch."
    assert soften_clearance("Keine Freigabe für Nachmittag.") == "Keine Einschätzung für Nachmittag."
    assert soften_clearance("Nicht empfohlen.") == "Nicht favorisiert."
    assert soften_clearance("Der Tag ist bedingt sicher.") == "Der Tag ist mit Warnhinweisen."
    assert soften_clearance("Fiesch ist nicht sicher.") == "Fiesch ist mit schweren Warnhinweisen."
    assert soften_clearance("Ein sicherer Flugtag.") == "Ein Flugtag ohne Warnhinweise."
    # "sicher" allein bleibt (mehrdeutig: "sicher nicht", "sicherlich")
    assert soften_clearance("Das ist sicher nicht der Fall.") == "Das ist sicher nicht der Fall."


def test_instructions_become_findings():
    assert soften_clearance("Pilots should avoid the 11:00 hour.") == "The alert covers the 11:00 hour."
    assert soften_clearance("You should not fly after 13:00.") == "Severe alert for flying after 13:00."
    assert soften_clearance("Piloten sollten den Nachmittag meiden.") == "Der Warnhinweis gilt für den Nachmittag."


def test_cached_tree_is_softened_in_place():
    from engine.wording_guard import soften_analysis_tree
    tree = {"Hummel": {"2026-10-05": {
        "safety": {"summary": "Conditionally safe — pilots should avoid 11:00.",
                   "safety_status": "conditional", "caution_notes": ["safe window 09-11"]},
        "recommendation": "I recommend the morning.",
        "streckenflug": {"summary": "safe flight possible"},
    }}, "Leer": {"2026-10-05": {"safety": {"summary": "Alerts: gusts 40 km/h."}}}}
    assert soften_analysis_tree(tree) == 1
    res = tree["Hummel"]["2026-10-05"]
    assert res["safety"]["summary"] == "With alerts — the alert covers 11:00."
    assert res["safety"]["safety_status"] == "conditional"
    assert res["safety"]["caution_notes"] == ["window without alerts 09-11"]
    assert res["recommendation"] == "I would favor the morning."
    assert res["streckenflug"]["summary"] == "flight without alerts possible"


def test_ui_tag_is_untouched():
    txt = "Best fit: Fiesch [RECOMMENDED: Fiesch | safety=safe, rating=5]. I recommend an early start."
    out = soften_clearance(txt)
    assert "[RECOMMENDED: Fiesch | safety=safe, rating=5]" in out
    assert "I would favor an early start" in out


def test_clean_text_and_non_strings_pass_through():
    assert soften_clearance("Alerts: gusts to 35 km/h after 13:00.") == "Alerts: gusts to 35 km/h after 13:00."
    assert soften_clearance("") == ""
    assert soften_clearance(None) is None


def test_weather_as_fact_becomes_data_attribution():
    assert soften_clearance("No foehn today, light wind.") == "No foehn indicated today, light wind."
    assert soften_clearance("South foehn situation from noon.") == "Data indicating South foehn from noon."
    assert soften_clearance("No Bise on the Plateau.") == "No Bise indicated on the Plateau."
    assert soften_clearance("Heute kein Föhn.") == "Heute kein Föhn angezeigt."
    assert soften_clearance("Aktuell kein Foehn-Risiko.") == "Aktuell kein Foehn-Risiko angezeigt."
    assert soften_clearance("Keine Bise im Mittelland.") == "Keine Bise angezeigt im Mittelland."
    assert soften_clearance("Südföhnlage ab Mittag.") == "Südföhn laut Daten ab Mittag."
    # schon datenbezogen oder anderes Wort: unangetastet
    assert soften_clearance("Data show no foehn wind in the valleys.") == "Data show no foehn wind in the valleys."
    assert soften_clearance("In den Tälern kein Föhnwind.") == "In den Tälern kein Föhnwind."


def test_foehn_followed_by_noun_stays_grammatical():
    """Regression 10.10.: "No foehn breakthrough" wurde zu "No signs of foehn in
    the data breakthrough"."""
    assert soften_clearance("No foehn breakthrough at the surface.") == \
        "No foehn breakthrough indicated at the surface."
    assert soften_clearance("Currently no foehn risk.") == "Currently no foehn risk indicated."
    assert soften_clearance("calm regionally (wind below 25 km/h, no foehn).") == \
        "calm regionally (wind below 25 km/h, no foehn indicated)."
    # Reparatur gespeicherter Texte aus der alten Waechter-Version
    assert soften_clearance("No signs of foehn in the data breakthrough at the surface.") == \
        "No foehn breakthrough indicated at the surface."
    assert soften_clearance("No signs of foehn in the data shear signs: the 850 hPa wind.") == \
        "No foehn shear indicated signs: the 850 hPa wind."
    # schon richtig: unangetastet, auch beim zweiten Durchlauf
    for ok in ("No foehn signs in the vertical column.", "No foehn breakthrough indicated.",
               "No foehn indicated.", "Kein Föhn angezeigt.", "Data show no signs of foehn."):
        assert soften_clearance(ok) == ok, ok
        assert soften_clearance(soften_clearance(ok)) == ok, ok


def test_briefing_labels_never_state_weather_as_fact():
    """Kein Föhn-/Bise-/Front-Satz im Briefing beginnt mit einer Tatsache."""
    import re
    import scripts.briefing_v3_context as bc
    src = open(bc.__file__, encoding="utf-8").read()
    bad = re.findall(r'"(?:No|Kein|Keine) (?:foehn|Föhn|bise|Bise|front|Front|hazard|Gefahr)[^"]*"', src)
    assert bad == [], bad
