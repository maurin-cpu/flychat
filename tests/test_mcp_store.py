"""ExportStore: Pointer-Reload, Frische, Lazy-Reader — offline mit Mini-Export in tmp_path."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

import pytest

from mcp_server.store import STALE_REFUSE_H, STALE_WARN_H, ExportMissing, ExportStore

NOW = datetime(2026, 9, 17, 9, 0)


def make_row(spot="Niederbauen", slug="niederbauen-x", date="2026-09-17", **kw) -> dict:
    r = dict(
        spot=spot, slug=slug, fluggebiet="Emmetten", region="Zentralschweizer Alpen", region_id="zentralschweiz",
        date=date, elev=1573, sector="N", foehn_crit="Süd", lat=46.93, lon=8.55, model="ch2",
        wind_ok_h=10, wind_wrong_h=2, clean_h=9, longest_clean_h=6, window_start=6, clean_windows="06-12,14-17",
        hard_warn_h=1, wind_warn_h=0, wind_danger_h=0, gust_max=24.0, gust_warn_h=0, gust_danger_h=0,
        aloft_warn_h=0, aloft_danger_h=0, aloft_gust_danger_h=0, aloft_pattern=None, wind_swing_deg=40.0,
        rain_h=0, rain_win_h=0, rain_sandwiched=False, max_dry_gap=12, thunder_h=0, thunder_win_h=0,
        cloud_below_to_h=0, cloud_near_to_h=0, min_base_m=2400.0,
        thermal_h=6, prod_h=4, prod_strict_h=2, peak_climb=1.8, sustained_peak=1.6, work_height_agl=900,
        rough_danger_h=0, cloud_structure="cumulus", low_cloud_pct=30.0, band_shallow_h=0,
        foehn_level="none", foehn_dp=1.2, foehn_dir="Süd",
        t_max=18.0, cloud_mean_pct=30.0, sun_h=6, wind_mean_ok=6.0, cape_max=120.0, precip_mm=0.0,
        region_thunder_pct=0.0,
        series={
            "hours": list(range(6, 18)),
            "wind": [2, 3, 3, 4, 5, 6, 8, 9, 10, 9, 7, 5], "gust": [8, 9, 10, 12, 15, 18, 22, 24, 24, 20, 16, 12],
            "dir": [350, 355, 0, 5, 10, 10, 15, 20, 20, 15, 10, 5], "wind_ok": [True] * 12,
            "aloft700": [10, 10, 11, 12, 14, 16, 18, 20, 22, 22, 20, 18], "aloft700_dir": [250] * 12,
            "aloft850": [4, 4, 5, 5, 6, 7, 8, 9, 9, 8, 7, 6],
            "climb": [0, 0, 0, 0.3, 0.8, 1.2, 1.6, 1.8, 1.8, 1.5, 1.0, 0.4],
            "top": [1600, 1600, 1610, 1700, 1900, 2100, 2300, 2450, 2500, 2400, 2200, 1900],
            "base": [None, None, 2600, 2600, 2500, 2400, 2400, 2450, 2500, 2500, 2600, 2700],
            "low": [40, 40, 35, 30, 25, 25, 30, 30, 30, 35, 30, 20], "mid": [0] * 12,
            "rain": [0.0] * 12, "cape": [0, 0, 0, 10, 40, 80, 120, 120, 100, 60, 20, 0],
            "sw": [0, 20, 120, 300, 480, 620, 700, 720, 660, 520, 340, 150],
            "temp": [9, 9, 10, 12, 14, 16, 17, 18, 18, 17, 16, 14],
        },
        profiles={"09": [[0, 4, 5, 8], [500, 6, 10, 6], [1000, 9, 20, 4], [1500, 12, 240, 2], [2000, 14, 250, 1], [3000, 20, 250, 0]],
                  "12": [[0, 8, 15, 14], [500, 10, 20, 10], [1000, 14, 30, 6], [1500, 17, 240, 3], [2000, 20, 250, 1], [3000, 26, 250, 0]]},
    )
    r.update(kw)
    return r


def write_export(root, build="build-20260917-0600", rows=None, last_updated="2026-09-17T05:02:00",
                 dates=("2026-09-17", "2026-09-18"), block_text="BLOCK Niederbauen 2026-09-17\n[WIND-OK] x10"):
    b = os.path.join(root, build)
    for sub in ("blocks", "meteogram", "altitude"):
        os.makedirs(os.path.join(b, sub), exist_ok=True)
    rows = rows if rows is not None else [make_row(date=d) for d in dates]
    slugs = {r["slug"]: r for r in rows}
    with open(os.path.join(b, "screening.jsonl"), "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    spots = [{"name": r["spot"], "slug": r["slug"], "fluggebiet": r["fluggebiet"], "region": r["region"],
              "region_id": r["region_id"], "lat": r["lat"], "lon": r["lon"], "elev": r["elev"],
              "windrichtung": r["sector"], "kritischer_foehn": r["foehn_crit"], "terrain_type": "voralpen",
              "slope_azimuth": 10, "slope_angle": 25, "bemerkungen_flug": "Talwind ab 13 Uhr",
              "bemerkung_flug_effekt": None, "bemerkungen_sicherheit": None, "bemerkung_sicherheit_effekt": None,
              "bemerkungen_sonstiges": "Bahn"} for r in slugs.values()]
    meta = {"built_at": "2026-09-17T06:10:00", "last_updated": last_updated, "dates": list(dates),
            "hours": list(range(6, 18)), "forecast_days": 3,
            "thresholds": {"CLEAN_WINDOW_MIN_HOURS": 2, "GUST_DANGER_KMH": 40},
            "models_by_date": {d: {"ch2": len(spots)} for d in dates},
            "counts": {"spots": len(spots), "rows": len(rows), "blocks": len(rows)},
            "profile_agl_steps": [0, 500, 1000, 1500, 2000, 3000], "profile_hours": [9, 12, 15]}
    regions = {}
    for s in spots:
        reg = regions.setdefault(s["region_id"], {"id": s["region_id"], "name": s["region"], "terrain_type": "alpen",
                                                   "kritischer_foehn": "Süd", "spot_count": 0})
        reg["spot_count"] += 1
    for name, obj in (("meta.json", meta), ("spots.json", spots), ("regions.json", list(regions.values())),
                      ("foehn.json", {"available": True, "days": {d: [{"hour": 9, "level": "none", "direction": "Süd", "delta_p": 1.2,
                                                                       "crest_wind": 20, "crest_dir": 250, "humidity_nord": 60}] for d in dates}})):
        with open(os.path.join(b, name), "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False)
    for r in rows:
        os.makedirs(os.path.join(b, "blocks", r["date"]), exist_ok=True)
        with open(os.path.join(b, "blocks", r["date"], r["slug"] + ".txt"), "w", encoding="utf-8") as fh:
            fh.write(block_text)
    for slug in slugs:
        with open(os.path.join(b, "meteogram", slug + ".json"), "w", encoding="utf-8") as fh:
            json.dump({d: {"wind": [{"time": f"{d}T12:00:00", "speed": 8, "gusts": 22, "direction": 15}],
                           "precipitation": [{"time": f"{d}T12:00:00", "amount": 0.0, "probability": 5, "weather_code": 2, "storm": False}],
                           "thermik": [{"time": f"{d}T12:00:00", "cape": 120, "climb_rate": 1.6, "max_height": 2300, "lcl": 2400}],
                           "cloudbase": [{"time": f"{d}T12:00:00", "height": 2400, "cover_low": 30, "cover_mid": 0, "cover_high": 10}]}
                       for d in dates}, fh)
        with open(os.path.join(b, "altitude", slug + ".json"), "w", encoding="utf-8") as fh:
            json.dump({d: [{"hour": 12, "levels": [{"alt": 1500, "ws": 8, "wd": 15, "tx": 14, "t": 12},
                                                  {"alt": 2000, "ws": 10, "wd": 20, "tx": 10, "t": 9},
                                                  {"alt": 2500, "ws": 14, "wd": 30, "tx": 6, "t": 6},
                                                  {"alt": 3000, "ws": 17, "wd": 240, "tx": 3, "t": 3}]}]
                       for d in dates}, fh)
    with open(os.path.join(root, "CURRENT"), "w", encoding="utf-8") as fh:
        fh.write(build)
    return b


@pytest.fixture
def root(tmp_path):
    write_export(str(tmp_path))
    return str(tmp_path)


def test_missing_export_raises(tmp_path):
    s = ExportStore(str(tmp_path))
    with pytest.raises(ExportMissing):
        s.maybe_reload()


def test_load_and_lazy_readers(root):
    s = ExportStore(root, now_fn=lambda: NOW)
    assert s.maybe_reload() is True
    assert s.maybe_reload() is False  # unveraendert
    assert len(s.rows) == 2 and s.spots[0]["name"] == "Niederbauen"
    assert s.current_dates() == ["2026-09-17", "2026-09-18"]
    assert s.block("niederbauen-x", "2026-09-17").startswith("BLOCK")
    assert s.block("niederbauen-x", "2026-09-19") is None
    assert "2026-09-17" in s.meteogram("niederbauen-x")
    assert s.altitude("niederbauen-x")["2026-09-18"][0]["hour"] == 12
    assert s.row("niederbauen-x", "2026-09-18")["date"] == "2026-09-18"


def test_pointer_change_triggers_reload(root):
    s = ExportStore(root, now_fn=lambda: NOW)
    s.maybe_reload()
    write_export(root, build="build-20260917-0700", rows=[make_row(spot="Neu", slug="neu-y")])
    os.utime(os.path.join(root, "CURRENT"), (NOW.timestamp() + 100, NOW.timestamp() + 100))
    assert s.maybe_reload() is True
    assert [r["spot"] for r in s.rows] == ["Neu"]


def test_past_dates_are_dropped(root):
    s = ExportStore(root, now_fn=lambda: datetime(2026, 9, 18, 8, 0))
    s.maybe_reload()
    assert s.current_dates() == ["2026-09-18"]
    assert all(r["date"] == "2026-09-18" for r in s.current_rows())


def test_staleness_banner_and_refusal(root):
    lu = datetime(2026, 9, 17, 5, 2)
    s = ExportStore(root, now_fn=lambda: lu + timedelta(hours=STALE_WARN_H + 1))
    s.maybe_reload()
    assert s.is_stale() and not s.is_unusable()
    s2 = ExportStore(root, now_fn=lambda: lu + timedelta(hours=STALE_REFUSE_H + 1))
    s2.maybe_reload()
    assert s2.is_unusable()
    s3 = ExportStore(root, now_fn=lambda: lu + timedelta(hours=3))
    s3.maybe_reload()
    assert not s3.is_stale()
