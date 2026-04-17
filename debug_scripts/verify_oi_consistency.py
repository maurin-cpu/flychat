"""
Verifiziert, dass die neue apply_oi_gust_correction in chat_engine
die gleichen Böenwerte produziert wie das Chart (web.format_altitude_wind_for_charts).

Zwei Tests:
1) Direkter Vergleich für Mittelland Ost / 07.04.2026 / 12:00:
   - Chart-OI-Werte (vom 250m-Grid, interpoliert auf Pressure-Level-Höhen)
   - Klassifizierer-OI-Werte (direkt auf Pressure-Levels)
   Erwartet: praktisch identisch (kleine Diff durch Interpolation OK)

2) Effekt auf ALOFT-GUST-DANGER über alle Regionen × Tage:
   - Vorher: rohe Multi-Anchor (Chat-Klassifizierer alt)
   - Nachher: OI-korrigiert (Chat-Klassifizierer neu, mit ws_val>30 & g_val>40)
"""
import os
import sys
import json
from pathlib import Path

os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config
from gust_calculator import (
    estimate_altitude_gusts_multi_anchor,
    apply_oi_gust_correction,
    collect_gust_anchors,
)
from web import format_altitude_wind_for_charts
from shapely.geometry import shape


# ─── Daten laden ───
with open(ROOT / "data" / "wetterdaten.json", encoding="utf-8") as f:
    wd = json.load(f)

regions = wd.get("_regions", {})
print(f"Geladene Regionen: {len(regions)}")

# Polygon-Loader für die regionen
import csv
region_meta = {}
geojson_path = config.REGIONEN_GEOJSON_PATH
if geojson_path.exists():
    with open(geojson_path, encoding="utf-8") as f:
        gj = json.load(f)
    for feat in gj.get("features", []):
        props = feat.get("properties", {})
        rid = props.get("id")
        if rid and feat.get("geometry"):
            try:
                region_meta[rid] = {
                    "polygon": shape(feat["geometry"]),
                    "elevation_ref": props.get("elevation_ref", 1200),
                    "name": props.get("region", rid),
                    "kritischer_foehn": props.get("kritischer_foehn", "Beide"),
                }
            except Exception:
                pass

# Spots aus CSV
spots = []
csv_path = ROOT / "data" / "fluggebiete.csv"
if csv_path.exists():
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                spots.append({
                    "name": row["name"].strip(),
                    "latitude": float(row["latitude"]),
                    "longitude": float(row["longitude"]),
                    "elevation_m": int(row["elevation_m"]),
                })
            except Exception:
                continue

# ─── Test 1: Mittelland Ost / 07.04.2026 / 12:00 ───
print("\n=== TEST 1: Mittelland Ost / 07.04.2026 / 12:00 ===")
rid = "mittelland_ost"
region_data = regions.get(rid)
meta = region_meta.get(rid)
if region_data and meta:
    elev_ref = meta["elevation_ref"]
    polygon = meta["polygon"]
    pressure_data = region_data.get("pressure_level_data", {})
    hourly = region_data.get("hourly_data", {})

    # Suche timestamp 07.04. 12:00
    target_ts = None
    for ts in pressure_data.keys():
        if ts.startswith("2026-04-07T12"):
            target_ts = ts
            break

    if target_ts:
        pl = pressure_data[target_ts]
        sfc = hourly.get(target_ts, {})

        # Bauen display_levels (wie chat_engine es macht)
        display_levels = []
        for level in config.PRESSURE_LEVELS:
            h = pl.get(f"geopotential_height_{level}hPa")
            ws = pl.get(f"wind_speed_{level}hPa")
            wd_val = pl.get(f"wind_direction_{level}hPa")
            if h is not None and ws is not None:
                display_levels.append({
                    "pressure": level,
                    "altitude": h,
                    "wind_speed": ws,
                    "wind_direction": wd_val if wd_val is not None else 0,
                    "temperature": pl.get(f"temperature_{level}hPa", 0),
                })

        # Anker
        ref_anchor = {
            "elevation_m": elev_ref,
            "gust_kmh": float(sfc.get("wind_gusts_10m", 0)),
            "wind_speed_kmh": float(sfc.get("wind_speed_10m", 0)),
            "source": f"Ref-{meta['name']}",
        }
        anchors = collect_gust_anchors(polygon, spots, wd, target_ts, ref_anchor=ref_anchor)
        print(f"Anker ({len(anchors)}):")
        for a in anchors:
            print(f"  {a['source']}: elev={a['elevation_m']}m, gust={a['gust_kmh']:.0f}, ws={a['wind_speed_kmh']:.0f}")

        # === Methode A: Chart (web.format_altitude_wind_for_charts mit OI) ===
        gust_anchors_by_time = {target_ts: anchors}
        surface_anchor_by_time = {target_ts: ref_anchor}
        chart_data = format_altitude_wind_for_charts(
            pressure_level_data={target_ts: pl},
            hourly_data=hourly,
            elevation_m=elev_ref,
            region_id=rid,
            gust_anchors_by_time=gust_anchors_by_time,
            surface_anchor_by_time=surface_anchor_by_time,
        )
        chart_levels = chart_data["profiles"][0]["levels"] if chart_data["profiles"] else []

        # === Methode B: Chat-Klassifizierer (estimate_altitude_gusts_multi_anchor + apply_oi_gust_correction) ===
        chat_levels = estimate_altitude_gusts_multi_anchor(
            anchors=anchors,
            pressure_levels_data=display_levels,
            elevation_ref=elev_ref,
            boundary_layer_height=sfc.get("boundary_layer_height"),
            region_id=rid,
        )
        chat_levels_oi = apply_oi_gust_correction(
            pressure_levels=chat_levels,
            anchors=anchors,
            elevation_ref=elev_ref,
            boundary_layer_height=sfc.get("boundary_layer_height"),
            region_id=rid,
        )

        # === Methode C: Chat-Klassifizierer ALT (ohne OI) ===
        chat_levels_old = estimate_altitude_gusts_multi_anchor(
            anchors=anchors,
            pressure_levels_data=display_levels,
            elevation_ref=elev_ref,
            boundary_layer_height=sfc.get("boundary_layer_height"),
            region_id=rid,
        )

        # Vergleich
        print(f"\n{'Höhe':>6} | {'WS':>6} | {'Chart-OI':>10} | {'Chat-NEU':>10} | {'Chat-ALT':>10} | {'Diff NEU↔Chart':>14}")
        print("-" * 80)

        # Chart hat 0-4000m grid; chat hat pressure levels.
        # Wir interpolieren chart-grid auf chat-altitudes für Vergleich.
        def interp_at(grid_levels, alt):
            pts = sorted([(l["altitude"], l["wind_gusts"]) for l in grid_levels])
            if not pts:
                return 0
            if alt <= pts[0][0]:
                return pts[0][1]
            if alt >= pts[-1][0]:
                return pts[-1][1]
            for i in range(len(pts) - 1):
                if pts[i][0] <= alt <= pts[i + 1][0]:
                    dh = pts[i + 1][0] - pts[i][0]
                    frac = (alt - pts[i][0]) / dh if dh > 0 else 0
                    return pts[i][1] + frac * (pts[i + 1][1] - pts[i][1])
            return pts[-1][1]

        for lv in sorted(chat_levels_oi, key=lambda l: l["altitude"]):
            alt = lv["altitude"]
            ws = lv.get("wind_speed", 0)
            chat_new = lv["wind_gusts"]
            chat_old = next((l["wind_gusts"] for l in chat_levels_old if l["altitude"] == alt), 0)
            chart_g = interp_at(chart_levels, alt)
            diff = chat_new - chart_g
            print(f"{int(alt):>6} | {ws:>6.1f} | {chart_g:>10.1f} | {chat_new:>10.1f} | {chat_old:>10.1f} | {diff:>+14.1f}")

        # Konsistenz-Check
        max_diff = 0
        for lv in chat_levels_oi:
            chart_g = interp_at(chart_levels, lv["altitude"])
            max_diff = max(max_diff, abs(lv["wind_gusts"] - chart_g))
        print(f"\nMax |Chat-NEU − Chart-OI|: {max_diff:.2f} km/h")
        if max_diff < 2.0:
            print("OK Konsistenz: Chat-Klassifizierer und Chart sind jetzt im Einklang.")
        else:
            print("WARNUNG: Diff > 2 km/h — bitte prüfen.")
    else:
        print("Kein Timestamp 2026-04-07T12 gefunden.")
else:
    print("mittelland_ost nicht in Daten / Meta.")

# ─── Test 2: Effekt über alle Regionen × Tage ───
print("\n=== TEST 2: Auswirkung auf ALOFT-GUST-DANGER (alle Regionen) ===")

old_dangers = 0
new_dangers = 0
total_hours = 0
flipped = []

for rid, region_data in regions.items():
    meta = region_meta.get(rid)
    if not meta:
        continue
    elev_ref = meta["elevation_ref"]
    polygon = meta["polygon"]
    pressure_data = region_data.get("pressure_level_data", {})
    hourly = region_data.get("hourly_data", {})

    for ts in sorted(hourly.keys()):
        from datetime import datetime
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            continue
        if not (config.FLIGHT_HOURS_START <= dt.hour < config.FLIGHT_HOURS_END):
            continue

        sfc = hourly[ts]
        pl = pressure_data.get(ts, {})
        if not pl:
            continue

        # Display-Levels
        display_levels = []
        for level in config.PRESSURE_LEVELS:
            h = pl.get(f"geopotential_height_{level}hPa")
            ws = pl.get(f"wind_speed_{level}hPa")
            if h is not None and ws is not None:
                display_levels.append({
                    "pressure": level,
                    "altitude": h,
                    "wind_speed": ws,
                    "wind_direction": pl.get(f"wind_direction_{level}hPa", 0),
                    "temperature": pl.get(f"temperature_{level}hPa", 0),
                })

        if not display_levels:
            continue

        # Effective ceiling (vereinfacht: elev + 1000)
        eff_ceiling = elev_ref + 1000

        # Anker
        wsg = sfc.get("wind_gusts_10m")
        ws10 = sfc.get("wind_speed_10m")
        if wsg is None or ws10 is None:
            continue
        ref_anchor = {
            "elevation_m": elev_ref,
            "gust_kmh": float(wsg),
            "wind_speed_kmh": float(ws10),
            "source": "ref",
        }
        anchors = collect_gust_anchors(polygon, spots, wd, ts, ref_anchor=ref_anchor)
        if not anchors:
            continue

        # ALT (Multi-Anchor only)
        old_levels = estimate_altitude_gusts_multi_anchor(
            anchors=anchors,
            pressure_levels_data=display_levels,
            elevation_ref=elev_ref,
            boundary_layer_height=sfc.get("boundary_layer_height"),
            region_id=rid,
        )

        # NEU (+ OI)
        new_levels = apply_oi_gust_correction(
            pressure_levels=old_levels,
            anchors=anchors,
            elevation_ref=elev_ref,
            boundary_layer_height=sfc.get("boundary_layer_height"),
            region_id=rid,
        )

        # ALOFT-GUST-DANGER prüfen (g_val > 40 AND ws_val > 30, in_range)
        def has_danger(levels):
            for lv in levels:
                alt = lv["altitude"]
                if not (elev_ref <= alt <= eff_ceiling):
                    continue
                ws = lv.get("wind_speed", 0)
                g = lv.get("wind_gusts", 0)
                if g > 40 and ws > 30:
                    return True
            return False

        old_d = has_danger(old_levels)
        new_d = has_danger(new_levels)
        if old_d:
            old_dangers += 1
        if new_d:
            new_dangers += 1
        if old_d and not new_d:
            flipped.append((rid, ts))
        total_hours += 1

print(f"Geprüfte Region-Stunden: {total_hours}")
print(f"ALOFT-GUST-DANGER ALT (ohne OI): {old_dangers}")
print(f"ALOFT-GUST-DANGER NEU (mit OI):  {new_dangers}")
print(f"Stunden, die NEU NICHT mehr DANGER haben: {len(flipped)}")
if flipped:
    print("\nBeispiele (erste 20):")
    for rid, ts in flipped[:20]:
        print(f"  {rid:25s} {ts}")
