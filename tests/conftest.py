"""Gemeinsame Test-Einstellungen.

Die Windkarte des Foehn-Blocks (foehn_indicators.fetch_wind_karte) holt ~440
Rasterpunkte von Open-Meteo. Tests, die decide_foehn_summary nur mit gemocktem
fetch_foehn_data aufrufen, wuerden sonst ins Netz gehen — hier abgeschaltet.
Tests der Windkarte selbst rufen evaluate_wind_karte mit eigenen Daten auf.
"""
from unittest import mock

import pytest


@pytest.fixture(autouse=True)
def _keine_windkarte_aus_dem_netz():
    with mock.patch("foehn_indicators.fetch_wind_karte", return_value=None):
        yield
