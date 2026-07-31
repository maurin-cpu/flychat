"""Tests fuer die weather_code-Aggregation ueber Referenzpunkte (Juli 2026).

Hintergrund: _aggregate_regional_data() aggregierte nur CLOUD_PARAMS und
PRECIP_USE_MIN. weather_code blieb auf data_list[0] stehen — bei Regionen also
auf EINEM von 7-16 Referenzpunkten. Gewitter an einem anderen Punkt der Region
gingen verloren (Archiv-Messung: nur ~50 % der Signale erreichten die Anzeige).

Die Tests halten drei Dinge fest:
  1. Regionen aggregieren nach Schweregrad, nicht numerisch.
  2. Spots bleiben unveraendert (Default-Pfad, 92.6 % gesund).
  3. Die Niederschlags-Aggregation wird davon nicht beruehrt.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import fetch_weather as fw


def _mk(codes, precip=None, hours=None):
    """Baut eine Referenzpunkt-Antwort mit den gegebenen Stundenwerten.

    hours richtet sich per Default nach der Anzahl Codes — die Zeitachse
    steuert die Aggregations-Schleife, eine zu kurze macht den Test blind.
    """
    hours = len(codes) if hours is None else hours
    hourly = {
        "time": [f"2026-07-31T{12 + h:02d}:00" for h in range(hours)],
        "weather_code": list(codes),
    }
    if precip is not None:
        hourly["precipitation"] = list(precip)
    return {"hourly": hourly}


# --- _severest_weather_code: Rangfolge statt numerischem max ---------------

def test_gewitter_schlaegt_alles():
    assert fw._severest_weather_code([0, 3, 95, 61]) == 95


def test_hagel_gewitter_schlaegt_gewitter():
    assert fw._severest_weather_code([95, 99, 96]) == 99


def test_starker_regen_schlaegt_leichten_schneefall():
    # Numerisch waere 71 > 65 — nach Gefaehrdung ist starker Regen schwerer.
    assert fw._severest_weather_code([65, 71]) == 65


def test_nebel_schlaegt_bedeckt():
    # Numerisch waere 45 > 3, hier faellt Rang und Zahl zufaellig zusammen.
    assert fw._severest_weather_code([3, 45]) == 45


def test_bedeckt_schlaegt_nicht_leichten_regen():
    # Numerisch waere 61 > 3; der Rang bestaetigt das hier.
    assert fw._severest_weather_code([3, 61]) == 61


def test_leere_und_none_werte():
    assert fw._severest_weather_code([]) is None
    assert fw._severest_weather_code([None, None]) is None
    assert fw._severest_weather_code([None, 95, None]) == 95


def test_unbekannter_code_verdraengt_echtes_signal_nicht():
    # Rang 0 (wie "klar") — ein erfundener Code darf das Gewitter nicht schlucken.
    assert fw._severest_weather_code([7777, 95]) == 95


# --- Region-Pfad: aggregiert ----------------------------------------------

def test_region_findet_gewitter_am_zweiten_referenzpunkt():
    """Der Kern-Bug: RP0 klar, RP3 Gewitter — die Region muss das melden."""
    data_list = [_mk([0]), _mk([2]), _mk([3]), _mk([95])]
    out = fw._aggregate_regional_data(data_list, aggregate_weather_code=True)
    assert out["hourly"]["weather_code"][0] == 95


def test_region_aggregiert_stundenweise_unabhaengig():
    """Jede Stunde wird eigenstaendig ausgewertet, nicht der Tages-Peak."""
    data_list = [_mk([0, 0, 0]), _mk([95, 0, 61])]
    out = fw._aggregate_regional_data(data_list, aggregate_weather_code=True)
    assert out["hourly"]["weather_code"] == [95, 0, 61]


def test_region_bei_nur_einem_referenzpunkt_unveraendert():
    data_list = [_mk([61])]
    out = fw._aggregate_regional_data(data_list, aggregate_weather_code=True)
    assert out["hourly"]["weather_code"][0] == 61


def test_region_none_luecke_wird_uebersprungen():
    """Fehlt der Wert an einem RP, zaehlen die uebrigen — kein Absturz."""
    data_list = [_mk([None]), _mk([95])]
    out = fw._aggregate_regional_data(data_list, aggregate_weather_code=True)
    assert out["hourly"]["weather_code"][0] == 95


def test_region_alle_none_bleibt_none():
    data_list = [_mk([None]), _mk([None])]
    out = fw._aggregate_regional_data(data_list, aggregate_weather_code=True)
    assert out["hourly"]["weather_code"][0] is None


def test_region_ungleich_lange_arrays():
    """Ein RP mit kuerzerer Zeitreihe darf die Aggregation nicht abbrechen."""
    short = {"hourly": {"time": ["2026-07-31T12:00"], "weather_code": [95]}}
    long = _mk([0, 0, 0], hours=3)
    out = fw._aggregate_regional_data([long, short], aggregate_weather_code=True)
    assert out["hourly"]["weather_code"] == [95, 0, 0]


# --- Spot-Pfad: NICHT aggregiert ------------------------------------------

def test_spot_behaelt_startplatz_code():
    """Default-Pfad (Spots): data_list[0] ist der Startplatz und bleibt stehen."""
    data_list = [_mk([0]), _mk([95]), _mk([95])]
    out = fw._aggregate_regional_data(data_list)
    assert out["hourly"]["weather_code"][0] == 0


def test_spot_default_ist_aus():
    """Ohne das Schluesselwort darf sich nichts aendern — Schutz gegen
    versehentliches Aktivieren des Region-Verhaltens auf dem Spot-Pfad."""
    data_list = [_mk([61]), _mk([99])]
    out = fw._aggregate_regional_data(data_list)
    assert out["hourly"]["weather_code"][0] == 61


# --- Niederschlag bleibt unberuehrt ---------------------------------------

def test_niederschlag_unveraendert_durch_weather_code_schalter():
    """Regen-Trefferquoten (Spot 86 %, Region 91 %) duerfen sich nicht bewegen:
    beide Schalterstellungen muessen dieselben precipitation-Werte liefern."""
    codes = [0, 95]
    precip_a = [0.0, 3.0]
    precip_b = [0.0, 4.0]

    aus = fw._aggregate_regional_data(
        [_mk(codes, precip_a, hours=2), _mk(codes, precip_b, hours=2)])
    ein = fw._aggregate_regional_data(
        [_mk(codes, precip_a, hours=2), _mk(codes, precip_b, hours=2)],
        aggregate_weather_code=True)

    assert aus["hourly"]["precipitation"] == ein["hourly"]["precipitation"]
    assert aus["hourly"]["precipitation_coverage"] == ein["hourly"]["precipitation_coverage"]
    assert aus["hourly"]["precipitation_class"] == ein["hourly"]["precipitation_class"]


def test_fehlender_weather_code_kein_absturz():
    """Nicht jeder Batch liefert weather_code (z.B. reine Druckniveau-Calls)."""
    data_list = [
        {"hourly": {"time": ["2026-07-31T12:00"], "precipitation": [1.0]}},
        {"hourly": {"time": ["2026-07-31T12:00"], "precipitation": [2.0]}},
    ]
    out = fw._aggregate_regional_data(data_list, aggregate_weather_code=True)
    assert "weather_code" not in out["hourly"]


# --- Alle Gewitter-Codes werden als Gewitter erkannt ----------------------

@pytest.mark.parametrize("code", fw.THUNDER_CODES)
def test_jeder_gewittercode_setzt_sich_durch(code):
    data_list = [_mk([0]), _mk([3]), _mk([code])]
    out = fw._aggregate_regional_data(data_list, aggregate_weather_code=True)
    assert out["hourly"]["weather_code"][0] == code
    assert int(out["hourly"]["weather_code"][0]) in fw.THUNDER_CODES


# --- Flaechenbild (thunder_class): beschreibend, nicht filternd -----------

def test_einzelzelle_bleibt_gewitter():
    """Kernentscheid: KEIN Quorum. 1 von 7 RPs ist ein Gewitter — gemessen
    haben 84 % aller Gewitterstunden genau einen Punkt. Ein Quorum haette
    das Signal geloescht."""
    data_list = [_mk([95])] + [_mk([0]) for _ in range(6)]
    out = fw._aggregate_regional_data(data_list, aggregate_weather_code=True)
    assert out["hourly"]["weather_code"][0] == 95
    assert out["hourly"]["thunder_class"][0] == "isolated"
    assert out["hourly"]["thunder_coverage"][0] == 0.14


def test_flaechiges_gewitter_wird_als_solches_erkannt():
    data_list = [_mk([95]) for _ in range(8)] + [_mk([0]) for _ in range(2)]
    out = fw._aggregate_regional_data(data_list, aggregate_weather_code=True)
    assert out["hourly"]["thunder_class"][0] == "widespread"


def test_verstreute_zellen():
    data_list = [_mk([95]) for _ in range(5)] + [_mk([0]) for _ in range(5)]
    out = fw._aggregate_regional_data(data_list, aggregate_weather_code=True)
    assert out["hourly"]["thunder_class"][0] == "scattered"


def test_kein_gewitter_kein_flaechenbild():
    data_list = [_mk([61]), _mk([3])]
    out = fw._aggregate_regional_data(data_list, aggregate_weather_code=True)
    assert out["hourly"]["thunder_class"][0] == "none"
    assert out["hourly"]["thunder_coverage"][0] == 0.0


def test_flaechenbild_nutzt_dieselben_schwellen_wie_regen():
    """Regen und Gewitter muessen dieselbe Sprache sprechen."""
    assert fw.classify_thunder_pattern(config.SYNOPTIC_PRECIP_COVERAGE_FLAECHIG) == "widespread"
    assert fw.classify_thunder_pattern(config.SYNOPTIC_PRECIP_COVERAGE_KONVEKTIV) == "scattered"
    assert fw.classify_thunder_pattern(0.01) == "isolated"
    assert fw.classify_thunder_pattern(0.0) == "none"
    assert fw.classify_thunder_pattern(None) == "none"


def test_spot_pfad_bekommt_kein_flaechenbild():
    """Ein Spot ist ein Punkt — ein Flaechenbild waere dort eine Erfindung."""
    out = fw._aggregate_regional_data([_mk([95]), _mk([0])])
    assert "thunder_class" not in out["hourly"]
    assert "thunder_coverage" not in out["hourly"]
