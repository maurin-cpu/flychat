"""Sieb-Logik des MCP-Servers (mcp_server/screening.py) — offline, Inline-Zeilen."""
from __future__ import annotations

import pytest

from mcp_server.screening import (
    EXCLUSION_REASONS, apply_filters, default_filters, haversine_km, overview_counts, rank, reasons_for_row,
    windows_from_hours,
)

THRESH = {"CLEAN_WINDOW_MIN_HOURS": 2}


def row(**kw) -> dict:
    base = dict(
        spot="A", slug="a", region="Reg", region_id="reg", date="2026-09-17", lat=46.9, lon=8.2, elev=1500,
        wind_ok_h=8, wind_wrong_h=4, clean_h=6, longest_clean_h=4, hard_warn_h=0,
        gust_max=22.0, gust_danger_h=0, aloft_gust_danger_h=0, aloft_danger_h=0,
        thunder_win_h=0, rain_win_h=0, foehn_level="none", cloud_below_to_h=0,
        thermal_h=5, prod_h=3, peak_climb=1.5, region_thunder_pct=None,
    )
    base.update(kw)
    return base


def test_default_row_passes():
    assert reasons_for_row(row(), default_filters(THRESH)) == []


def test_multiple_reasons_are_all_listed_but_row_counts_once():
    rows = [row(longest_clean_h=1, wind_ok_h=0, gust_danger_h=2, thunder_win_h=1), row()]
    kept, s = apply_filters(rows, default_filters(THRESH))
    assert s["checked"] == 2 and s["excluded"] == 1 and s["kept"] == 1
    assert s["by_reason"]["no_window"] == 1
    assert s["by_reason"]["gusts"] == 1
    assert s["by_reason"]["thunderstorm"] == 1
    assert len(kept) == 1


def test_no_window_split_wind_sector_vs_hard_warnings():
    rows = [row(longest_clean_h=0, wind_ok_h=0), row(longest_clean_h=1, wind_ok_h=3, hard_warn_h=6)]
    _, s = apply_filters(rows, default_filters(THRESH))
    assert s["no_window_split"] == {"wind_sector": 1, "hard_warnings": 1}


def test_cloud_below_takeoff_is_not_a_default_exclusion():
    # 17.09.2026: eine Stratus-Stunde am Morgen strich sonst 286 von 494 Spots
    assert reasons_for_row(row(cloud_below_to_h=2), default_filters(THRESH)) == []
    f = default_filters(THRESH)
    f["allow_cloud_below_takeoff"] = False
    assert reasons_for_row(row(cloud_below_to_h=2), f) == ["cloud_below_takeoff"]


def test_threshold_from_config_snapshot():
    f = default_filters({"CLEAN_WINDOW_MIN_HOURS": 3})
    assert f["min_clean_h"] == 3
    assert reasons_for_row(row(longest_clean_h=2), f) == ["no_window"]


def test_pilot_filters_optional():
    f = default_filters(THRESH)
    f.update(max_gust=20, min_thermal_h=6, min_peak_climb=2.0)
    assert set(reasons_for_row(row(), f)) == {"max_gust", "min_thermal"}


def test_region_date_near_filters():
    f = default_filters(THRESH)
    f.update(regions=["other"], dates=["2026-09-18"], near={"lat": 47.4, "lon": 9.0, "km": 10})
    assert set(reasons_for_row(row(), f)) == {"region", "date", "near"}
    f["regions"] = ["Reg"]  # Name statt id akzeptiert
    assert "region" not in reasons_for_row(row(), f)


def test_rank_window_then_hard_warnings_then_thermal():
    a = row(spot="a", longest_clean_h=4, hard_warn_h=2)
    b = row(spot="b", longest_clean_h=4, hard_warn_h=0, prod_h=1)
    c = row(spot="c", longest_clean_h=6, hard_warn_h=5, prod_h=2)
    assert [r["spot"] for r in rank([a, b, c])] == ["c", "b", "a"]
    assert [r["spot"] for r in rank([a, b, c], "thermal")] == ["a", "c", "b"]
    assert rank([a, b, c], "unbekannt")[0]["spot"] == "c"


def test_overview_counts_pass_total():
    rows = [row(), row(spot="B", longest_clean_h=1), row(spot="C", region="X", region_id="x", region_thunder_pct=45)]
    cnt = overview_counts(rows, default_filters(THRESH))
    assert cnt[("Reg", "2026-09-17")] == {"pass": 1, "total": 2, "thunder_pct": None}
    assert cnt[("X", "2026-09-17")]["thunder_pct"] == 45


def test_all_reason_keys_have_descriptions():
    for k in ("no_window", "gusts", "aloft_wind", "thunderstorm", "rain", "foehn", "cloud_below_takeoff",
              "max_gust", "min_thermal", "region", "date", "near"):
        assert k in EXCLUSION_REASONS


@pytest.mark.parametrize("hours,expected", [
    ([], "-"),
    (["10:00", "11:00", "12:00"], "10-13"),
    (["10:00", "11:00", "13:00", "14:00", "15:00"], "10-12,13-16"),
    (["06:00"], "06-07"),
])
def test_windows_from_hours(hours, expected):
    assert windows_from_hours(hours) == expected


def test_haversine_luzern_engelberg():
    assert 25 < haversine_km(47.05, 8.31, 46.82, 8.40) < 30
    assert haversine_km(None, 1, 2, 3) == float("inf")
