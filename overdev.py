"""Ueberentwicklungs-Stufe: die Entscheidung "Quellwolken koennen hochschiessen".

DIE EINE gemeinsame Regel — genutzt vom Meteogramm (web.format_data_for_charts,
hohler Blitz), von der KI-Analyse (engine/weather_context.py, Zeile
UEBERENTWICKLUNG) und spaeter von der Validierung. Dieselbe Konstruktion wie
ensemble_thunder.is_ensemble_storm_hour: eine Funktion, damit Symbol, Text
und Messung nie auseinanderlaufen.

Vier Bedingungen je Stunde (Begruendung + Backtest: config.OVERDEV_*,
docs/GEWITTER.md par.0c):
  1. kalter Wolkentop an genug Referenzpunkten (ICON-EU, cloud_top.py)
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
