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


def test_ui_tag_is_untouched():
    txt = "Best fit: Fiesch [RECOMMENDED: Fiesch | safety=safe, rating=5]. I recommend an early start."
    out = soften_clearance(txt)
    assert "[RECOMMENDED: Fiesch | safety=safe, rating=5]" in out
    assert "I would favor an early start" in out


def test_clean_text_and_non_strings_pass_through():
    assert soften_clearance("Alerts: gusts to 35 km/h after 13:00.") == "Alerts: gusts to 35 km/h after 13:00."
    assert soften_clearance("") == ""
    assert soften_clearance(None) is None
