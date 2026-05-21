"""Manueller Snapshot der aktuellen Wettervorhersage + Thermik + Ratings.

Friert den Forecast-Stand fuer den AKTUELLEN TAG ein (Default), bevor die
naechste Aktualisierung ihn ueberschreibt. Forecast-Tage in der Zukunft werden
NICHT gespeichert — das, was wir validieren wollen, ist was ein Pilot am
Flug-Morgen vor sich hatte, nicht ein D+3-Forecast der nochmal revidiert wird.

Speichert in data/weather_archive/YYYY-MM-DD.json:
  * Tages-Aggregaten (t2m, gust, precip, climb, max_height, ...)
  * Flug-Fenster 08-20 stuendlich (Wind, Wolken, Strahlung, climb_rate, ...)
  * Rating-Snapshot aus spot_analyses.json / region_analyses.json
  * Decisions_applied + no_go_reasons fuer Forecast-Vergleich

**Verhalten**: ueberschreibt IMMER. Damit ist der Snapshot stets auf dem
neuesten Stand des letzten Wetter-Refreshs + LLM-Analysen.

Usage:
    python scripts/snapshot_weather.py                # nur heute (Default)
    python scripts/snapshot_weather.py 2026-05-18     # spezifischer Tag (Backfill)
    python scripts/snapshot_weather.py --all          # alle verfuegbaren Tage (Debug)
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
from thermik_calculator import compute_daily_thermals

ARCHIVE_DIR = ROOT / "data" / "weather_archive"
WETTERDATEN = ROOT / "data" / "wetterdaten.json"
SPOT_ANALYSES = ROOT / "data" / "spot_analyses.json"
REGION_ANALYSES = ROOT / "data" / "region_analyses.json"
FLUGGEBIETE = ROOT / "data" / "fluggebiete_complete.csv"

FLIGHT_HOUR_START = 8
FLIGHT_HOUR_END = 20  # inklusiv

HOURLY_KEEP_FIELDS = [
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "wind_gusts_10m_ch1",
    "wind_gusts_10m_ch2",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "cloud_base",
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
    "precipitation",
    "precipitation_probability",
    "cape",
    "convective_inhibition",
    "lifted_index",
    "boundary_layer_height",
    "boundary_layer_height_gfs",
    "soil_moisture_0_to_1cm",
    "soil_temperature_0cm",
    "updraft",
    "vapour_pressure_deficit",
    "snow_depth",
    "weather_code",
]

THERMAL_KEEP_FIELDS = [
    "climb_rate",
    "max_height",
    "lcl",
    "rating",
    "thermal_quality",
    "limiting_factor",
    "data_warnings",
]


def load_spot_metadata() -> Dict[str, Dict[str, Any]]:
    meta: Dict[str, Dict[str, Any]] = {}
    if not FLUGGEBIETE.exists():
        return meta
    with FLUGGEBIETE.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = (row.get("site_name") or "").strip()
            if not name:
                continue

            def _f(key):
                v = row.get(key)
                if v is None or v == "":
                    return None
                try:
                    return float(v)
                except ValueError:
                    return None

            meta[name] = {
                "slope_azimuth": _f("slope_azimuth"),
                "slope_angle": _f("slope_angle"),
                "analyse_region": (row.get("analyse_region") or "").strip() or None,
                "windrichtung": (row.get("windrichtung") or "").strip() or None,
                "terrain_type": (row.get("terrain_type") or "").strip() or None,
                "ideal_wind_max_kmh": _f("ideal_wind_max_kmh"),
                "kritischer_foehn": (row.get("kritischer_foehn") or "").strip() or None,
            }
    return meta


def _mx(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return max(xs) if xs else None


def _mn(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return min(xs) if xs else None


def _avg(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(sum(xs) / len(xs), 2) if xs else None


def _sum(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(sum(xs), 2) if xs else None


def _vals(hourly: Dict[str, Dict], keys, field):
    return [hourly[k].get(field) for k in keys if k in hourly]


def _t_vals(thermals: Dict[str, Dict], keys, field):
    out = []
    for k in keys:
        t = thermals.get(k) or {}
        v = t.get(field)
        if v is not None:
            out.append(v)
    return out


def aggregate_daily(hourly_day: Dict[str, Dict], thermals_day: Dict[str, Dict]) -> Dict[str, Any]:
    hours = sorted(hourly_day.keys())
    if not hours:
        return {}
    flight = [h for h in hours if FLIGHT_HOUR_START <= int(h[11:13]) <= FLIGHT_HOUR_END]

    out: Dict[str, Any] = {
        "t2m_max": _mx(_vals(hourly_day, hours, "temperature_2m")),
        "t2m_min": _mn(_vals(hourly_day, hours, "temperature_2m")),
        "wind_gust_max_kmh": _mx(_vals(hourly_day, flight, "wind_gusts_10m")),
        "wind_speed_max_kmh": _mx(_vals(hourly_day, flight, "wind_speed_10m")),
        "precip_sum_mm": _sum(_vals(hourly_day, hours, "precipitation")),
        "shortwave_rad_max": _mx(_vals(hourly_day, flight, "shortwave_radiation")),
        "cloud_low_mean_pct": _avg(_vals(hourly_day, flight, "cloud_cover_low")),
        "cloud_mid_mean_pct": _avg(_vals(hourly_day, flight, "cloud_cover_mid")),
        "cloud_high_mean_pct": _avg(_vals(hourly_day, flight, "cloud_cover_high")),
        "soil_moisture_mean": _avg(_vals(hourly_day, hours, "soil_moisture_0_to_1cm")),
        "lifted_index_min": _mn(_vals(hourly_day, flight, "lifted_index")),
        "cape_max": _mx(_vals(hourly_day, flight, "cape")),
        "cin_min": _mn(_vals(hourly_day, flight, "convective_inhibition")),
        "blh_max_m": _mx(_vals(hourly_day, flight, "boundary_layer_height_gfs")),
        "climb_rate_max_ms": _mx(_t_vals(thermals_day, flight, "climb_rate")),
        "climb_rate_mean_flight_ms": _avg(_t_vals(thermals_day, flight, "climb_rate")),
        "max_thermal_height_max_m": _mx(_t_vals(thermals_day, flight, "max_height")),
        "lcl_max_m": _mx(_t_vals(thermals_day, flight, "lcl")),
        "productive_thermal_h": sum(
            1
            for h in flight
            if (thermals_day.get(h) or {}).get("climb_rate") is not None
            and thermals_day[h]["climb_rate"] >= 0.7
        ),
    }

    # Dominante Windrichtung (geschwindigkeits-gewichtetes Vektor-Mittel, Flugstunden)
    u = v = 0.0
    weight = 0.0
    for h in flight:
        ws = hourly_day[h].get("wind_speed_10m")
        wd = hourly_day[h].get("wind_direction_10m")
        if isinstance(ws, (int, float)) and isinstance(wd, (int, float)) and ws > 0:
            rad = math.radians(wd)
            u -= ws * math.sin(rad)
            v -= ws * math.cos(rad)
            weight += ws
    if weight > 0:
        dom = (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0
        out["wind_dir_dominant_deg"] = round(dom)

    return out


def slice_hourly_flight(hourly_day: Dict[str, Dict], thermals_day: Dict[str, Dict]) -> Dict[str, Dict]:
    out: Dict[str, Dict] = {}
    for ts in sorted(hourly_day.keys()):
        hh = int(ts[11:13])
        if not (FLIGHT_HOUR_START <= hh <= FLIGHT_HOUR_END):
            continue
        hkey = ts[11:16]
        row: Dict[str, Any] = {}
        src = hourly_day[ts]
        for k in HOURLY_KEEP_FIELDS:
            v = src.get(k)
            if v is not None:
                row[k] = v
        therm = thermals_day.get(ts) or {}
        for k in THERMAL_KEEP_FIELDS:
            v = therm.get(k)
            if v is not None and v != [] and v != {}:
                row[k] = v
        out[hkey] = row
    return out


def compute_thermals_for_spot(spot_name: str, spot_data: Dict, spot_meta: Dict) -> Dict[str, Dict]:
    """Run compute_daily_thermals ueber das ganze Fenster (mehrtaegig).

    State (previous_max_height, cumulative_buoyancy, peak_H, peak_shortwave) wird
    pro Kalendertag im Calculator selbst zurueckgesetzt. Wir muessen das gesamte
    Hourly-Fenster auf einmal uebergeben, damit die Reihenfolge stimmt.
    """
    hourly_all = spot_data.get("hourly_data") or {}
    pl_all = spot_data.get("pressure_level_data") or {}
    elevation = spot_data.get("elevation_m", 850)
    sm = spot_meta.get(spot_name, {})

    try:
        return compute_daily_thermals(
            hourly_all,
            pl_all,
            elevation,
            config.PRESSURE_LEVELS,
            slope_azimuth=sm.get("slope_azimuth"),
            slope_angle=sm.get("slope_angle"),
            region_id=sm.get("analyse_region"),
        )
    except Exception as exc:  # noqa: BLE001
        return {"_error": str(exc)}


def extract_analysis(spot_ana_day: Optional[Dict]) -> Optional[Dict]:
    if not spot_ana_day:
        return None
    safety = spot_ana_day.get("safety") or {}
    streckenflug = spot_ana_day.get("streckenflug") or {}
    return {
        "safety_status": safety.get("safety_status"),
        "rating": spot_ana_day.get("rating"),
        "status": spot_ana_day.get("status"),
        "fly_status": spot_ana_day.get("fly_status"),
        "is_conditional": spot_ana_day.get("is_conditional"),
        "experience_rating": spot_ana_day.get("experience_rating"),
        "streckenflug_rating": streckenflug.get("rating"),
        "streckenflug_tier": streckenflug.get("tier"),
        "streckenflug_limiting_factor": streckenflug.get("limiting_factor"),
        "no_go_reasons": safety.get("no_go_reasons", []),
        "caution_notes": safety.get("caution_notes", []),
        "primary_no_go": safety.get("primary_no_go"),
        "primary_caution": safety.get("primary_caution"),
        "wind_summary": safety.get("wind_summary"),
        "foehn_risk": safety.get("foehn_risk"),
        "tags": spot_ana_day.get("tags", []),
        "decisions_applied": spot_ana_day.get("_decisions_applied", []),
        "best_window": spot_ana_day.get("best_window"),
        "start_window": spot_ana_day.get("start_window"),
    }


def extract_region_analysis(region_day: Dict) -> Dict:
    safety = region_day.get("safety") or {}
    return {
        "safety_status": safety.get("safety_status"),
        "rating": region_day.get("rating"),
        "status": region_day.get("status"),
        "experience_rating": region_day.get("experience_rating"),
        "fly_status": region_day.get("fly_status"),
        "no_go_reasons": safety.get("no_go_reasons", []),
        "caution_notes": safety.get("caution_notes", []),
        "primary_no_go": safety.get("primary_no_go"),
        "primary_caution": safety.get("primary_caution"),
        "wind_summary": safety.get("wind_summary"),
        "foehn_risk": safety.get("foehn_risk"),
        "tags": region_day.get("tags", []),
        "decisions_applied": region_day.get("_decisions_applied", []),
    }


def build_snapshots(target_date: Optional[str] = None, all_days: bool = False) -> Dict[str, Dict]:
    """Baut Snapshots.

    Default (target_date=None, all_days=False): nur HEUTE.
    target_date='YYYY-MM-DD': nur dieser Tag.
    all_days=True: alle Tage im wetterdaten.json-Fenster (Debug/Backfill).
    """
    print(f"Lese {WETTERDATEN.relative_to(ROOT)}...", flush=True)
    wetterdaten = json.loads(WETTERDATEN.read_text(encoding="utf-8"))
    spot_ana = json.loads(SPOT_ANALYSES.read_text(encoding="utf-8")) if SPOT_ANALYSES.exists() else {}
    region_ana = json.loads(REGION_ANALYSES.read_text(encoding="utf-8")) if REGION_ANALYSES.exists() else {}
    spot_meta = load_spot_metadata()

    meta = wetterdaten.get("_meta", {}) or {}
    wetter_last_updated = meta.get("last_updated", "unknown")
    spots = [k for k in wetterdaten if k != "_meta"]

    available_days: set = set()
    for s in spots:
        hd = wetterdaten[s].get("hourly_data") or {}
        for ts in hd:
            available_days.add(ts[:10])
    available_days = sorted(available_days)
    print(f"Verfuegbare Forecast-Tage: {', '.join(available_days)}", flush=True)

    today_str = datetime.now().date().isoformat()
    if target_date:
        if target_date not in available_days:
            print(f"  Tag {target_date} nicht im Forecast verfuegbar.", flush=True)
            return {}
        target_days = [target_date]
    elif all_days:
        target_days = list(available_days)
    else:
        # Default: nur heute. Wenn heute (z.B. nach Mitternacht) nicht im
        # Forecast-Fenster ist, fallback auf den fruehesten verfuegbaren Tag.
        if today_str in available_days:
            target_days = [today_str]
        else:
            target_days = available_days[:1]
            print(
                f"  Heute ({today_str}) nicht im Forecast-Fenster, "
                f"nutze stattdessen {target_days[0]}.",
                flush=True,
            )
    print(f"Snapshot-Ziel: {', '.join(target_days)}", flush=True)

    print(f"Berechne Thermik fuer {len(spots)} Spots (ueber gesamtes Fenster)...", flush=True)
    spot_thermals: Dict[str, Dict[str, Dict]] = {}
    skipped = 0
    for i, spot in enumerate(spots, 1):
        sdata = wetterdaten[spot]
        if "hourly_data" not in sdata:
            skipped += 1
            continue
        spot_thermals[spot] = compute_thermals_for_spot(spot, sdata, spot_meta)
        if i % 50 == 0:
            print(f"  ...{i}/{len(spots)} Spots", flush=True)
    print(f"Thermik fertig ({len(spot_thermals)} Spots, {skipped} ohne hourly_data).", flush=True)

    today = datetime.now().date()
    snapshots: Dict[str, Dict] = {}
    for day in target_days:
        out = {
            "_meta": {
                "snapshot_at": datetime.now().isoformat(timespec="seconds"),
                "forecast_date": day,
                "source_wetterdaten_last_updated": wetter_last_updated,
                "lead_time_days": (datetime.fromisoformat(day).date() - today).days,
                "schema_version": 1,
            },
            "spots": {},
            "regions": {},
        }

        for spot in spots:
            sdata = wetterdaten[spot]
            hourly_all = sdata.get("hourly_data") or {}
            if not hourly_all:
                continue
            hourly_day = {ts: v for ts, v in hourly_all.items() if ts[:10] == day}
            if not hourly_day:
                continue
            thermals = spot_thermals.get(spot, {}) or {}
            thermals_day = {ts: v for ts, v in thermals.items() if isinstance(ts, str) and ts[:10] == day}
            sm = spot_meta.get(spot, {})
            spot_ana_day = (spot_ana.get(spot, {}) or {}).get(day)

            out["spots"][spot] = {
                "latitude": sdata.get("latitude"),
                "longitude": sdata.get("longitude"),
                "elevation_m": sdata.get("elevation_m"),
                "analyse_region": sm.get("analyse_region"),
                "terrain_type": sm.get("terrain_type"),
                "windrichtung": sm.get("windrichtung"),
                "slope_azimuth": sm.get("slope_azimuth"),
                "slope_angle": sm.get("slope_angle"),
                "daily_aggregates": aggregate_daily(hourly_day, thermals_day),
                "hourly_flight": slice_hourly_flight(hourly_day, thermals_day),
                "analysis": extract_analysis(spot_ana_day),
            }

        for region_id, region_days in region_ana.items():
            r = region_days.get(day)
            if r:
                out["regions"][region_id] = extract_region_analysis(r)

        snapshots[day] = out

    return snapshots


def write_snapshots(snapshots: Dict[str, Dict]) -> int:
    """Schreibt Snapshots, ueberschreibt IMMER (kein Skip-Verhalten)."""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for day, snap in snapshots.items():
        path = ARCHIVE_DIR / f"{day}.json"
        existed = path.exists()
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        size_kb = path.stat().st_size // 1024
        action = "UPDATED" if existed else "WROTE"
        print(
            f"  {action} {day}: {path.relative_to(ROOT)} ({size_kb} KB, "
            f"{len(snap['spots'])} spots, {len(snap['regions'])} regions)",
            flush=True,
        )
        written += 1
    return written


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("date", nargs="?", help="Spezifisches YYYY-MM-DD (Default: heute)")
    p.add_argument("--all", dest="all_days", action="store_true",
                   help="Alle verfuegbaren Forecast-Tage (Debug/Backfill statt nur heute)")
    args = p.parse_args(argv)

    snapshots = build_snapshots(args.date, all_days=args.all_days)
    if not snapshots:
        print("Keine Snapshots erstellt.", flush=True)
        return 1

    written = write_snapshots(snapshots)
    print(f"Fertig. {written}/{len(snapshots)} Snapshot(s) geschrieben.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
