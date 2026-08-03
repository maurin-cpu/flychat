"""Tests fuer das Blitz-Symbol im Meteogramm (web.format_data_for_charts).

Stand 02.08.2026 (PLAN_gewitter_anzeige Teil B, Schritte 1 + 2). Zwei Regeln:

1. Der Blitz kommt aus dem STUENDLICHEN Member-Anteil, nie aus dem Tageswert.
   Bis 02.08. fuellte der Tageswert das ganze Schwerpunkt-Fenster. Er ist aber
   der Anteil der Member, die irgendwann im Flugfenster an irgendeinem der 16
   Referenzpunkte zuenden — im Sommer nahezu gesaettigt (Median 95 %). Auf
   Stunden gemalt erzeugte er 53 von 217 Blitzstunden.

2. Ein Ensemble-Blitz braucht einen PLAUSIBILITAETSANKER in derselben Stunde:
   NIEDERSCHLAG UND Instabilitaet (CAPE oder Lifted Index). Vorher stand die
   Haelfte aller Blitze bei unter 50 % Bewoelkung und ohne Regen — Tessin
   Zentral 04.08. 14:00 zeigte einen Blitz bei 2 % Bewoelkung.

   Seit 03.08.2026 ist der Regen PFLICHT (vorher: Regen ODER Bewoelkung).
   Saison-Backtest: die Wolken-Alternative liess 61 % der gewitterfreien
   Tage durch und rettete genau einen Gewittertag von 113.

Der deterministische Gewittercode 95/96/99 bleibt ungefiltert.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from web import format_data_for_charts

# Anker-erfuellende Stunde: Modell-Regen und instabil genug.
_ANCHOR_OK = {"precipitation": config.THUNDER_ANCHOR_PRECIP_MM,
              "cape": config.THUNDER_ANCHOR_CAPE_JKG + 100}


def _hourly(day="2026-08-02", hours=range(8, 20), weather_code=None, **over):
    out = {}
    for h in hours:
        rec = {
            "temperature_2m": 20.0,
            "precipitation": 0.0,
            "precipitation_probability": 0,
            "weather_code": weather_code,
            "cloud_base": 2500,
            "cloud_cover": 40,
            "cape": 0.0,
            "wind_speed_10m": 10.0,
            "wind_direction_10m": 270,
        }
        rec.update(over)
        out[f"{day}T{h:02d}:00"] = rec
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


def _share(*hours, pct=None):
    pct = config.ENSEMBLE_THUNDER_METEOGRAM_PCT + 5 if pct is None else pct
    return {h: pct for h in hours}


def _storm_hours(chart):
    return sorted(p["time"][11:16] for p in chart["precipitation"] if p.get("storm"))


# --- Schritt 1: Tageswert malt keine Stunden mehr -------------------------

def test_tageswert_allein_erzeugt_keine_blitze():
    """Der Kern von Schritt 1: hoher Tageswert, Schwerpunkt 13-17 h, aber kein
    stuendlicher Anteil — frueher fuenf Blitze, jetzt keiner."""
    c = format_data_for_charts(_hourly(**_ANCHOR_OK), thunder_ensemble=_ens())
    assert _storm_hours(c) == []


def test_stuendlicher_anteil_erzeugt_blitz():
    c = format_data_for_charts(
        _hourly(**_ANCHOR_OK),
        thunder_ensemble=_ens(hourly_share=_share("14:00", "15:00")))
    assert _storm_hours(c) == ["14:00", "15:00"]


def test_stunde_unter_der_schwelle_bleibt_leer():
    c = format_data_for_charts(
        _hourly(**_ANCHOR_OK),
        thunder_ensemble=_ens(hourly_share=_share(
            "14:00", pct=config.ENSEMBLE_THUNDER_METEOGRAM_PCT - 1)))
    assert _storm_hours(c) == []


def test_blitz_auch_ausserhalb_des_schwerpunkts():
    """Ohne Fenster-Logik ist die Stunde selbst massgeblich — egal wo sie liegt."""
    c = format_data_for_charts(
        _hourly(**_ANCHOR_OK),
        thunder_ensemble=_ens(peak=("15:00", "16:00"),
                              hourly_share=_share("09:00")))
    assert _storm_hours(c) == ["09:00"]


# --- Schritt 2: Plausibilitaetsanker --------------------------------------

def test_kein_blitz_ohne_wolken_und_ohne_regen():
    """Der gemeldete Fall Tessin Zentral: Ensemble feuert, aber 2 % Bewoelkung,
    kein Regen. CAPE allein genuegt nicht."""
    c = format_data_for_charts(
        _hourly(cloud_cover=2, cape=750.0),
        thunder_ensemble=_ens(hourly_share=_share("14:00")))
    assert _storm_hours(c) == []


def test_kein_blitz_ohne_cape():
    """Regen allein ist keine Konvektion."""
    c = format_data_for_charts(
        _hourly(precipitation=1.0, cape=50.0),
        thunder_ensemble=_ens(hourly_share=_share("14:00")))
    assert _storm_hours(c) == []


def test_wolken_ohne_regen_genuegen_nicht_mehr():
    """Kern der Verschaerfung vom 03.08.: bewoelkt + instabil, aber der
    det. Lauf hat keinen Regen -> kein Blitz. Vorher passierte diese Stunde
    den Anker — im Saison-Backtest der Grund fuer 61 % Durchlass an
    gewitterfreien Tagen."""
    c = format_data_for_charts(
        _hourly(cloud_cover=95, precipitation=0.0,
                cape=config.THUNDER_ANCHOR_CAPE_JKG + 500),
        thunder_ensemble=_ens(hourly_share=_share("14:00")))
    assert _storm_hours(c) == []


def test_regen_und_instabilitaet_erzeugen_blitz():
    c = format_data_for_charts(
        _hourly(cloud_cover=10, precipitation=config.THUNDER_ANCHOR_PRECIP_MM,
                cape=config.THUNDER_ANCHOR_CAPE_JKG),
        thunder_ensemble=_ens(hourly_share=_share("14:00")))
    assert _storm_hours(c) == ["14:00"]


def test_fehlendes_cape_zaehlt_nicht_als_erfuellt():
    """Aeltere Caches ohne CAPE duerfen den Anker nicht stillschweigend passieren."""
    h = _hourly(precipitation=1.0)
    for rec in h.values():
        rec.pop("cape")
    c = format_data_for_charts(h, thunder_ensemble=_ens(hourly_share=_share("14:00")))
    assert _storm_hours(c) == []


def test_lifted_index_ersetzt_fehlendes_cape():
    """Hoehenkorrektur: Oberwallis kam am 02.08. nie ueber CAPE 290, XC Therm
    zeigte dort 1,5 h Gewitter. Der Lifted Index rettet solche Stunden."""
    c = format_data_for_charts(
        _hourly(precipitation=1.0, cape=100.0,
                lifted_index=config.THUNDER_ANCHOR_LI - 1),
        thunder_ensemble=_ens(hourly_share=_share("14:00")))
    assert _storm_hours(c) == ["14:00"]


def test_stabiler_lifted_index_rettet_nicht():
    c = format_data_for_charts(
        _hourly(precipitation=1.0, cape=100.0, lifted_index=+5.0),
        thunder_ensemble=_ens(hourly_share=_share("14:00")))
    assert _storm_hours(c) == []


def test_anker_gilt_nicht_fuer_den_deterministischen_code():
    """Ein hartes Modell-Gewitter bleibt sichtbar — es stammt aus demselben
    Lauf wie Wolken und Regen und ist per Konstruktion stimmig."""
    c = format_data_for_charts(_hourly(weather_code=95, cloud_cover=0, cape=0.0))
    assert len(_storm_hours(c)) == 12


# --- Unveraendertes Verhalten ---------------------------------------------

def test_ohne_ensemble_bleibt_alles_beim_alten():
    """Spots bekommen kein Ensemble — dort zaehlt weiter nur der weather_code."""
    c = format_data_for_charts(_hourly(weather_code=3))
    assert _storm_hours(c) == []


def test_deterministisches_gewitter_ueberlebt_schwaches_ensemble():
    c = format_data_for_charts(
        _hourly(weather_code=95),
        thunder_ensemble=_ens(pct=2, peak=None),
    )
    assert len(_storm_hours(c)) == 12


def test_anzeige_ist_zurueckhaltender_als_der_text():
    """Zwei getrennte Schwellen mit Absicht: ein Satz im Analysetext ist billig,
    ein Blitz im Meteogramm ist laut."""
    assert (config.ENSEMBLE_THUNDER_METEOGRAM_PCT
            > config.ENSEMBLE_THUNDER_MENTION_PCT)


def test_anderer_tag_bleibt_unberuehrt():
    hourly = _hourly(day="2026-08-02", **_ANCHOR_OK)
    hourly.update(_hourly(day="2026-08-03", **_ANCHOR_OK))
    c = format_data_for_charts(
        hourly,
        thunder_ensemble=_ens(day="2026-08-02", hourly_share=_share("14:00")))
    tage = {p["time"][:10] for p in c["precipitation"] if p.get("storm")}
    assert tage == {"2026-08-02"}


def test_fehlendes_schwerpunktfenster_stuerzt_nicht_ab():
    c = format_data_for_charts(_hourly(**_ANCHOR_OK),
                               thunder_ensemble=_ens(peak=None))
    assert _storm_hours(c) == []


def test_meta_schluessel_wird_ignoriert():
    """thunder_ensemble enthaelt neben den Tagen einen _meta-Eintrag."""
    ens = _ens(hourly_share=_share("14:00"))
    ens["_meta"] = {"model": "meteoswiss_icon_ch2", "n_members": 21}
    c = format_data_for_charts(_hourly(**_ANCHOR_OK), thunder_ensemble=ens)
    assert _storm_hours(c) == ["14:00"]


def test_prozentwert_wird_mitgeliefert():
    """Der Tooltip soll die Herkunft benennen koennen — auch dann, wenn der
    Anker den Blitz unterdrueckt."""
    c = format_data_for_charts(_hourly(),
                               thunder_ensemble=_ens(hourly_share={"13:00": 38}))
    rec = [p for p in c["precipitation"] if p["time"][11:16] == "13:00"][0]
    assert rec["thunder_ens_pct"] == 38
