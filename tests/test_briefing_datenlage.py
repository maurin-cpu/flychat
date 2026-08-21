# -*- coding: utf-8 -*-
"""Schutz fuer die Datenlage-Regel im Briefing (Vorgabe vom 21.08.2026).

Real passiert: Kunden erhielten leere Briefings, weil die Bewertungen fehlten.
Die Mail las sich dann wie ein Wetterurteil ("diese Woche nichts in deinen
Regionen") — ein Ausfall war fuer den Kunden nicht von einer echten
Schlechtwetter-Woche zu unterscheiden.

Geprueft werden die drei Faelle, an denen sich der Versand entscheidet:

  keine Daten   keine einzige Bewertung fuer die Abo-Regionen -> kein Versand
  teilweise     Luecken werden benannt, nie in eine Flugaussage umgedeutet
  alle Daten    unveraendertes Verhalten

Entschieden wird ausschliesslich an der Datenlage. Die Ursache (abgebrochener
Lauf, Provider-Stoerung, leeres Guthaben, Zeitueberschreitung) darf keine Rolle
spielen — eine ursachenbasierte Regel deckt immer nur die Ausfaelle ab, die
schon einmal passiert sind.
"""
import pytest

import email_service as es


REGION_A = "region_a"
REGION_B = "region_b"


def _spot(name, region, band="green", rating=4):
    return {
        "spot": name,
        "region_id": region,
        "region_name": region,
        "rating": float(rating),
        "experience_rating": rating,
        "experience_stars": rating,
        "safety_band": band,
        "safety_status": {"green": "safe", "amber": "conditional",
                          "red": "not_safe", "no_data": "no_data"}[band],
        "is_conditional": band == "amber",
        "best_window": "11:00-15:00",
        "flyability": {},
        "safety": {},
    }


def _region(region, band="green", rating=4):
    return {
        "region_id": region,
        "region_name": region,
        "rating": float(rating),
        "experience_rating": rating,
        "experience_stars": rating,
        "safety_band": band,
    }


def _briefing(days):
    """days: Liste von (datum, [spots], [regionen])."""
    return {
        "generated_at": "2026-08-21T06:00:00",
        "days": [{"date": d, "top_spots": s, "top_regions": r} for d, s, r in days],
    }


def _abo(regionen):
    return {"id": 1, "email": "pilot@example.com", "regions": list(regionen),
            "action_token": "tok"}


# ---------------------------------------------------------------------------
# Die Messung selbst
# ---------------------------------------------------------------------------

def test_alle_daten_ist_voll():
    bd = _briefing([
        ("2026-08-21", [_spot("S1", REGION_A)], [_region(REGION_A)]),
        ("2026-08-22", [_spot("S1", REGION_A)], [_region(REGION_A)]),
    ])
    cov = es.briefing_coverage(_abo([REGION_A]), bd)
    assert cov["state"] == "voll"
    assert cov["cells_rated"] == cov["cells"] == 2


def test_keine_daten_ist_leer():
    bd = _briefing([("2026-08-21", [], []), ("2026-08-22", [], [])])
    cov = es.briefing_coverage(_abo([REGION_A]), bd)
    assert cov["state"] == "leer"
    assert cov["cells_rated"] == 0


def test_no_data_eintrag_zaehlt_als_luecke_nicht_als_bewertung():
    """Eine leere Huelle darf nicht als 'bewertet' durchgehen — sonst greift
    das Gate nie, obwohl der Kunde nichts Verwertbares bekommt."""
    bd = _briefing([
        ("2026-08-21", [_spot("S1", REGION_A, band="no_data", rating=0)],
         [_region(REGION_A, band="no_data", rating=0)]),
    ])
    cov = es.briefing_coverage(_abo([REGION_A]), bd)
    assert cov["state"] == "leer"


def test_fehlende_region_macht_teilweise():
    bd = _briefing([
        ("2026-08-21", [_spot("S1", REGION_A)], [_region(REGION_A)]),
    ])
    cov = es.briefing_coverage(_abo([REGION_A, REGION_B]), bd)
    assert cov["state"] == "teilweise"
    assert cov["missing_regions"] == [REGION_B]


def test_ursache_spielt_keine_rolle():
    """Zwei voellig verschiedene Ausfallursachen, identische Datenlage —
    identisches Urteil. Genau das ist der Punkt der Regel."""
    leer_wegen_abbruch = _briefing([("2026-08-21", [], [])])
    leer_wegen_no_data = _briefing([
        ("2026-08-21", [_spot("S1", REGION_A, band="no_data", rating=0)], []),
    ])
    a = es.briefing_coverage(_abo([REGION_A]), leer_wegen_abbruch)
    b = es.briefing_coverage(_abo([REGION_A]), leer_wegen_no_data)
    assert a["state"] == b["state"] == "leer"


# ---------------------------------------------------------------------------
# Wirkung auf die Mail
# ---------------------------------------------------------------------------

def test_tag_ohne_bewertung_ist_unbekannt_nicht_bedingt():
    """Frueher hob ein no_data-Spot den Tag auf 'conditional' — aus einem
    Datenloch wurde die Flugaussage 'bedingt fliegbar'."""
    bd = _briefing([
        ("2026-08-21", [_spot("S1", REGION_A, band="no_data", rating=0)],
         [_region(REGION_A)]),
    ])
    ctx = es.build_briefing_context(_abo([REGION_A]), bd)
    tag = ctx["days"][0]
    assert tag["tier"] != "conditional"
    assert tag["shown_spots"] == []


def test_tag_ganz_ohne_daten_ist_unbekannt_nicht_none():
    bd = _briefing([
        ("2026-08-21", [], []),
        ("2026-08-22", [_spot("S1", REGION_A)], [_region(REGION_A)]),
    ])
    ctx = es.build_briefing_context(_abo([REGION_A]), bd)
    assert ctx["days"][0]["tier"] == "unknown"
    assert ctx["days"][0]["has_data"] is False
    assert ctx["days"][1]["has_data"] is True


def test_abo_region_ohne_bewertung_bleibt_in_der_matrix():
    """Frueher fiel eine Region ohne Analyse komplett aus der Uebersicht —
    der Kunde sah seine Abo-Region gar nicht."""
    bd = _briefing([
        ("2026-08-21", [_spot("S1", REGION_A)], [_region(REGION_A)]),
    ])
    ctx = es.build_briefing_context(_abo([REGION_A, REGION_B]), bd)
    ids = [r["region_id"] for r in ctx["region_matrix"]]
    assert REGION_B in ids
    zeile = next(r for r in ctx["region_matrix"] if r["region_id"] == REGION_B)
    assert all(c["tier"] == "unknown" for c in zeile["days"])


def test_luecken_hinweis_nennt_zahlen():
    bd = _briefing([
        ("2026-08-21", [_spot("S1", REGION_A)], [_region(REGION_A)]),
    ])
    ctx = es.build_briefing_context(_abo([REGION_A, REGION_B]), bd)
    assert ctx["gap_notice"]
    assert "1" in ctx["gap_notice"] and "2" in ctx["gap_notice"]


def test_kein_hinweis_wenn_alles_da():
    bd = _briefing([
        ("2026-08-21", [_spot("S1", REGION_A)], [_region(REGION_A)]),
    ])
    ctx = es.build_briefing_context(_abo([REGION_A]), bd)
    assert ctx["gap_notice"] == ""
    assert ctx["coverage"]["state"] == "voll"


def test_verdict_kommt_nie_aus_einem_unbekannten_tag():
    bd = _briefing([("2026-08-21", [], []), ("2026-08-22", [], [])])
    ctx = es.build_briefing_context(_abo([REGION_A]), bd)
    assert ctx["verdict"] is None


def test_alter_datenstand_wird_ausgewiesen():
    bd = _briefing([("2026-08-21", [_spot("S1", REGION_A)], [_region(REGION_A)])])
    bd["analyses_at"] = "2020-01-01T06:00:00"
    ctx = es.build_briefing_context(_abo([REGION_A]), bd)
    assert ctx["stale_notice"]


def test_frischer_datenstand_ohne_hinweis():
    from datetime import datetime
    bd = _briefing([("2026-08-21", [_spot("S1", REGION_A)], [_region(REGION_A)])])
    bd["analyses_at"] = datetime.now().isoformat()
    ctx = es.build_briefing_context(_abo([REGION_A]), bd)
    assert ctx["stale_notice"] == ""


# ---------------------------------------------------------------------------
# Versand-Sperre
# ---------------------------------------------------------------------------

def _render(ctx):
    """Beide Mail-Templates mit blankem Jinja2 rendern (ohne Flask).

    Die Templates haengen an nichts ausser `t` — so faellt ein kaputter
    Zweig hier auf, statt erst im Versand.
    """
    from pathlib import Path
    from jinja2 import Environment, FileSystemLoader
    import i18n

    root = Path(__file__).resolve().parent.parent / "templates"
    env = Environment(loader=FileSystemLoader(str(root)))
    env.globals["t"] = i18n.t
    return (env.get_template("email/briefing.html").render(**ctx),
            env.get_template("email/briefing.txt").render(**ctx))


def test_mail_rendert_mit_luecken_und_nennt_sie():
    bd = _briefing([
        ("2026-08-21", [_spot("S1", REGION_A)], [_region(REGION_A)]),
        ("2026-08-22", [], []),
    ])
    ctx = es.build_briefing_context(_abo([REGION_A, REGION_B]), bd)
    html, text = _render(ctx)
    # Die Luecke steht als solche drin — nicht als "nicht fliegbar".
    assert "KEINE BEWERTUNG" in text
    assert "?" in text
    assert ctx["gap_notice"] in text
    assert ctx["gap_notice"] in html


def test_mail_rendert_unveraendert_wenn_alles_da():
    bd = _briefing([
        ("2026-08-21", [_spot("S1", REGION_A)], [_region(REGION_A)]),
    ])
    ctx = es.build_briefing_context(_abo([REGION_A]), bd)
    html, text = _render(ctx)
    assert "KEINE BEWERTUNG" not in text
    assert "S1" in text and "S1" in html


def test_kein_versand_ohne_jede_bewertung(monkeypatch):
    gesendet = []
    monkeypatch.setattr(es, "send_email",
                        lambda *a, **k: gesendet.append(a) or True)
    monkeypatch.setattr(es, "send_email_async",
                        lambda *a, **k: gesendet.append(a))
    bd = _briefing([("2026-08-21", [], [])])
    ok = es.send_briefing_email(_abo([REGION_A]), bd, async_send=False)
    assert ok is False
    assert gesendet == []
