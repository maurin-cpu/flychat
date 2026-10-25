# -*- coding: utf-8 -*-
"""Region rot → Spot nie gruen, und die Begruendung schreibt die KI (25.10.2026).

Archiv 02.08.–25.10.2026: 111 Spots standen gruen ("No alerts"), waehrend ihre
Region schwere Warnhinweise hatte. 104× hatte die KI den Regions-Kontext und
hat ihn uebergangen, 7× lag der Spot ausserhalb aller Polygone und bekam gar
keinen. Ein Code-Override waere ein gelber Spot ohne Grund — darum fragt der
Code die KI nach, statt den Status selbst zu setzen.
"""
import json
from types import SimpleNamespace

import pytest

from engine.analyzers import AnalyzersMixin, _region_schwer
from engine.weather_context import _format_region_context_block


def _antwort(daten):
    msg = SimpleNamespace(content=json.dumps(daten))
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")],
                           usage=None)


class _Client:
    def __init__(self, antworten):
        self.antworten = list(antworten)
        self.aufrufe = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.aufrufe.append(kw["messages"])
        return _antwort(self.antworten.pop(0))


class _Engine(AnalyzersMixin):
    analysis_model = "test-model"

    def __init__(self, antworten):
        self.analysis_client = _Client(antworten)

    def _analysis_call_kwargs(self):
        return {}

    def _record_call_usage(self, response, kind):
        pass

    def _post_process_safety_spot(self, result, spot, date_str):
        return result


GRUEN = {"safety_status": "safe", "caution_notes": [], "summary": "No alerts."}
GELB = {"safety_status": "conditional",
        "caution_notes": ["Region: upper wind 48-71 km/h at 3000m"],
        "summary": "Alert: the region shows upper wind 48-71 km/h."}
REGION_ROT = {"region": "Zentralschweizer Alpen", "safety_status": "not_safe",
              "primary_no_go": "ALOFT_DANGER",
              "no_go_reasons": ["Upper wind: 48-71 km/h at 3000m, all hours"]}
SPOT = {"name": "Haldi"}


def _lauf(engine, region):
    return engine._safety_analysis_single_spot_day(SPOT, "2026-10-22", "KONTEXT",
                                                   region_result=region)


def test_rueckfrage_macht_spot_gelb_mit_text_der_ki():
    e = _Engine([GRUEN, GELB])
    r = _lauf(e, REGION_ROT)
    assert r["safety_status"] == "conditional"
    assert r["caution_notes"] == GELB["caution_notes"]      # Text kommt von der KI
    assert "RegionUntergrenzeRueckfrage" in r["_decisions_applied"]
    zweiter = e.analysis_client.aufrufe[1]
    assert zweiter[-2] == {"role": "assistant", "content": json.dumps(GRUEN)}
    assert "48-71 km/h" in zweiter[-1]["content"]
    assert "Zentralschweizer Alpen" in zweiter[-1]["content"]


def test_ki_bleibt_gruen_code_ueberschreibt_nicht():
    e = _Engine([GRUEN, GRUEN])
    r = _lauf(e, REGION_ROT)
    assert r["safety_status"] == "safe"
    assert len(e.analysis_client.aufrufe) == 2


@pytest.mark.parametrize("region", [
    None,
    {"region": "X", "safety_status": "conditional"},
    {"region": "X", "safety_status": "safe"},
])
def test_ohne_rote_region_keine_rueckfrage(region):
    e = _Engine([GRUEN])
    assert _lauf(e, region)["safety_status"] == "safe"
    assert len(e.analysis_client.aufrufe) == 1


def test_spot_schon_gelb_keine_rueckfrage():
    e = _Engine([GELB])
    _lauf(e, REGION_ROT)
    assert len(e.analysis_client.aufrufe) == 1


def test_region_schwer_liest_beide_formen():
    flach = _region_schwer(REGION_ROT)
    gespeichert = _region_schwer({"region": "Zentralschweizer Alpen",
                                  "safety": {k: v for k, v in REGION_ROT.items()
                                             if k != "region"}})
    assert flach == gespeichert
    assert flach["gruende"] == REGION_ROT["no_go_reasons"]
    assert _region_schwer({"safety": {"safety_status": "conditional"}}) is None


def test_kontextblock_nennt_untergrenze_nur_bei_roter_region():
    rot = _format_region_context_block(REGION_ROT, {"region": "Zentralschweizer Alpen"})
    assert "REGION-STATUS-UNTERGRENZE" in rot
    assert "48-71 km/h" in rot
    gelb = _format_region_context_block(dict(REGION_ROT, safety_status="conditional"),
                                        {"region": "Zentralschweizer Alpen"})
    assert "REGION-STATUS-UNTERGRENZE" not in gelb


def test_spot_ausserhalb_polygon_bekommt_angezeigte_region():
    """Monte Bisbino liegt in Italien, ausserhalb aller Polygone; die App zeigt
    ihn unter Locarnese / Bellinzonese."""
    from source_area import find_region_for_point, find_region_for_spot
    spot = {"latitude": 45.8734, "longitude": 9.062,
            "analyse_region": "Locarnese / Bellinzonese"}
    assert find_region_for_point(spot["latitude"], spot["longitude"]) is None
    assert find_region_for_spot(spot)["id"] == "locarnese_bellinzonese"
    assert find_region_for_spot(dict(spot, analyse_region="")) is None
