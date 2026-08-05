"""Validiert 5 Aggregations-Varianten fuer Region-Thermik gegen Spot-Median.

Vergleicht heute fuer 3 Regionen (Unterwallis, Berner Voralpen, Surselva):
  A: Status quo (Single Punkt mit hoechster Strahlung)
  B: Roh-Median ueber 7 Refpoints
  C: Top-4 nach Strahlung (Median)
  D: Sheridan-Lapse-korrigiert auf elev_ref, dann Median
  E: Spot-Median (Vergleichsanker, aus aktueller wetterdaten.json)

Output: max_h Tagespeak pro Variante + Bias zu Spot-Median.
"""
from __future__ import annotations
import json
import statistics as st
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
from thermik_calculator import compute_daily_thermals

TARGET_DATE = "2026-05-25"
FLIGHT_HOURS = range(8, 19)
PRESSURE_LEVELS_FETCHED = [850, 800, 750, 700, 650, 600, 550, 500]
ICAO_LAPSE = 6.5  # °C/km — Standard-Lapse fuer Sheridan-Korrektur

REGIONS = {
    "unterwallis": {"display": "Unterwallis", "elev_ref": 2200},
    "berner_voralpen": {"display": "Berner Voralpen", "elev_ref": 1950},
    "surselva": {"display": "Surselva", "elev_ref": 2200},
}


def load_raw():
    raw = json.loads(Path("/tmp/refpoint_pl_raw.json").read_text())
    meta = json.loads(Path("/tmp/refpoints_to_query.json").read_text())
    # pt_to_region keys are strings; map flat idx -> (rid, rp_idx)
    pt_map = {int(k): tuple(v) for k, v in meta["pt_to_region"].items()}
    return raw, pt_map, meta


def split_per_region(raw, pt_map):
    """Returns {rid: [rp_response_0, rp_response_1, ...]} ordered by rp_idx."""
    out: dict[str, list[dict]] = {}
    for flat_idx, resp in enumerate(raw):
        rid, rp_idx = pt_map[flat_idx]
        if rid not in out:
            out[rid] = [None] * 7
        out[rid][rp_idx] = resp
    return out


def mean_radiation_flight(rp_resp) -> float:
    """Mittlere Strahlung waehrend Flugstunden 08-18."""
    times = rp_resp["hourly"]["time"]
    rads = rp_resp["hourly"]["shortwave_radiation"]
    vals = [
        rads[i] for i, t in enumerate(times)
        if t[:10] == TARGET_DATE
        and int(t[11:13]) in FLIGHT_HOURS
        and rads[i] is not None
    ]
    return sum(vals) / len(vals) if vals else 0.0


def median_at_idx(arrs, i):
    vals = [a[i] for a in arrs if i < len(a) and a[i] is not None]
    return st.median(vals) if vals else None


def hourly_from_response(rp_resp) -> dict:
    """API-Response -> {ts: {field: val}} format (wie wetterdaten.json)."""
    h = rp_resp["hourly"]
    times = h["time"]
    out = {}
    for i, t in enumerate(times):
        row = {}
        for k, arr in h.items():
            if k == "time":
                continue
            row[k] = arr[i] if i < len(arr) else None
        out[t] = row
    return out


def pl_from_response(rp_resp) -> dict:
    """API-Response -> {ts: {pl_field: val}} mit nur PL-Feldern."""
    h = rp_resp["hourly"]
    times = h["time"]
    out = {}
    for i, t in enumerate(times):
        row = {}
        for k, arr in h.items():
            if k == "time" or "hPa" not in k:
                continue
            row[k] = arr[i] if i < len(arr) else None
        out[t] = row
    return out


def aggregate_variant(variant: str, rps: list[dict], elev_ref: float, _rid=None) -> tuple[dict, dict]:
    """Returns (hourly_data, pressure_level_data) aggregiert nach Variante."""
    n = len(rps)
    if variant == "A":  # Status quo
        rads = [(i, mean_radiation_flight(r)) for i, r in enumerate(rps)]
        best_i = max(rads, key=lambda x: x[1])[0]
        return hourly_from_response(rps[best_i]), pl_from_response(rps[best_i])

    # Bestimme Subset
    if variant == "B":  # Roh-Median ueber 7
        subset = list(range(n))
    elif variant == "C":  # Top-4 nach Strahlung
        rads = [(i, mean_radiation_flight(r)) for i, r in enumerate(rps)]
        rads.sort(key=lambda x: -x[1])
        subset = [x[0] for x in rads[:4]]
    elif variant == "D":  # Sheridan-Lapse-korrigiert
        subset = list(range(n))
    else:
        raise ValueError(variant)

    # Sammle alle ts
    all_times = rps[0]["hourly"]["time"]
    hourly_out: dict = {}
    pl_out: dict = {}

    # Surface fields die wir aggregieren (Median ueber Subset)
    sfc_fields_to_med = [
        "temperature_2m", "shortwave_radiation", "boundary_layer_height",
        "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
        "wind_speed_10m", "wind_direction_10m",
    ]

    for i, ts in enumerate(all_times):
        # --- Surface (hourly_data) ---
        sfc_row = {}
        for f in sfc_fields_to_med:
            arr = rps[subset[0]]["hourly"].get(f, [])
            if not arr:
                continue
            vals = []
            for k in subset:
                arr_k = rps[k]["hourly"].get(f, [])
                if i < len(arr_k) and arr_k[i] is not None:
                    vals.append(arr_k[i])
            if vals:
                sfc_row[f] = st.median(vals)
        hourly_out[ts] = sfc_row

        # --- Pressure-Level (pressure_level_data) ---
        pl_row = {}
        for lvl in PRESSURE_LEVELS_FETCHED:
            t_field = f"temperature_{lvl}hPa"
            gp_field = f"geopotential_height_{lvl}hPa"
            ws_field = f"wind_speed_{lvl}hPa"
            wd_field = f"wind_direction_{lvl}hPa"
            rh_field = f"relative_humidity_{lvl}hPa"

            if variant == "D":
                # Sheridan: pro Punkt die T auf elev_ref-equivalent Hoehe korrigieren
                # Idee: Punkt hat gp_height_LVL = z_LVL_at_point. Die Modell-Topografie
                # des Punkts unterscheidet sich. Wir bringen T_LVL auf eine gemeinsame
                # "true" Hoehe: T_corrected = T_at_LVL + lapse * (z_LVL_at_point - z_LVL_target)
                # Wobei z_LVL_target = median(z_LVL_at_point) ueber alle 7
                vals = []
                gp_vals_for_target = []
                for k in subset:
                    h_k = rps[k]["hourly"]
                    t_arr = h_k.get(t_field, [])
                    gp_arr = h_k.get(gp_field, [])
                    if i < len(t_arr) and i < len(gp_arr) and t_arr[i] is not None and gp_arr[i] is not None:
                        gp_vals_for_target.append(gp_arr[i])
                if not gp_vals_for_target:
                    continue
                z_target = st.median(gp_vals_for_target)
                t_corrected_vals = []
                for k in subset:
                    h_k = rps[k]["hourly"]
                    t_arr = h_k.get(t_field, [])
                    gp_arr = h_k.get(gp_field, [])
                    if i < len(t_arr) and i < len(gp_arr) and t_arr[i] is not None and gp_arr[i] is not None:
                        dz = gp_arr[i] - z_target  # >0 wenn Punkt das Level "hoeher" sieht
                        t_corr = t_arr[i] + ICAO_LAPSE * dz / 1000.0
                        t_corrected_vals.append(t_corr)
                if t_corrected_vals:
                    pl_row[t_field] = st.median(t_corrected_vals)
                pl_row[gp_field] = z_target
                # Wind/RH: einfacher Median ueber subset
                for f in (ws_field, wd_field, rh_field):
                    vals_f = []
                    for k in subset:
                        h_k = rps[k]["hourly"]
                        arr = h_k.get(f, [])
                        if i < len(arr) and arr[i] is not None:
                            vals_f.append(arr[i])
                    if vals_f:
                        pl_row[f] = st.median(vals_f)
            else:
                # B oder C: Roh-Median ueber subset, pro Feld separat
                for f in (t_field, gp_field, ws_field, wd_field, rh_field):
                    vals_f = []
                    for k in subset:
                        h_k = rps[k]["hourly"]
                        arr = h_k.get(f, [])
                        if i < len(arr) and arr[i] is not None:
                            vals_f.append(arr[i])
                    if vals_f:
                        pl_row[f] = st.median(vals_f)
        pl_out[ts] = pl_row

    return hourly_out, pl_out


def peak_max_h(thermal_results: dict, day: str) -> int | None:
    peak = 0
    for ts, t in thermal_results.items():
        if not isinstance(ts, str) or ts[:10] != day:
            continue
        hh = int(ts[11:13])
        if hh not in FLIGHT_HOURS:
            continue
        mh = t.get("max_height")
        if isinstance(mh, (int, float)) and mh > peak:
            peak = int(mh)
    return peak if peak > 0 else None


def main():
    raw, pt_map, meta = load_raw()
    per_region = split_per_region(raw, pt_map)

    # Spot-Median heute aus voriger Berechnung
    spot_med_today = json.loads(Path("/tmp/region_today_vs_spotmed.json").read_text())
    spot_med_by_display = {r["region"]: r["spot_med"] for r in spot_med_today}
    region_today_status_quo = {r["region"]: r["region_mh"] for r in spot_med_today}

    print(f"\n=== Aggregations-Varianten Vergleich — {TARGET_DATE} ===\n")
    print(f"{'Region':<22} {'Variante':<32} {'max_h':<8} {'vs Spot-Med':<12} {'|Bias|':<8}")
    print("-" * 90)

    all_results = []
    for rid, meta_r in REGIONS.items():
        disp = meta_r["display"]
        elev_ref = meta_r["elev_ref"]
        rps = per_region.get(rid, [])
        if not rps or any(r is None for r in rps):
            print(f"  SKIP {rid}: incomplete RPs")
            continue

        spot_med = spot_med_by_display.get(disp)
        if not spot_med:
            print(f"  WARN {disp}: no spot_med")
            spot_med = 0
        status_quo_archive = region_today_status_quo.get(disp)

        print(f"\n{disp} (elev_ref={elev_ref}m, Spot-Median heute = {spot_med}m, n_spots aus Statistik):")

        for variant in ["A", "B", "C", "D"]:
            label = {
                "A": "Status quo (max-Strahlung-RP)",
                "B": "Roh-Median 7 RPs",
                "C": "Top-4 nach Strahlung",
                "D": "Sheridan-Lapse-korrigiert",
            }[variant]
            try:
                hourly, pld = aggregate_variant(variant, rps, elev_ref, rid)
                therm = compute_daily_thermals(
                    hourly, pld, elev_ref, config.PRESSURE_LEVELS, region_id=rid
                )
                mh = peak_max_h(therm, TARGET_DATE)
            except Exception as e:
                print(f"  ERROR {variant}: {e}")
                mh = None

            if mh is not None and spot_med:
                bias = mh - spot_med
                print(f"  {variant} {label:<30}: {mh:<6}m  diff {bias:+5}m  |{abs(bias)}|")
                all_results.append({
                    "region": disp, "rid": rid, "variant": variant,
                    "label": label, "max_h": mh, "spot_med": spot_med,
                    "bias": bias, "abs_bias": abs(bias),
                })
            else:
                print(f"  {variant} {label:<30}: {mh!s}")

        # E: Spot-Median (Anker)
        print(f"  E {'Spot-Median (Anker)':<30}: {spot_med}m  diff {0:+5}m  |0|")
        all_results.append({
            "region": disp, "rid": rid, "variant": "E",
            "label": "Spot-Median (Anker)", "max_h": spot_med, "spot_med": spot_med,
            "bias": 0, "abs_bias": 0,
        })

    # Aggregierte Stats pro Variante
    print(f"\n\n=== AGGREGATE BIAS pro VARIANTE (3 Regionen) ===")
    print(f"{'Variante':<35} {'Mittel-Bias':<13} {'Median-|Bias|':<14} {'max |Bias|':<11}")
    print("-" * 80)
    by_var = {}
    for r in all_results:
        by_var.setdefault(r["variant"], []).append(r)
    for variant in ["A", "B", "C", "D", "E"]:
        if variant not in by_var:
            continue
        rs = by_var[variant]
        biases = [r["bias"] for r in rs]
        abs_b = [r["abs_bias"] for r in rs]
        label = rs[0]["label"]
        print(f"{label:<35} {st.mean(biases):+6.0f}      {st.mean(abs_b):6.0f}        {max(abs_b):6.0f}")

    Path("/tmp/variants_result.json").write_text(json.dumps(all_results, indent=2))


if __name__ == "__main__":
    main()
