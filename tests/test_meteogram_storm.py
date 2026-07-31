"""Tests fuer das Blitz-Symbol im Meteogramm (web.format_data_for_charts).

Bis Juli 2026 kam der Blitz allein aus dem deterministischen weather_code —
also aus genau der Quelle, die Konvektion regelmaessig verpasst. Die KI bekam
die Ensemble-Aussage laengst, die Anzeige nicht: Zentralschweizer Voralpen
zeigte am 02.08. einen blanken Tag, waehrend 15 von 21 Membern ein Gewitter
sahen.

Massgeblich ist jetzt das SCHWERPUNKT-FENSTER des Tages — dieselbe Aussage,
die im LLM-Kontext steht. Anzeige und KI-Eingabe erzaehlen damit dieselbe
Geschichte.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from web import format_data_for_charts


def _hourly(day="2026-08-02", hours=range(8, 20), weather_code=None):
    out = {}
    for h in hours:
        out[f"{day}T{h:02d}:00"] = {
            "temperature_2m": 20.0,
            "precipitation": 0.0,
            "precipitation_probability": 0,
            "weather_code": weather_code,
            "cloud_base": 2500,
            "cloud_cover": 40,
            "wind_speed_10m": 10.0,
            "wind_direction_10m": 270,
        }
    return out


def _ens(day="2026-08-02", pct=71, peak=("13:00", "17:00"), hourly_share=None):
    return {day: {
        "probability_pct": pct,
        "n_members": 21,
        "peak_start": peak[0] if peak else None,
        "peak_end": peak[1] if peak else None,
        "hourly_share_pct": hourly_share or {},
        "level": "hoch",
    }}


def _storm_hours(chart):
    return sorted(p["time"][11:16] for p in chart["precipitation"] if p.get("storm"))


def test_schwerpunktfenster_erzeugt_blitze():
    """Der gemeldete Fall: 71 % der Member, Schwerpunkt 13-17 h,
    deterministisch nichts. Vorher blieb der Tag leer."""
    c = format_data_for_charts(_hourly(), thunder_ensemble=_ens())
    assert _storm_hours(c) == ["13:00", "14:00", "15:00", "16:00", "17:00"]


def test_ohne_ensemble_bleibt_alles_beim_alten():
    """Spots bekommen kein Ensemble — dort zaehlt weiter nur der weather_code."""
    c = format_data_for_charts(_hourly(weather_code=3))
    assert _storm_hours(c) == []


def test_spot_mit_modellgewitter_zeigt_weiter_blitz():
    c = format_data_for_charts(_hourly(weather_code=95))
    assert len(_storm_hours(c)) == 12


def test_deterministisches_gewitter_ueberlebt_schwaches_ensemble():
    """Ein hartes Modell-Gewitter darf nie verschwinden, auch wenn das
    Ensemble unter der Schwelle liegt."""
    c = format_data_for_charts(
        _hourly(weather_code=95),
        thunder_ensemble=_ens(pct=2, peak=None),
    )
    assert len(_storm_hours(c)) == 12


def test_unter_der_anzeige_schwelle_kein_blitz():
    c = format_data_for_charts(
        _hourly(),
        thunder_ensemble=_ens(pct=config.ENSEMBLE_THUNDER_METEOGRAM_DAY_PCT - 1))
    assert _storm_hours(c) == []


def test_ab_der_anzeige_schwelle_gibt_blitz():
    c = format_data_for_charts(
        _hourly(),
        thunder_ensemble=_ens(pct=config.ENSEMBLE_THUNDER_METEOGRAM_DAY_PCT,
                              peak=("15:00", "16:00")))
    assert _storm_hours(c) == ["15:00", "16:00"]


def test_anzeige_ist_zurueckhaltender_als_der_text():
    """Zwei getrennte Schwellen mit Absicht: ein Satz im Analysetext ist billig,
    ein Blitz im Meteogramm ist laut. Fall 01.08. (19 %) — Text erwaehnt,
    Meteogramm schweigt."""
    assert (config.ENSEMBLE_THUNDER_METEOGRAM_DAY_PCT
            > config.ENSEMBLE_THUNDER_MENTION_PCT)
    c = format_data_for_charts(
        _hourly(), thunder_ensemble=_ens(pct=19, peak=("15:00", "16:00")))
    assert _storm_hours(c) == []


def test_einzelstunde_mit_hohem_anteil_zaehlt_auch_ausserhalb():
    """Eine Stunde mit sehr hoher Zustimmung wird auch dann gezeigt, wenn sie
    ausserhalb des Schwerpunkts liegt."""
    share = {"09:00": config.ENSEMBLE_THUNDER_METEOGRAM_PCT + 5}
    c = format_data_for_charts(
        _hourly(), thunder_ensemble=_ens(pct=19, peak=("15:00", "16:00"),
                                         hourly_share=share))
    assert "09:00" in _storm_hours(c)


def test_anderer_tag_bleibt_unberuehrt():
    """Das Fenster gilt nur fuer seinen Tag."""
    hourly = _hourly(day="2026-08-02")
    hourly.update(_hourly(day="2026-08-03"))
    c = format_data_for_charts(hourly, thunder_ensemble=_ens(day="2026-08-02"))
    tage = {p["time"][:10] for p in c["precipitation"] if p.get("storm")}
    assert tage == {"2026-08-02"}


def test_fehlendes_schwerpunktfenster_stuerzt_nicht_ab():
    c = format_data_for_charts(_hourly(), thunder_ensemble=_ens(peak=None))
    assert _storm_hours(c) == []


def test_meta_schluessel_wird_ignoriert():
    """thunder_ensemble enthaelt neben den Tagen einen _meta-Eintrag."""
    ens = _ens()
    ens["_meta"] = {"model": "meteoswiss_icon_ch2", "n_members": 21}
    c = format_data_for_charts(_hourly(), thunder_ensemble=ens)
    assert len(_storm_hours(c)) == 5


def test_prozentwert_wird_mitgeliefert():
    """Der Tooltip soll die Herkunft benennen koennen."""
    share = {"13:00": 38}
    c = format_data_for_charts(_hourly(), thunder_ensemble=_ens(hourly_share=share))
    rec = [p for p in c["precipitation"] if p["time"][11:16] == "13:00"][0]
    assert rec["thunder_ens_pct"] == 38
