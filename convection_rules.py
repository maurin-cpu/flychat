"""Konvektions-Regeln: ALLE Entscheidungen zu Gewitter und Ueberentwicklung.

Eine Datei fuer die Regel-Schicht (Umbau 03.08.2026, vorher verteilt auf
convection_ensemble.py und convection_rules.py — Daten-Abruf jetzt getrennt in
convection_ensemble.py und convection_convection_cloud_top.py):

  is_ensemble_storm_hour()  ->  harter Blitz (Ensemble-Anteil + Anker)
  thunder_anchor_ok()       ->  Plausibilitaetsanker (Regen-Pflicht seit 03.08.)
  probability_level()       ->  Text-Warnstufe (moeglich/erhoeht/hoch)
  is_overdev_hour()         ->  hohler Blitz "Quellwolken koennen hochschiessen"

Genutzt von Meteogramm (web.py), KI-Analyse (engine/weather_context.py) und
Validierung — EINE Quelle der Wahrheit, damit Symbol, Text und Messung nie
auseinanderlaufen.

DIE EINE gemeinsame Regel — genutzt vom Meteogramm (web.format_data_for_charts,
hohler Blitz), von der KI-Analyse (engine/weather_context.py, Zeile
UEBERENTWICKLUNG) und spaeter von der Validierung. Dieselbe Konstruktion wie
convection_rules.is_ensemble_storm_hour: eine Funktion, damit Symbol, Text
und Messung nie auseinanderlaufen.

Vier Bedingungen je Stunde (Begruendung + Backtest: config.OVERDEV_*,
docs/GEWITTER.md par.0c):
  1. kalter Wolkentop an genug Referenzpunkten (ICON-EU, convection_cloud_top.py)
  2. Konsistenz: die ANGEZEIGTE Bewoelkung dieser Stunde zeigt Wolken
  3. Instabilitaet (CAPE oder Lifted Index)
  4. kein Blauthermik-Veto (Thermik erreicht die Wolkenbasis)

AUSDRUECKLICH weiche Stufe: sperrt nie, setzt kein No-Go, und in einer
harten Blitz-Stunde gewinnt der Blitz — ein Symbol, eine Botschaft.
"""
from __future__ import annotations

import config


def _num(v):
    return v if isinstance(v, (int, float)) else None


def is_overdev_hour(cloud_top_entry, data, therm=None, storm=False):
    """Zeigt diese Stunde Ueberentwicklungs-Potenzial?

    cloud_top_entry: {"cold_share_pct": .., "top_min_c": ..} aus
                     _regions[rid]["cloud_top"][zeitstempel] (None = kein Top)
    data:            deterministische Stundenwerte (cloud_cover, cape,
                     lifted_index) — DIESELBEN Werte, die das Meteogramm zeigt
    therm:           Thermik der Stunde (max_height, lcl) — Spot-Median der
                     Region; fehlt sie, entscheidet der Rest (fail-open,
                     die Stufe ist Zusatzinfo, kein Gate)
    storm:           True = harte Blitz-Stunde -> immer False
    """
    if storm:
        return False
    if not isinstance(cloud_top_entry, dict):
        return False
    share = _num(cloud_top_entry.get("cold_share_pct"))
    if share is None or share < config.OVERDEV_TOP_SHARE_PCT:
        return False
    if not isinstance(data, dict):
        return False

    # Konsistenz-Regel (User 03.08.): nie "wolkenlos" anzeigen und daneben
    # Ueberentwicklung behaupten. Massstab ist die angezeigte Bewoelkung.
    cloud = _num(data.get("cloud_cover"))
    if cloud is None or cloud < config.OVERDEV_CLOUD_MIN_PCT:
        return False

    cape = _num(data.get("cape"))
    li = _num(data.get("lifted_index"))
    unstable = ((cape is not None and cape >= config.THUNDER_ANCHOR_CAPE_JKG)
                or (li is not None and li <= config.THUNDER_ANCHOR_LI))
    if not unstable:
        return False

    # Blauthermik-Veto: AKTIVE Thermik (climb > 0), die die Wolkenbasis klar
    # nicht erreicht -> es waechst keine Quellwolke aus der Grenzschicht
    # (User-Kriterium: nur Wolken-Gefahr zaehlt). Bewusst NUR bei aktiver
    # Thermik: Stunden ohne Thermik (Abend, Morgen) haben zwar keine
    # Blauthermik, aber sehr wohl moegliche Front-/Abendkonvektion — die
    # Abend-Gewitter waren der grosse blinde Fleck des Testtags 02.08.
    if isinstance(therm, dict):
        climb = _num(therm.get("climb_rate"))
        max_h = _num(therm.get("max_height"))
        lcl = _num(therm.get("lcl"))
        if (climb is not None and climb > 0
                and max_h is not None and lcl is not None
                and max_h + config.OVERDEV_THERMIK_MARGIN_M < lcl):
            return False
    return True


def onset_hour(hours):
    """Erste Ueberentwicklungs-Stunde ("HH:MM"-Liste) — fuer das Wording
    "Quellwolken koennen ab ~14 Uhr hochschiessen"."""
    return min(hours) if hours else None


# --------------------------------------------------------------------------
# Gewitter-Regeln (aus convection_ensemble.py hierher gezogen, 03.08.2026)
# --------------------------------------------------------------------------


def probability_level(prob):
    """Weiche Warnstufe. None = unterhalb der Erwaehnungsschwelle.

    UNKALIBRIERT — Startpunkt laut Auftrag (20-30 % der Member).
    """
    if prob is None:
        return None
    if prob >= config.ENSEMBLE_THUNDER_HIGH_PCT:
        return "hoch"
    if prob >= config.ENSEMBLE_THUNDER_ELEVATED_PCT:
        return "erhoeht"
    if prob >= config.ENSEMBLE_THUNDER_MENTION_PCT:
        return "moeglich"
    return None


def thunder_anchor_ok(data):
    """Plausibilitaetsanker: gibt die Stunde ein Gewitter ueberhaupt her?

    Das Ensemble kennt nur Wettercodes und wurde bis 02.08.2026 nie gegen die
    Stunde gegengelesen, in der es angezeigt wird — die Haelfte aller Blitze
    stand bei unter 50 % Bewoelkung und ohne einen Tropfen Regen (Tessin
    Zentral 04.08. 14:00 bei 2 % Bewoelkung).

    Bedingung: Instabilitaet UND Niederschlag, beides in DERSELBEN Stunde aus
    dem deterministischen Lauf. Instabilitaet heisst CAPE ODER Lifted Index —
    CAPE allein waere hoehenabhaengig und wuerde Hochalpenregionen dauerhaft
    stummschalten. Schwellen und Begruendung — auch warum CIN bewusst fehlt —
    in config.THUNDER_ANCHOR_*.

    Bewoelkung als Regen-Alternative wurde am 03.08.2026 ENTFERNT: im
    Saison-Backtest (15.05.-02.08., 2320 Regionstage gegen SwissMetNet-
    Signaturen) liess der Wolken-Zweig 61 % aller gewitterfreien Tage durch
    — im Sommer hat fast jede Region irgendwo 50 % Bewoelkung. Die
    Regen-Pflicht senkt das auf 24 % und kostet genau einen Gewittertag von
    113 (Tessin Nord 16.07., det. Lauf voellig trocken). Zahlen:
    docs/GEWITTER.md, Abschnitt "Anker verschaerft".

    Gilt nur fuer den Ensemble-Weg, nie fuer den deterministischen
    Gewittercode 95/96/99: der stammt aus demselben Lauf wie Wolken und Regen
    und ist per Konstruktion in sich stimmig.
    """
    if not isinstance(data, dict):
        return False

    def _num(key):
        v = data.get(key)
        return v if isinstance(v, (int, float)) else None

    cape = _num("cape")
    li = _num("lifted_index")
    unstable = ((cape is not None and cape >= config.THUNDER_ANCHOR_CAPE_JKG)
                or (li is not None and li <= config.THUNDER_ANCHOR_LI))
    if not unstable:
        return False
    precip = _num("precipitation")
    return precip is not None and precip >= config.THUNDER_ANCHOR_PRECIP_MM


def is_ensemble_storm_hour(share_pct, data):
    """Zeigt diese Stunde ein Ensemble-Gewitter? Die EINE gemeinsame Regel.

    Wird sowohl vom Blitz-Symbol im Meteogramm (web.format_data_for_charts)
    als auch von der Gewitter-Kachel und dem LLM-Kontext
    (engine/weather_context.py) benutzt. Vorher hatte jede Schicht ihre eigene
    Rechnung: das Symbol lief ab 02.08. auf Stundenwerten, die Kachel weiter
    auf dem Tageswert — dieselbe Region zeigte im Meteogramm keinen Blitz und
    im Text daneben eine Gewitterwarnung.

    share_pct: Anteil der Member mit Gewitter in DIESER Stunde.
    """
    if share_pct is None or share_pct < config.ENSEMBLE_THUNDER_METEOGRAM_PCT:
        return False
    return thunder_anchor_ok(data)
