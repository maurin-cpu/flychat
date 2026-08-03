"""Tests fuer die Ueberentwicklungs-Stufe (convection.py + hohler Blitz).

Stand 03.08.2026 (docs/GEWITTER.md par.0d). Vier Bedingungen je Stunde:
kalter Wolkentop an genug Punkten + KONSISTENZ mit der angezeigten
Bewoelkung + Instabilitaet + kein Blauthermik-Veto. Der harte Blitz
gewinnt immer.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import convection
from web import format_data_for_charts

CT_OK = {"cold_share_pct": config.OVERDEV_TOP_SHARE_PCT + 5, "top_min_c": -32.0}
DATA_OK = {"cloud_cover": config.OVERDEV_CLOUD_MIN_PCT + 20,
           "cape": config.THUNDER_ANCHOR_CAPE_JKG + 100}


# --- Kernregel -------------------------------------------------------------

def test_alle_bedingungen_erfuellt():
    assert convection.is_overdev_hour(CT_OK, DATA_OK) is True


def test_harte_blitzstunde_gewinnt():
    """Ein Symbol, eine Botschaft: in einer Gewitterstunde kein Zusatzsymbol."""
    assert convection.is_overdev_hour(CT_OK, DATA_OK, storm=True) is False


def test_ohne_wolkentop_nichts():
    assert convection.is_overdev_hour(None, DATA_OK) is False


def test_zu_wenige_kalte_punkte():
    ct = {"cold_share_pct": config.OVERDEV_TOP_SHARE_PCT - 10, "top_min_c": -30.0}
    assert convection.is_overdev_hour(ct, DATA_OK) is False


def test_konsistenz_keine_wolken_keine_warnung():
    """Die User-Regel vom 03.08.: das Meteogramm darf nie wolkenlos zeigen
    und daneben Ueberentwicklung behaupten."""
    data = dict(DATA_OK, cloud_cover=config.OVERDEV_CLOUD_MIN_PCT - 20)
    assert convection.is_overdev_hour(CT_OK, data) is False


def test_stabile_luft_keine_warnung():
    data = dict(DATA_OK, cape=50.0)
    assert convection.is_overdev_hour(CT_OK, data) is False


def test_lifted_index_ersetzt_cape():
    """Hoehenkorrektur wie beim Blitz-Anker: CAPE allein wuerde
    Hochalpenregionen stummschalten."""
    data = dict(DATA_OK, cape=100.0, lifted_index=config.THUNDER_ANCHOR_LI - 1)
    assert convection.is_overdev_hour(CT_OK, data) is True


def test_blauthermik_veto():
    """AKTIVE Thermik, die die Wolkenbasis klar nicht erreicht: keine
    Quellwolke moeglich — keine Warnung (User-Kriterium: Wolken-Gefahr)."""
    therm = {"climb_rate": 1.8, "max_height": 2000,
             "lcl": 2000 + config.OVERDEV_THERMIK_MARGIN_M + 100}
    assert convection.is_overdev_hour(CT_OK, DATA_OK, therm=therm) is False


def test_thermik_erreicht_basis_kein_veto():
    therm = {"climb_rate": 1.8, "max_height": 2600, "lcl": 2400}
    assert convection.is_overdev_hour(CT_OK, DATA_OK, therm=therm) is True


def test_ohne_aktive_thermik_kein_veto():
    """Abend-/Frontkonvektion: keine Thermik heisst nicht keine Gefahr —
    die Abend-Gewitter waren der blinde Fleck des Testtags 02.08."""
    therm = {"climb_rate": 0.0, "max_height": 850, "lcl": 2210}
    assert convection.is_overdev_hour(CT_OK, DATA_OK, therm=therm) is True


def test_fehlende_thermik_blockiert_nicht():
    """Fail-open: die Stufe ist Zusatzinfo, kein Gate."""
    assert convection.is_overdev_hour(CT_OK, DATA_OK, therm=None) is True


# --- Meteogramm-Payload ----------------------------------------------------

def _hourly(day="2026-08-03", hours=range(8, 20), **over):
    out = {}
    for h in hours:
        rec = {"temperature_2m": 22.0, "precipitation": 0.0,
               "precipitation_probability": 0, "weather_code": 2,
               "cloud_base": 2500, "cloud_cover": 60,
               "cape": config.THUNDER_ANCHOR_CAPE_JKG + 100,
               "wind_speed_10m": 10.0, "wind_direction_10m": 270}
        rec.update(over)
        out[f"{day}T{h:02d}:00"] = rec
    return out


def _overdev_hours(chart):
    return sorted(p["time"][11:16] for p in chart["precipitation"]
                  if p.get("overdev"))


def test_chart_overdev_stunden():
    ct = {"2026-08-03T14:00": CT_OK, "2026-08-03T15:00": CT_OK}
    c = format_data_for_charts(_hourly(), cloud_top=ct)
    assert _overdev_hours(c) == ["14:00", "15:00"]
    rec = [p for p in c["precipitation"] if p["time"][11:16] == "14:00"][0]
    assert rec["overdev_top_c"] == -32.0


def test_chart_gewitterstunde_ohne_zusatzsymbol():
    ct = {"2026-08-03T14:00": CT_OK}
    c = format_data_for_charts(_hourly(weather_code=95), cloud_top=ct)
    assert _overdev_hours(c) == []


def test_chart_ohne_cloud_top_kein_overdev():
    c = format_data_for_charts(_hourly())
    assert _overdev_hours(c) == []


def test_chart_wolkenlos_kein_overdev():
    """Konsistenz-Regel Ende-zu-Ende: klare Stunde -> kein hohler Blitz."""
    ct = {"2026-08-03T14:00": CT_OK}
    c = format_data_for_charts(_hourly(cloud_cover=5), cloud_top=ct)
    assert _overdev_hours(c) == []
