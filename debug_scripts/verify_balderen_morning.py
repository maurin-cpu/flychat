"""
Verifiziert: Mittelland Ost am 07.04.2026 morgens (10/11/12) bleibt OK
nach Einführung von apply_oi_gust_correction.
Zusätzlich: zählt Hours die NEU als DANGER triggern (Sicherheits-Check).
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
from shapely.geometry import shape

with open(ROOT / "data" / "wetterdaten.json", encoding="utf-8") as f:
    wd = json.load(f)
regions = wd.get("_regions", {})

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


def has_danger(levels, elev_ref, ceiling):
    """g_val > 40 AND ws_val > 30, in_range."""
    for lv in levels:
        alt = lv.get("altitude", 0)
        if not (elev_ref <= alt <= ceiling):
            continue
        ws = lv.get("wind_speed", 0)
        g = lv.get("wind_gusts", 0)
        if g > 40 and ws > 30:
            return True
    return False


# === FOKUS: Mittelland Ost / 07.04.2026 ===
print("=== Mittelland Ost / 07.04.2026 ===")
rid = "mittelland_ost"
region_data = regions.get(rid)
meta = region_meta.get(rid)
if region_data and meta:
    elev_ref = meta["elevation_ref"]
    polygon = meta["polygon"]
    pressure_data = region_data.get("pressure_level_data", {})
    hourly = region_data.get("hourly_data", {})

    for ts in sorted(hourly.keys()):
        if not ts.startswith("2026-04-07"):
            continue
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

        old_levels = estimate_altitude_gusts_multi_anchor(
            anchors=anchors, pressure_levels_data=display_levels,
            elevation_ref=elev_ref, boundary_layer_height=sfc.get("boundary_layer_height"),
            region_id=rid,
        )
        new_levels = apply_oi_gust_correction(
            pressure_levels=old_levels, anchors=anchors,
            elevation_ref=elev_ref, boundary_layer_height=sfc.get("boundary_layer_height"),
            region_id=rid,
        )
        ceiling = elev_ref + 1000
        old_d = has_danger(old_levels, elev_ref, ceiling)
        new_d = has_danger(new_levels, elev_ref, ceiling)

        # Print max in range
        def max_in_range(levels):
            mx_g, mx_ws = 0, 0
            for lv in levels:
                if elev_ref <= lv["altitude"] <= ceiling:
                    if lv["wind_gusts"] > mx_g:
                        mx_g = lv["wind_gusts"]
                        mx_ws = lv["wind_speed"]
            return mx_g, mx_ws

        ogm, ows = max_in_range(old_levels)
        ngm, nws = max_in_range(new_levels)
        marker_old = "DANGER" if old_d else "ok    "
        marker_new = "DANGER" if new_d else "ok    "
        print(f"  {ts[11:16]} sfc({ws10:.0f}/{wsg:.0f}) | "
              f"OLD: {ows:.0f}/{ogm:.0f} {marker_old} | "
              f"NEW: {nws:.0f}/{ngm:.0f} {marker_new}")

# === Globaler Sicherheits-Check: triggert OI neue DANGER? ===
print("\n=== Globale Auswirkung (OI-Effekt auf DANGER-Klassifizierung) ===")
flipped_to_danger = []  # OLD ok → NEW danger
flipped_from_danger = []  # OLD danger → NEW ok
total = 0
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

        display_levels = []
        for level in config.PRESSURE_LEVELS:
            h = pl.get(f"geopotential_height_{level}hPa")
            ws = pl.get(f"wind_speed_{level}hPa")
            if h is not None and ws is not None:
                display_levels.append({
                    "pressure": level, "altitude": h, "wind_speed": ws,
                    "wind_direction": pl.get(f"wind_direction_{level}hPa", 0),
                    "temperature": pl.get(f"temperature_{level}hPa", 0),
                })
        if not display_levels:
            continue

        ref_anchor = {
            "elevation_m": elev_ref, "gust_kmh": float(wsg),
            "wind_speed_kmh": float(ws10), "source": "ref",
        }
        anchors = collect_gust_anchors(polygon, spots, wd, ts, ref_anchor=ref_anchor)
        if not anchors:
            continue

        old_levels = estimate_altitude_gusts_multi_anchor(
            anchors=anchors, pressure_levels_data=display_levels,
            elevation_ref=elev_ref, boundary_layer_height=sfc.get("boundary_layer_height"),
            region_id=rid,
        )
        new_levels = apply_oi_gust_correction(
            pressure_levels=old_levels, anchors=anchors,
            elevation_ref=elev_ref, boundary_layer_height=sfc.get("boundary_layer_height"),
            region_id=rid,
        )
        ceiling = elev_ref + 1000
        old_d = has_danger(old_levels, elev_ref, ceiling)
        new_d = has_danger(new_levels, elev_ref, ceiling)

        if (not old_d) and new_d:
            flipped_to_danger.append((rid, ts))
        if old_d and (not new_d):
            flipped_from_danger.append((rid, ts))
        total += 1

print(f"Total Region-Stunden: {total}")
print(f"OK → DANGER (OI macht strenger): {len(flipped_to_danger)}")
print(f"DANGER → OK (OI macht milder):    {len(flipped_from_danger)}")
if flipped_to_danger:
    print("\nNeue DANGER-Falle (erste 10):")
    for rid, ts in flipped_to_danger[:10]:
        rname = region_meta.get(rid, {}).get("name", rid)
        print(f"  {rname:25s} {ts}")
