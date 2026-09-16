"""MCP-Tools ueber MCPServer.call_tool gegen einen Mini-Export (offline)."""
from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from mcp_server import formatting as fmt
from mcp_server.server import build_server
from mcp_server.store import ExportStore
from tests.test_mcp_store import make_row, write_export

NOW = datetime(2026, 9, 17, 9, 0)


def _text(res) -> str:
    return "".join(getattr(c, "text", "") for c in res.content)


@pytest.fixture
def srv(tmp_path):
    rows = [
        make_row(date="2026-09-17"),
        make_row(date="2026-09-18", longest_clean_h=1, wind_ok_h=0, clean_windows="-"),
        make_row(spot="Fiesch -Kuehboden (Heimat- Galfera)", slug="fiesch-a", fluggebiet="Galfera", region="Oberwallis / Goms",
                 region_id="oberwallis_goms", lat=46.40, lon=8.10, elev=2163, date="2026-09-17", gust_danger_h=2, gust_max=44.0),
        make_row(spot="Fiescheralp", slug="fiesch-b", fluggebiet="Galfera", region="Oberwallis / Goms",
                 region_id="oberwallis_goms", lat=46.41, lon=8.11, elev=2200, date="2026-09-17", foehn_level="danger", foehn_dp=9.1),
    ]
    write_export(str(tmp_path), rows=rows)
    server = build_server(str(tmp_path))
    # Store des Servers auf feste Zeit setzen (Closure ueber register → via Attribut nicht erreichbar,
    # darum ueber den in build_server erzeugten Store: wir bauen neu mit now_fn)
    return server


def call(server, name, **args):
    return _text(asyncio.run(server.call_tool(name, args)))


def test_tools_registered(srv):
    names = {t.name for t in asyncio.run(srv.list_tools())}
    assert {"data_status", "overview", "day_table", "search_spots", "spot_series", "spot_detail",
            "spot_meteogram", "spot_altitude_wind", "foehn", "find_spots_near", "spot_info", "list_regions"} <= names


def test_every_answer_has_footer(srv):
    for name, args in (("data_status", {}), ("list_regions", {}), ("overview", {}),
                       ("day_table", {"date": "2026-09-17"}), ("search_spots", {}),
                       ("spot_series", {"spots": "Niederbauen", "date": "2026-09-17"}),
                       ("spot_detail", {"spot": "Niederbauen", "date": "2026-09-17"}),
                       ("spot_meteogram", {"spot": "Niederbauen", "date": "2026-09-17"}),
                       ("spot_altitude_wind", {"spot": "Niederbauen", "date": "2026-09-17", "hours": "12"}),
                       ("foehn", {}), ("spot_info", {"spot": "Niederbauen"})):
        out = call(srv, name, **args)
        assert "Stand Prognose" in out and "Open-Meteo" in out, name


def test_search_reports_checked_and_exclusions(srv):
    out = call(srv, "search_spots")
    assert "Geprüft: 4 Spot-Tage" in out
    assert "Ausgeschlossen: 3" in out
    assert "no_window 1 [Windrichtung passt nie 1" in out
    assert "gusts 1" in out and "foehn 1" in out
    assert "Übrig: 1" in out
    assert "Niederbauen" in out and "Fiescheralp" not in out.split("Legende")[1]


def test_search_scope_is_not_an_exclusion(srv):
    out = call(srv, "search_spots", dates="2026-09-17")
    assert "Im Bereich: 3 von 4 Spot-Tagen" in out
    assert "date " not in out.split("Geprüft")[1].split("Übrig")[0]


def test_search_loosen_filters(srv):
    out = call(srv, "search_spots", dates="2026-09-17", allow_gust_danger=True, allow_foehn_danger=True)
    assert "Übrig: 3" in out
    assert "!! GUST-DANGER" in out


def test_day_table_lists_all_spots_unfiltered(srv):
    out = call(srv, "day_table", date="2026-09-17")
    body = out.split("Bew. tief%")[1]
    assert body.count("\n") >= 3 and "Fiescheralp" in body and "Niederbauen" in body
    assert "3 Spots" in out
    out2 = call(srv, "day_table", date="2026-09-17", region="Oberwallis")
    assert "Niederbauen" not in out2.split("Bew. tief%")[1] and "2 Spots" in out2
    assert "nicht im Export" in call(srv, "day_table", date="2026-09-30")


def test_ambiguous_spot_returns_candidates(srv):
    out = call(srv, "spot_detail", spot="Fiesch", date="2026-09-17")
    assert "mehrdeutig" in out and "Fiescheralp" in out and "Kuehboden" in out
    assert "nicht gefunden" in call(srv, "spot_info", spot="Gibtsnicht")


def test_spot_series_region_and_profile(srv):
    out = call(srv, "spot_series", spots="region:Zentralschweizer Alpen", date="2026-09-17")
    assert "### Niederbauen" in out
    assert "Böen       8   9  10  12  15  18  22  24  24  20  16  12" in out
    assert "+3000m" in out and "09 Uhr" in out and "12 Uhr" in out
    assert "700hPa" in out


def test_spot_altitude_wind_table(srv):
    out = call(srv, "spot_altitude_wind", spot="Niederbauen", date="2026-09-17", hours="12", step_m=500)
    assert "1500 (-73)" in out or "1500 (" in out
    assert "17 SW +3 3°" in out


def test_overview_counts(srv):
    out = call(srv, "overview")
    assert "Zentralschweizer Alpen | 1/1 | 0/1" in out
    assert "GESAMT | 1/3 | 0/1" in out


def test_find_spots_near_radius(srv):
    out = call(srv, "find_spots_near", lat=46.93, lon=8.55, radius_km=5)
    assert "1 Spots" in out and "Niederbauen" in out and "Luftlinie" in out


def test_day_line_trend_and_units():
    r = make_row()
    line = fmt.day_line(r)
    assert "2→10 ↗" in line and "24 ↗" in line and "10→22 ↗" in line
    assert "8→26 W" in line  # Hoehe Start→+3000m 12 Uhr
    assert "2400m" in line
    r2 = make_row(min_base_m=None, cloud_below_to_h=3)
    assert "| - |" in fmt.day_line(r2) and "BASIS<START 3h" in fmt.day_line(r2)
