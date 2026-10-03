"""Föhn-Talpunkte: Datei-Integrität und Verschieben eines Punkts."""
import json
import shutil

import pytest

import config
import foehn_talpunkte


def test_ausgelieferte_punkte_sind_vollstaendig():
    punkte = foehn_talpunkte.load_talpunkte()
    assert len(punkte) == 23
    ids = [p["id"] for p in punkte]
    assert len(set(ids)) == len(ids)
    regionen = {line.split(",")[0] for line in config.REGIONEN_CSV_PATH.read_text(encoding="utf-8").splitlines()[1:]}
    for p in punkte:
        assert p["region_id"] in regionen, p["id"]
        assert p["gruppe"] in ("A", "B", "C")
        assert 45.0 <= p["lat"] <= 48.5 and 5.0 <= p["lon"] <= 11.5


def test_update_verschiebt_nur_einen_punkt(tmp_path, monkeypatch):
    kopie = tmp_path / "foehn_talpunkte.geojson"
    shutil.copy(config.FOEHN_TALPUNKTE_PATH, kopie)
    monkeypatch.setattr(config, "FOEHN_TALPUNKTE_PATH", kopie)
    vorher = {p["id"]: (p["lat"], p["lon"]) for p in foehn_talpunkte.load_talpunkte()}

    punkt = foehn_talpunkte.update_talpunkt("alt", 46.88123, 8.63456)

    assert (punkt["lat"], punkt["lon"]) == (46.8812, 8.6346)
    nachher = {p["id"]: (p["lat"], p["lon"]) for p in foehn_talpunkte.load_talpunkte()}
    assert nachher["alt"] == (46.8812, 8.6346)
    assert {k: v for k, v in nachher.items() if k != "alt"} == {k: v for k, v in vorher.items() if k != "alt"}
    assert "_doc" in json.loads(kopie.read_text(encoding="utf-8"))


def test_update_unbekannte_id(tmp_path, monkeypatch):
    kopie = tmp_path / "foehn_talpunkte.geojson"
    shutil.copy(config.FOEHN_TALPUNKTE_PATH, kopie)
    monkeypatch.setattr(config, "FOEHN_TALPUNKTE_PATH", kopie)
    with pytest.raises(ValueError):
        foehn_talpunkte.update_talpunkt("gibtsnicht", 46.9, 8.6)
