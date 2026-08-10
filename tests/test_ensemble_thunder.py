"""Tests fuer die Ensemble-Gewitterwahrscheinlichkeit (ICON-CH2-EPS).

Kein Netzzugriff — geprueft wird die Rechenlogik auf konstruierten Membern.
Der Netzpfad (fetch_ensemble) wird bewusst nicht getestet: er haengt am freien
Open-Meteo-Endpunkt mit eigenen Rate-Limits.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import convection as et

TIMES = [f"2026-08-02T{h:02d}:00" for h in range(24)]


def _members(spec, n=21):
    """spec: {member_index: {hour: code}} -> Liste von Werte-Arrays."""
    out = []
    for m in range(n):
        row = [0] * len(TIMES)
        for h, code in (spec.get(m) or {}).items():
            row[h] = code
        out.append(row)
    return out


# --- member_keys ----------------------------------------------------------

def test_member_keys_kontrolllauf_zuerst():
    hourly = {
        "time": [], "cape_member02": [], "cape": [], "cape_member01": [],
        "precipitation": [],
    }
    keys = et.member_keys(hourly, "cape")
    assert keys == ["cape", "cape_member01", "cape_member02"]


def test_member_keys_trennt_variablen():
    hourly = {"cape": [], "cape_member01": [], "precipitation": [],
              "precipitation_member01": []}
    assert et.member_keys(hourly, "precipitation") == [
        "precipitation", "precipitation_member01"]


# --- thunder_probability --------------------------------------------------

def test_anteil_ist_member_bezogen_nicht_stunden_bezogen():
    """3 von 21 Membern -> 14 %, egal wie viele Stunden sie zuenden."""
    mem = _members({0: {12: 95}, 1: {13: 95, 14: 96, 15: 99}, 2: {16: 95}})
    r = et.thunder_probability(mem, TIMES, "2026-08-02", 11, 20)
    assert r["n_hit"] == 3
    assert r["n_members"] == 21
    assert r["probability_pct"] == 14


def test_gewitter_ausserhalb_des_fensters_zaehlt_nicht():
    mem = _members({0: {4: 95}, 1: {22: 95}})
    r = et.thunder_probability(mem, TIMES, "2026-08-02", 11, 20)
    assert r["probability_pct"] == 0
    assert r["level"] is None


def test_anderer_tag_zaehlt_nicht():
    mem = _members({0: {12: 95}})
    r = et.thunder_probability(mem, TIMES, "2026-08-03", 11, 20)
    assert r["probability_pct"] is None


def test_alle_gewittercodes_zaehlen():
    for code in et.THUNDER_CODES:
        mem = _members({0: {12: code}})
        assert et.thunder_probability(mem, TIMES, "2026-08-02", 11, 20)["n_hit"] == 1


def test_regen_ohne_gewitter_zaehlt_nicht():
    mem = _members({0: {12: 65}, 1: {13: 82}})
    assert et.thunder_probability(mem, TIMES, "2026-08-02", 11, 20)["n_hit"] == 0


def test_stundenanteil_wird_ausgewiesen():
    mem = _members({0: {12: 95}, 1: {12: 95}, 2: {15: 95}})
    r = et.thunder_probability(mem, TIMES, "2026-08-02", 11, 20)
    assert r["hourly_share_pct"]["12:00"] == 10   # 2/21
    assert r["hourly_share_pct"]["15:00"] == 5    # 1/21
    assert r["hourly_share_pct"]["11:00"] == 0


def test_schwerpunkt_umfasst_stunden_ab_halber_spitze():
    # Spitze 14:00 (4 Member), 13:00 hat 2 = genau die Haelfte -> gehoert dazu.
    # 17:00 hat 1 = darunter -> faellt raus.
    mem = _members({
        0: {13: 95, 14: 95}, 1: {13: 95, 14: 95},
        2: {14: 95}, 3: {14: 95}, 4: {17: 95},
    })
    r = et.thunder_probability(mem, TIMES, "2026-08-02", 11, 20)
    assert r["peak_start"] == "13:00"
    assert r["peak_end"] == "14:00"


def test_kein_signal_kein_schwerpunkt():
    r = et.thunder_probability(_members({}), TIMES, "2026-08-02", 11, 20)
    assert r["probability_pct"] == 0
    assert r["peak_start"] is None


def test_leere_eingabe():
    r = et.thunder_probability([], TIMES, "2026-08-02", 11, 20)
    assert r["probability_pct"] is None
    assert r["n_members"] == 0


# --- Warnstufen -----------------------------------------------------------

def test_stufen_folgen_der_konfiguration():
    assert et.probability_level(config.ENSEMBLE_THUNDER_MENTION_PCT - 1) is None
    assert et.probability_level(config.ENSEMBLE_THUNDER_MENTION_PCT) == "moeglich"
    assert et.probability_level(config.ENSEMBLE_THUNDER_ELEVATED_PCT) == "erhoeht"
    assert et.probability_level(config.ENSEMBLE_THUNDER_HIGH_PCT) == "hoch"
    assert et.probability_level(100) == "hoch"


def test_stufe_none_bei_fehlendem_wert():
    assert et.probability_level(None) is None


def test_schwellen_sind_aufsteigend():
    """Schutz vor einer Fehlkalibrierung, die die Stufen unerreichbar macht."""
    assert (config.ENSEMBLE_THUNDER_MENTION_PCT
            < config.ENSEMBLE_THUNDER_ELEVATED_PCT
            < config.ENSEMBLE_THUNDER_HIGH_PCT <= 100)


# --- Referenzpunkte je Member zusammenfassen ------------------------------

def test_referenzpunkte_werden_je_member_zusammengefasst():
    """Zuendet Member 1 nur am zweiten Referenzpunkt, gilt das fuer die Region."""
    rp_a = {"weather_code": [0, 0], "weather_code_member01": [0, 0]}
    rp_b = {"weather_code": [0, 0], "weather_code_member01": [95, 0]}
    merged = et.merge_points_per_member([rp_a, rp_b], "weather_code")
    assert merged[0] == [0, 0]      # Kontrolllauf: nirgends Gewitter
    assert merged[1] == [95, 0]     # Member 1: an RP B -> zaehlt


def test_member_werden_nicht_vermischt():
    """Gewitter bei Member 1 darf nicht bei Member 2 auftauchen."""
    rp_a = {"weather_code_member01": [95], "weather_code_member02": [0],
            "weather_code": [0]}
    merged = et.merge_points_per_member([rp_a], "weather_code")
    assert merged == [[0], [95], [0]]


def test_zusammenfassung_nutzt_schwere_nicht_zahl():
    # 65 (starker Regen) muss 71 (leichter Schneefall) schlagen.
    rp_a = {"weather_code": [65]}
    rp_b = {"weather_code": [71]}
    assert et.merge_points_per_member([rp_a, rp_b], "weather_code") == [[65]]


def test_leere_punktliste():
    assert et.merge_points_per_member([], "weather_code") == []


# --- Mindestanteil der Referenzpunkte (02.08.2026) ------------------------
# Vorher genuegte ein einziger von 7 Punkten, damit ein Member fuer die ganze
# Region als Gewitter zaehlte. Im Vergleich gegen XC Therm lagen alle 5
# Faelle, in denen nur wir Gewitter zeigten, im Voralpenguertel — dort spannen
# die Punkte vom Talboden bis zum Grat und sind am unterschiedlichsten.

def test_punktzaehler_zaehlt_treffer_statt_schwerstem_code():
    rp_a = {"weather_code": [95, 0]}
    rp_b = {"weather_code": [95, 65]}
    rp_c = {"weather_code": [0, 0]}
    assert et.merge_points_thunder_count([rp_a, rp_b, rp_c]) == [[2, 0]]


def test_ein_einzelner_punkt_traegt_die_region_nicht_mehr():
    """Der Kern der Aenderung: 1 von 3 Punkten reicht nicht mehr."""
    mem = [[1] * len(TIMES)]           # jede Stunde genau EIN Punkt mit Gewitter
    r = et.thunder_probability(mem, TIMES, "2026-08-02", 11, 20, quorum=2)
    assert r["probability_pct"] == 0


def test_zwei_punkte_genuegen():
    mem = [[0] * len(TIMES)]
    mem[0][12] = 2
    r = et.thunder_probability(mem, TIMES, "2026-08-02", 11, 20, quorum=2)
    assert r["probability_pct"] == 100
    assert r["hourly_share_pct"]["12:00"] == 100
    assert r["hourly_share_pct"]["13:00"] == 0


def test_ohne_quorum_bleibt_das_alte_verhalten():
    """Bestandsschutz: ohne quorum sind die Werte weiter Wettercodes."""
    mem = _members({0: {12: 95}})
    assert et.thunder_probability(mem, TIMES, "2026-08-02", 11, 20)["n_hit"] == 1


def test_quorum_ist_konfiguriert_und_plausibel():
    assert 1 <= config.ENSEMBLE_THUNDER_POINT_QUORUM <= 4


# --- Warn-Kachel: sichtbar, aber niemals ein No-Go ------------------------

from engine.decision_engine import build_region_topic_tags  # noqa: E402


def _thunder_tag(gi):
    tags = [t for t in build_region_topic_tags({}, gi) if t["topic"] == "THUNDERSTORM"]
    return tags[0] if tags else None


def test_ensemble_erzeugt_sichtbare_kachel():
    """Der gemeldete Fall: Zentralschweizer Alpen 02.08. — 71 % der Member,
    deterministisch nichts. Vorher blieb der Tag in der Anzeige komplett leer."""
    t = _thunder_tag({
        "thunderstorm_hours": 0, "thunder_ens_pct": 71,
        "thunder_ens_level": "hoch",
        "thunder_ens_peak_start": "13:00", "thunder_ens_peak_end": "17:00",
    })
    assert t is not None
    assert t["severity"] == "warn"
    assert "71%" in t["value"]
    assert t["time"] == "13:00-17:00"


def test_ensemble_kachel_ist_nie_ein_no_go():
    """Auch bei 100 % bleibt es eine Warnung — die Schwellen sind ungemessen."""
    t = _thunder_tag({"thunderstorm_hours": 0, "thunder_ens_pct": 100,
                      "thunder_ens_level": "hoch"})
    assert t["severity"] == "warn"


def test_unter_der_schwelle_keine_kachel():
    assert _thunder_tag({"thunderstorm_hours": 0, "thunder_ens_pct": 8,
                         "thunder_ens_level": None}) is None


def test_deterministisches_gewitter_bleibt_stop():
    """Das harte Gate darf vom Ensemble nicht verdraengt oder verdoppelt werden."""
    t = _thunder_tag({
        "thunderstorm_hours": 3, "thunderstorm_in_window_h": 3,
        "thunder_ens_pct": 71, "thunder_ens_level": "hoch",
    })
    assert t["severity"] == "stop"
    assert "71%" not in t["value"]


def test_nur_eine_gewitter_kachel():
    """Kein Doppel-Eintrag, wenn beide Quellen etwas sagen."""
    tags = [t for t in build_region_topic_tags({}, {
        "thunderstorm_hours": 2, "thunderstorm_in_window_h": 2,
        "thunder_ens_pct": 60, "thunder_ens_level": "hoch",
    }) if t["topic"] == "THUNDERSTORM"]
    assert len(tags) == 1


def test_stufe_folgt_der_konfiguration_nicht_dem_cache():
    """Die Schwelle ist Anzeige-Politik: eine Aenderung muss sofort wirken,
    nicht erst nach dem naechsten Wetterlauf. Darum wird die Stufe aus
    probability_pct neu berechnet und das gespeicherte `level` ignoriert."""
    assert et.probability_level(19) == "moeglich"   # bei MENTION=15
    assert et.probability_level(14) is None
