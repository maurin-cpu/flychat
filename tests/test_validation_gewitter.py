# -*- coding: utf-8 -*-
"""Schutz gegen die drei Blindstellen des Gewitter-Richters (04.08.2026).

Alle drei kosteten still Urteile, ohne dass irgendwo ein Fehler auftauchte:
Messung zu frueh geholt, Region ueber den Namen verloren, beides unbemerkt
im Scoreboard gelandet.
"""
import datetime

from scripts import validation_common as vc
from scripts.validate_gewitter_daily import (letzter_vollstaendiger_tag,
                                             tag_vollstaendig)


def _tag(bis: str, n_stationen: int = 5) -> dict:
    """Messwerte-Struktur, deren Stationen bis `bis` Uhr liefern."""
    zeiten = []
    h, m = 0, 0
    while f"{h:02d}:{m:02d}" <= bis:
        zeiten.append(f"{h:02d}:{m:02d}")
        m += 10
        if m == 60:
            h, m = h + 1, 0
    return {f"st{i}": {t: [0.0, 10.0, 20.0, 5.0, 950.0] for t in zeiten}
            for i in range(n_stationen)}


# --- Vollstaendigkeit ------------------------------------------------------

def test_voller_tag_ist_vollstaendig():
    assert tag_vollstaendig(_tag("23:50")) is True


def test_zu_frueh_geholter_tag_ist_unvollstaendig():
    # Genau der Fall vom 03.08.2026: die OGD-Datei endete bei 01:50.
    assert tag_vollstaendig(_tag("01:50")) is False


def test_einzelne_hinkende_station_blockiert_den_tag_nicht():
    tage = _tag("23:50")
    tage["nachzuegler"] = {t: [0.0, 10.0, 20.0, 5.0, 950.0]
                           for t in ("00:00", "00:10")}
    assert tag_vollstaendig(tage) is True


def test_leere_messung_ist_nicht_vollstaendig():
    assert tag_vollstaendig({}) is False


# --- Welcher Tag darf ueberhaupt validiert werden? -------------------------

def test_morgenlauf_nimmt_vorvortag():
    now = datetime.datetime(2026, 8, 4, 6, 20)
    assert letzter_vollstaendiger_tag(now) == datetime.date(2026, 8, 2)


def test_nachmittagslauf_nimmt_vortag():
    now = datetime.datetime(2026, 8, 4, 15, 0)
    assert letzter_vollstaendiger_tag(now) == datetime.date(2026, 8, 3)


# --- Namens-Join -----------------------------------------------------------

def test_umlaut_und_ae_treffen_sich():
    assert vc.norm_region("Waadtländer Alpen") == vc.norm_region("Waadtlaender Alpen")


def test_normalisierung_ignoriert_schreibweise_und_leerzeichen():
    assert vc.norm_region("  JURA  Ost ") == vc.norm_region("Jura Ost")


def test_verschiedene_regionen_bleiben_verschieden():
    assert vc.norm_region("Jura Ost") != vc.norm_region("Jura West")
