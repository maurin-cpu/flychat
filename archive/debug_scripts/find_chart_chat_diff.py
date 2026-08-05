"""
Findet alle Region-Stunden, wo Chart und Chat-Klassifizierer signifikant
unterschiedliche Böenwerte zeigen. Misst, wie groß die "structural" Diff
WIRKLICH ist.
"""
import os
import sys
import json
import csv
from pathlib import Path
from datetime import datetime

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

with open(ROOT / "data" / "wetterdaten.json", encoding="utf-8") as f:
    wd = json.load(f)
regions = wd.get("_regions", {})

# Region polygons
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
                }
            except Exception:
                pass

# Spots
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


def get_max_in_range_gust(levels, elev_ref, ceiling):
    """Returns max wind_gusts in [elev_ref, ceiling]."""
    mx = 0
    mx_ws = 0
    for lv in levels:
        alt = lv.get("altitude", 0)
        if elev_ref <= alt <= ceiling:
            g = lv.get("wind_gusts", 0)
            if g > mx:
                mx = g
                mx_ws = lv.get("wind_speed", 0)
    return mx, mx_ws


def interp_gust_at(grid_levels, alt):
    pts = sorted([(l["altitude"], l["wind_gusts"], l.get("wind_speed", 0)) for l in grid_levels])
    if not pts:
        return 0, 0
    if alt <= pts[0][0]:
        return pts[0][1], pts[0][2]
    if alt >= pts[-1][0]:
        return pts[-1][1], pts[-1][2]
    for i in range(len(pts) - 1):
        if pts[i][0] <= alt <= pts[i + 1][0]:
            dh = pts[i + 1][0] - pts[i][0]
            frac = (alt - pts[i][0]) / dh if dh > 0 else 0
            g = pts[i][1] + frac * (pts[i + 1][1] - pts[i][1])
            ws = pts[i][2] + frac * (pts[i + 1][2] - pts[i][2])
            return g, ws
    return pts[-1][1], pts[-1][2]


# Vergleiche an JEDER Druckhöhe innerhalb des Flugbereichs:
# Chart-Wert (Grid-interpoliert) vs Chat-Wert (direkt)
diffs = []  # [(rid, ts, alt, chart_g, chat_g_old, chat_g_new, n_anchors)]
total_levels_compared = 0

for rid, region_data in regions.items():
    meta = region_meta.get(rid)
    if not meta:
        continue
    elev_ref = meta["elevation_ref"]
    polygon = meta["polygon"]
    pressure_data = region_data.get("pressure_level_data", {})
    hourly = region_data.get("hourly_data", {})

    for ts in sorted(hourly.keys()):
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

        wsg = sfc.get("wind_gusts_10m")
        ws10 = sfc.get("wind_speed_10m")
        if wsg is None or ws10 is None:
            continue

        # Display levels
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

        ref_anchor = {
            "elevation_m": elev_ref,
            "gust_kmh": float(wsg),
            "wind_speed_kmh": float(ws10),
            "source": "ref",
        }
        anchors = collect_gust_anchors(polygon, spots, wd, ts, ref_anchor=ref_anchor)
        if not anchors:
            continue

        # Chart-Berechnung
        chart_data = format_altitude_wind_for_charts(
            pressure_level_data={ts: pl},
            hourly_data=hourly,
            elevation_m=elev_ref,
            region_id=rid,
            gust_anchors_by_time={ts: anchors},
            surface_anchor_by_time={ts: ref_anchor},
        )
        if not chart_data["profiles"]:
            continue
        chart_levels = chart_data["profiles"][0]["levels"]

        # Chat-Berechnung ALT (vor unserer OI-Erweiterung)
        chat_old = estimate_altitude_gusts_multi_anchor(
            anchors=anchors,
            pressure_levels_data=display_levels,
            elevation_ref=elev_ref,
            boundary_layer_height=sfc.get("boundary_layer_height"),
            region_id=rid,
        )

        # Chat-Berechnung NEU (mit OI)
        chat_new = apply_oi_gust_correction(
            pressure_levels=chat_old,
            anchors=anchors,
            elevation_ref=elev_ref,
            boundary_layer_height=sfc.get("boundary_layer_height"),
            region_id=rid,
        )

        ceiling = elev_ref + 1000
        for lv in chat_old:
            alt = lv["altitude"]
            if not (elev_ref <= alt <= ceiling):
                continue
            chart_g, _ = interp_gust_at(chart_levels, alt)
            chat_old_g = lv["wind_gusts"]
            chat_new_g = next((l["wind_gusts"] for l in chat_new if l["altitude"] == alt), 0)
            diffs.append((rid, ts, alt, chart_g, chat_old_g, chat_new_g, len(anchors)))
            total_levels_compared += 1


# Statistiken
print(f"Verglichene Druckniveau-Höhen im Flugbereich: {total_levels_compared}")
diffs_old = [(d[3] - d[4]) for d in diffs]  # chart - chat_old
diffs_new = [(d[3] - d[5]) for d in diffs]  # chart - chat_new

if diffs_old:
    import statistics
    print(f"\n=== Chart vs Chat-ALT (multi-anchor only) ===")
    print(f"Mean diff (chart - chat_old): {statistics.mean(diffs_old):+.2f} km/h")
    print(f"Median:                       {statistics.median(diffs_old):+.2f} km/h")
    print(f"StDev:                        {statistics.stdev(diffs_old):.2f} km/h")
    print(f"Min:                          {min(diffs_old):+.2f} km/h")
    print(f"Max:                          {max(diffs_old):+.2f} km/h")
    cnt_big = sum(1 for d in diffs_old if abs(d) > 5)
    print(f"|Diff| > 5 km/h:              {cnt_big} / {len(diffs_old)} ({100*cnt_big/len(diffs_old):.1f}%)")

    print(f"\n=== Chart vs Chat-NEU (multi-anchor + OI) ===")
    print(f"Mean diff (chart - chat_new): {statistics.mean(diffs_new):+.2f} km/h")
    print(f"Median:                       {statistics.median(diffs_new):+.2f} km/h")
    print(f"StDev:                        {statistics.stdev(diffs_new):.2f} km/h")
    print(f"Min:                          {min(diffs_new):+.2f} km/h")
    print(f"Max:                          {max(diffs_new):+.2f} km/h")
    cnt_big2 = sum(1 for d in diffs_new if abs(d) > 5)
    print(f"|Diff| > 5 km/h:              {cnt_big2} / {len(diffs_new)} ({100*cnt_big2/len(diffs_new):.1f}%)")

# Top 10 größte Diffs (chart - chat_old)
print("\n=== Top 15 größte Abweichungen (Chart-Chat_alt) ===")
diffs_with_meta = sorted(diffs, key=lambda d: abs(d[3] - d[4]), reverse=True)
for d in diffs_with_meta[:15]:
    rid, ts, alt, chart, old, new, na = d
    rname = region_meta.get(rid, {}).get("name", rid)
    print(f"{rname:25s} {ts}  alt={int(alt):4}m  chart={chart:6.1f}  chat_old={old:6.1f}  chat_new={new:6.1f}  Δ_old={chart-old:+6.1f}  Δ_new={chart-new:+6.1f}  anchors={na}")
