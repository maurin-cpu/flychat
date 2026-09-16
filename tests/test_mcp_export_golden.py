"""Golden-Test: Screening-Zeile == deterministische Caches == Tags im Textblock.

Engine offline via __new__ (Muster tests/test_decision_engine.py), synthetische
12 Stunden fuer einen Spot, Region-Lookup gepatcht. Kein Netz, kein LLM.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta

import pytest

import config


def _engine(date_str: str, windy_from: int | None = None):
    from chat_engine import WingcastEngine
    e = WingcastEngine.__new__(WingcastEngine)
    e.spots = [{
        "name": "Testberg", "fluggebiet": "Testgebiet", "region": "Ostschweiz", "analyse_region": "Testregion",
        "latitude": 46.9, "longitude": 8.4, "elevation_m": 1500, "windrichtung": "N-NO", "wind_N": 1, "wind_NE": 1,
        "wind_E": 0, "wind_SE": 0, "wind_S": 0, "wind_SW": 0, "wind_W": 0, "wind_NW": 0,
        "slope_azimuth": 20, "slope_angle": 25, "kritischer_foehn": "Süd", "terrain_type": "voralpen",
        "bemerkungen_flug": "", "bemerkung_flug_effekt": "", "bemerkungen_sicherheit": "", "bemerkung_sicherheit_effekt": "",
        "bemerkungen_sonstiges": "", "ideal_wind_max": 20,
    }]
    hourly, pl = {}, {}
    for h in range(0, 24):
        ts = f"{date_str}T{h:02d}:00"
        strong = windy_from is not None and h >= windy_from
        hourly[ts] = {
            "temperature_2m": 8 + h * 0.6, "relative_humidity_2m": 60, "cloud_base": 2600, "wind_speed_10m": 25 if strong else 6,
            "wind_direction_10m": 15, "wind_gusts_10m": 45 if strong else 12, "cloud_cover": 30, "precipitation": 0.0, "rain": 0.0,
            "precipitation_probability": 5, "cloud_cover_low": 30, "cloud_cover_mid": 0, "cloud_cover_high": 10,
            "sunshine_duration": 3000, "cape": 100, "boundary_layer_height": 1200, "surface_pressure": 850,
            "pressure_msl": 1018, "shortwave_radiation": max(0, 700 - abs(13 - h) * 110), "direct_radiation": 400,
            "diffuse_radiation": 100, "soil_moisture_0_to_1cm": 0.2, "soil_temperature_0cm": 12, "updraft": 0.5,
            "et0_fao_evapotranspiration": 0.2, "vapour_pressure_deficit": 0.8, "snow_depth": 0, "weather_code": 2,
            "convective_inhibition": 20, "lifted_index": 1.0, "boundary_layer_height_gfs": 1200,
        }
        levels = {}
        for p, alt, ws in ((1000, 100, 5), (975, 320, 6), (950, 540, 7), (925, 760, 8), (900, 990, 9), (875, 1220, 10),
                           (850, 1460, 11), (825, 1700, 12), (800, 1950, 14), (775, 2200, 16), (750, 2470, 18),
                           (700, 3010, 22), (650, 3590, 26)):
            levels[f"temperature_{p}hPa"] = 15 - alt / 150
            levels[f"wind_speed_{p}hPa"] = ws
            levels[f"wind_direction_{p}hPa"] = 250
            levels[f"geopotential_height_{p}hPa"] = alt
        pl[ts] = levels
    e.weather_data = {
        "_meta": {"last_updated": f"{date_str}T05:00:00", "spots_count": 1},
        "Testberg": {"latitude": 46.9, "longitude": 8.4, "elevation_m": 1500, "hourly_data": hourly,
                     "pressure_level_data": pl, "reference_points": [], "data_sources": {date_str: "ch2"}},
    }
    e.foehn_data = None
    e.region_weather_data = {}
    e.spot_analyses = {}
    e.region_analyses = {}
    e.station_manager = None
    e.instantdb = None
    e._ctx_gust_cache, e._ctx_tq_cache, e._ctx_foehn_cache, e._ctx_fewshot_cache = {}, {}, {}, {}
    return e


@pytest.fixture
def today():
    return datetime.now().strftime("%Y-%m-%d")


def _run_export(monkeypatch, tmp_path, engine):
    import mcp_server.export as ex
    import engine.weather_context as wc
    monkeypatch.setattr(ex, "find_region_for_point", lambda lat, lon: None)
    monkeypatch.setattr(wc, "find_region_for_point", lambda lat, lon: None, raising=False)
    monkeypatch.setattr(ex, "get_all_regions", lambda: [])
    return ex.build_export(engine, str(tmp_path))


def _read(build_dir):
    with open(os.path.join(build_dir, "screening.jsonl"), encoding="utf-8") as fh:
        rows = [json.loads(l) for l in fh if l.strip()]
    with open(os.path.join(build_dir, "meta.json"), encoding="utf-8") as fh:
        meta = json.load(fh)
    return rows, meta


def test_export_row_matches_caches_and_block(monkeypatch, tmp_path, today):
    e = _engine(today)
    build = _run_export(monkeypatch, tmp_path, e)
    rows, meta = _read(build)
    assert meta["counts"] == {"spots": 1, "rows": 1, "blocks": 1}
    assert meta["dates"] == [today]
    assert meta["thresholds"]["CLEAN_WINDOW_MIN_HOURS"] == config.CLEAN_WINDOW_MIN_HOURS
    r = rows[0]
    gust = e._ctx_gust_cache[f"Testberg|{today}"]
    tq = e._ctx_tq_cache[f"Testberg|{today}"]
    # Zeile == Cache
    assert r["wind_ok_h"] == gust["wind_ok_count"] == 12
    assert r["clean_h"] == gust["clean_hours_count"]
    assert r["longest_clean_h"] == gust["longest_clean_run_hours"]
    assert r["gust_max"] == round(gust["max_surface_gust"])
    assert r["thermal_h"] == tq["thermal_hours_total"]
    assert r["clean_windows"] == "06-18"
    assert r["foehn_level"] == "unknown" or r["foehn_level"] in ("none", "caution", "danger")
    # Zeile == Block (Tags gezaehlt)
    with open(os.path.join(build, "blocks", today, r["slug"] + ".txt"), encoding="utf-8") as fh:
        block = fh.read()
    assert block.count("[WIND-OK]") == r["wind_ok_h"]
    assert block.count("[GUST-DANGER]") == r["gust_danger_h"] == 0
    # Reihen + Profil vorhanden
    s = r["series"]
    assert s["hours"] == list(range(config.FLIGHT_HOURS_START, config.FLIGHT_HOURS_END))
    assert all(v == 6 for v in s["wind"]) and all(s["wind_ok"])
    assert s["aloft700"][0] == 22
    assert "12" in r["profiles"] and r["profiles"]["12"][0][0] == 0
    # Hoehenwind nimmt im Profil mit der Hoehe zu (synthetisch monoton)
    speeds = [p[1] for p in r["profiles"]["12"]]
    assert speeds == sorted(speeds)
    # Pointer + Dateien
    with open(os.path.join(tmp_path, "CURRENT"), encoding="utf-8") as fh:
        assert fh.read().strip() == os.path.basename(build)
    assert os.path.exists(os.path.join(build, "meteogram", r["slug"] + ".json"))
    alt = json.load(open(os.path.join(build, "altitude", r["slug"] + ".json"), encoding="utf-8"))
    assert alt[today][0]["levels"][0].keys() >= {"alt", "ws", "wd", "tx"}


def test_export_counts_gust_danger_from_afternoon(monkeypatch, tmp_path, today):
    e = _engine(today, windy_from=13)
    build = _run_export(monkeypatch, tmp_path, e)
    rows, _ = _read(build)
    r = rows[0]
    gust = e._ctx_gust_cache[f"Testberg|{today}"]
    assert r["gust_danger_h"] == gust["gust_danger_hours"] == 5  # 13..17
    assert r["clean_windows"] == "06-13"
    assert r["longest_clean_h"] == 7
    with open(os.path.join(build, "blocks", today, r["slug"] + ".txt"), encoding="utf-8") as fh:
        assert fh.read().count("[GUST-DANGER]") == 5
    # Trend sichtbar in der Reihe
    assert r["series"]["gust"][:3] == [12, 12, 12] and r["series"]["gust"][-1] == 45


def test_old_builds_pruned(monkeypatch, tmp_path, today):
    import mcp_server.export as ex
    for old in ("build-20260901-0600", "build-20260902-0600", "build-20260903-0600"):
        os.makedirs(os.path.join(tmp_path, old))
    build = _run_export(monkeypatch, tmp_path, _engine(today))
    builds = sorted(b for b in os.listdir(tmp_path) if b.startswith("build-"))
    assert len(builds) == ex.KEEP_BUILDS
    assert os.path.basename(build) in builds and "build-20260901-0600" not in builds
