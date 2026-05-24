"""
Backfill _rating_inputs + aggregates fuer bestehende Labels in
data/labeled_examples.jsonl.

Hintergrund: vor Mai 2026 wurden im Snapshot die Thermik-Aggregates
(climb_peak, productive_thermal_h, rough_pct etc.) auf None gesetzt.
Nach dem Fix in engine/analyzers.py (`_attach_rating_inputs`) persistieren
neue Analysen die Werte in `result["_rating_inputs"]`.

Fuer Alt-Labels koennen wir die Werte rekonstruieren, sofern:
- die Pressure-Level-Daten fuer das Ziel-Datum in data/wetterdaten.json
  noch vorhanden sind (Cache haelt ~5 Forecast-Tage).

Ohne Pressure-Levels: Label wird uebersprungen.

Approximationen vs. Production:
- productive_thermal_h: nutzt Surface-Cloud-Cover statt Band-Average.
- Keine ROUGH-UNUSABLE / WIND-UNUSABLE Pruefung (rough_pct bleibt None).
- Sonst identisch zur Production-Logik in engine/weather_context.py.

Usage:
    python scripts/backfill_label_aggregates.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config
from engine.labeled_examples import (
    JSONL_PATH,
    _FileLock,
    LOCK_PATH,
    _atomic_write_all,
    load_all,
    resolve_spot_name,
)
from engine.weather_context import _classify_cloud_structure, _compute_sustained_peak, _median
from fetch_weather import load_cached_weather
from thermik_calculator import compute_daily_thermals


def _pressure_slice_for(node: dict, target_date: str) -> dict:
    plev_all = node.get("pressure_level_data") or {}
    prefix = f"{target_date}T"
    return {ts: v for ts, v in plev_all.items() if ts.startswith(prefix)}


def _node_for_label(raw_weather: dict, kind: str, entity_id: str) -> dict | None:
    if kind == "region":
        return (raw_weather.get("_regions") or {}).get(entity_id)
    site_name = resolve_spot_name(entity_id) or entity_id
    return raw_weather.get(site_name)


def _compute_rating_inputs(
    hourly: dict,
    pressure_levels: dict,
    elevation_m: float,
) -> dict | None:
    """Replikiert die Aggregate-Berechnung aus weather_context.py auf den
    gespeicherten Hourly-Slice.

    Vereinfachungen ggue. Production:
    - Surface-Cloud (cloud_cover_low/mid/high) statt Band-Average.
    - Keine ROUGH-UNUSABLE / WIND-UNUSABLE-Pruefung (rough_pct = None).
    """
    if not hourly or not pressure_levels:
        return None

    daily_thermals = compute_daily_thermals(
        hourly,
        pressure_levels,
        elevation_m,
        config.PRESSURE_LEVELS,
    )

    hourly_climbs: list[float] = []
    prod_tops_agl: list[float] = []
    productive_thermal_h = 0
    productive_h_strict = 0
    peak_climb = 0.0
    cloud_low_sum = 0.0
    cloud_mid_sum = 0.0
    cloud_high_sum = 0.0
    thermal_hours = 0

    for ts in sorted(hourly.keys()):
        therm = daily_thermals.get(ts) or {}
        if "error" in therm or therm.get("climb_rate") is None:
            continue
        climb = therm.get("climb_rate") or 0.0
        if not isinstance(climb, (int, float)):
            continue
        hourly_climbs.append(float(climb))
        if climb > peak_climb:
            peak_climb = float(climb)

        h = hourly[ts] or {}
        low = h.get("cloud_cover_low") or 0
        mid = h.get("cloud_cover_mid") or 0
        high = h.get("cloud_cover_high") or 0

        thermal_hours += 1
        cloud_low_sum += float(low)
        cloud_mid_sum += float(mid)
        cloud_high_sum += float(high)

        # productive_thermal_h: climb >= PRODUCTIVE_CLIMB_MIN + saubere Sicht.
        # Vereinfacht: Surface-Cloud statt Band-Average.
        if (climb >= config.PRODUCTIVE_CLIMB_MIN
                and low <= config.PRODUCTIVE_LOW_CLOUD_MAX
                and mid <= config.PRODUCTIVE_MID_CLOUD_MAX):
            productive_thermal_h += 1

            # Working-Height = Thermik-Top AGL (capped bei LCL)
            top_raw = therm.get("max_height")
            lcl = therm.get("lcl")
            if isinstance(top_raw, (int, float)) and isinstance(lcl, (int, float)):
                top = min(top_raw, lcl)
            else:
                top = top_raw
            if isinstance(top, (int, float)):
                prod_tops_agl.append(top - elevation_m)

        if climb >= 1.5:
            productive_h_strict += 1

    if thermal_hours == 0:
        return None

    avg_low = cloud_low_sum / thermal_hours
    avg_mid = cloud_mid_sum / thermal_hours
    avg_high = cloud_high_sum / thermal_hours
    cloud_structure = _classify_cloud_structure(avg_low, avg_mid, avg_high)
    sustained_peak = _compute_sustained_peak(hourly_climbs, window=2)
    working_height_agl = round(_median(prod_tops_agl)) if prod_tops_agl else 0

    return {
        "peak_climb_proxy": round(peak_climb, 2),
        "sustained_peak_mps": sustained_peak,
        "productive_thermal_h": productive_thermal_h,
        "productive_h_strict": productive_h_strict,
        "working_height_agl_m": working_height_agl,
        "cloud_structure": cloud_structure,
        # rough_*-Felder nicht rekonstruierbar ohne Tag-Pipeline → None.
        "rough_danger_h": None,
        "thermal_hours_total": thermal_hours,
        "rough_pct": None,
    }


def backfill(dry_run: bool = False) -> dict:
    raw_weather = load_cached_weather() or {}

    entries = load_all()
    if not entries:
        print("Keine Labels gefunden.")
        return {"updated": 0, "skipped_no_data": 0, "skipped_already_filled": 0}

    updated = 0
    skipped_no_data = 0
    skipped_already_filled = 0
    skipped_no_thermals = 0

    for entry in entries:
        analysis_id = entry.get("analysis_id")
        kind = entry.get("entity_type")
        entity_slug = entry.get("entity_slug") or entry.get("spot_or_region_id")
        target_date = entry.get("target_date")

        # Schon befuellt?
        llm_out = entry.get("llm_output_full") or {}
        if llm_out.get("_rating_inputs"):
            skipped_already_filled += 1
            continue

        node = _node_for_label(raw_weather, kind, entity_slug)
        if not node:
            print(f"SKIP {analysis_id}: keine Wetterdaten in Cache (Entitaet weg)")
            skipped_no_data += 1
            continue

        plev_day = _pressure_slice_for(node, target_date)
        if not plev_day:
            print(f"SKIP {analysis_id}: keine Pressure-Level fuer {target_date}")
            skipped_no_data += 1
            continue

        # Hourly aus dem Label-Snapshot ist die Wahrheit (zur Label-Zeit). Falls
        # weg, fallback auf den aktuellen Wetter-Cache.
        wi = entry.get("weather_input") or {}
        hourly = wi.get("hourly") or {}
        if not hourly:
            hourly_all = node.get("hourly_data") or {}
            prefix = f"{target_date}T"
            hourly = {ts: v for ts, v in hourly_all.items() if ts.startswith(prefix)}
        if not hourly:
            print(f"SKIP {analysis_id}: keine Hourly-Daten")
            skipped_no_data += 1
            continue

        elevation_m = wi.get("elevation_m")
        if not isinstance(elevation_m, (int, float)):
            print(f"SKIP {analysis_id}: keine Elevation")
            skipped_no_data += 1
            continue

        ri = _compute_rating_inputs(hourly, plev_day, float(elevation_m))
        if not ri:
            print(f"SKIP {analysis_id}: keine produktive Thermik (kein Tag)")
            skipped_no_thermals += 1
            continue

        # 1) llm_output_full._rating_inputs (Single Source of Truth)
        llm_out["_rating_inputs"] = ri
        entry["llm_output_full"] = llm_out

        # 2) weather_input.aggregates (Feature-Vektor-Quelle)
        agg = wi.get("aggregates") or {}
        thermal_total = ri.get("thermal_hours_total")
        rough_h = ri.get("rough_danger_h")
        rough_pct = None
        if isinstance(thermal_total, int) and thermal_total > 0 and isinstance(rough_h, int):
            rough_pct = round(100.0 * rough_h / thermal_total, 1)
        agg.update({
            "climb_peak": ri.get("peak_climb_proxy"),
            "sustained_peak_mps": ri.get("sustained_peak_mps"),
            "productive_thermal_h": ri.get("productive_thermal_h"),
            "productive_h_strict": ri.get("productive_h_strict"),
            "working_height_agl_m": ri.get("working_height_agl_m"),
            "cloud_structure": ri.get("cloud_structure"),
            "rough_pct": rough_pct,
        })
        wi["aggregates"] = agg
        # Marker: diese Aggregates wurden nachtraeglich aus dem aktuellen
        # wetterdaten.json rekonstruiert (nicht zur Label-Zeit). Approximation
        # gegenueber production. Regression kann nach diesem Feld filtern.
        wi["aggregates_source"] = "backfill_approx"
        entry["weather_input"] = wi

        updated += 1
        peak = ri.get("peak_climb_proxy")
        prod_h = ri.get("productive_thermal_h")
        wh = ri.get("working_height_agl_m")
        cs = ri.get("cloud_structure")
        print(f"  OK {analysis_id}: peak={peak} prod_h={prod_h} wh={wh}m struct={cs}")

    if dry_run:
        print(f"\n[DRY-RUN] Wuerde {updated} Labels schreiben.")
    else:
        with _FileLock(LOCK_PATH):
            _atomic_write_all(entries)
        print(f"\nGespeichert: {updated} Labels aktualisiert.")

    return {
        "updated": updated,
        "skipped_no_data": skipped_no_data,
        "skipped_already_filled": skipped_already_filled,
        "skipped_no_thermals": skipped_no_thermals,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Nichts schreiben, nur loggen.")
    args = parser.parse_args()

    print(f"JSONL: {JSONL_PATH}")
    print(f"Dry-Run: {args.dry_run}\n")
    stats = backfill(dry_run=args.dry_run)
    print("\nZusammenfassung:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
