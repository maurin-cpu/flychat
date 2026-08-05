"""Vollstaendiger Vergleich: alle Regionen, 4 Varianten (A/B/D/E).

A: Status quo (1 RP mit max Strahlung)
B: Roh-Median ueber 7 RPs
D: Sheridan-Lapse-korrigiert (Median ueber 7 RPs nach Hoehen-Korrektur)
E: Spot-Median (aus /tmp/region_today_vs_spotmed.json)
"""
from __future__ import annotations
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
from thermik_calculator import compute_daily_thermals

TARGET_DATE = "2026-05-25"
FLIGHT_HOURS = range(8, 19)
PL_LEVELS = [850, 800, 750, 700, 650, 600, 550, 500]
ICAO_LAPSE = 6.5


def mean_radiation_flight(rp_resp):
    times = rp_resp["hourly"]["time"]
    rads = rp_resp["hourly"]["shortwave_radiation"]
    vals = [rads[i] for i, t in enumerate(times)
            if t[:10] == TARGET_DATE and int(t[11:13]) in FLIGHT_HOURS and rads[i] is not None]
    return sum(vals)/len(vals) if vals else 0.0


def hourly_from_response(rp_resp):
    h = rp_resp["hourly"]
    times = h["time"]
    return {t: {k: arr[i] if i < len(arr) else None for k, arr in h.items() if k != "time"}
            for i, t in enumerate(times)}


def pl_from_response(rp_resp):
    h = rp_resp["hourly"]
    times = h["time"]
    return {t: {k: arr[i] if i < len(arr) else None for k, arr in h.items() if k != "time" and "hPa" in k}
            for i, t in enumerate(times)}


def aggregate_variant(variant, rps, elev_ref):
    n = len(rps)
    if variant == "A":
        rads = [(i, mean_radiation_flight(r)) for i, r in enumerate(rps)]
        best_i = max(rads, key=lambda x: x[1])[0]
        return hourly_from_response(rps[best_i]), pl_from_response(rps[best_i])

    subset = list(range(n))
    all_times = rps[0]["hourly"]["time"]
    hourly_out, pl_out = {}, {}

    sfc_fields = ["temperature_2m", "shortwave_radiation", "boundary_layer_height",
                  "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
                  "wind_speed_10m", "wind_direction_10m"]

    for i, ts in enumerate(all_times):
        sfc_row = {}
        for f in sfc_fields:
            vals = []
            for k in subset:
                arr = rps[k]["hourly"].get(f, [])
                if i < len(arr) and arr[i] is not None:
                    vals.append(arr[i])
            if vals:
                sfc_row[f] = st.median(vals)
        hourly_out[ts] = sfc_row

        pl_row = {}
        for lvl in PL_LEVELS:
            t_f = f"temperature_{lvl}hPa"
            gp_f = f"geopotential_height_{lvl}hPa"
            ws_f = f"wind_speed_{lvl}hPa"
            wd_f = f"wind_direction_{lvl}hPa"
            rh_f = f"relative_humidity_{lvl}hPa"

            if variant == "D":
                gps = []
                for k in subset:
                    arr = rps[k]["hourly"].get(gp_f, [])
                    if i < len(arr) and arr[i] is not None:
                        gps.append(arr[i])
                if not gps:
                    continue
                z_target = st.median(gps)
                t_corrs = []
                for k in subset:
                    t_arr = rps[k]["hourly"].get(t_f, [])
                    gp_arr = rps[k]["hourly"].get(gp_f, [])
                    if i < len(t_arr) and i < len(gp_arr) and t_arr[i] is not None and gp_arr[i] is not None:
                        dz = gp_arr[i] - z_target
                        t_corrs.append(t_arr[i] + ICAO_LAPSE * dz / 1000.0)
                if t_corrs:
                    pl_row[t_f] = st.median(t_corrs)
                pl_row[gp_f] = z_target
                for f in (ws_f, wd_f, rh_f):
                    vals = [rps[k]["hourly"].get(f, [None])[i] for k in subset
                            if i < len(rps[k]["hourly"].get(f, [])) and rps[k]["hourly"][f][i] is not None]
                    if vals:
                        pl_row[f] = st.median(vals)
            else:  # B
                for f in (t_f, gp_f, ws_f, wd_f, rh_f):
                    vals = [rps[k]["hourly"].get(f, [None])[i] for k in subset
                            if i < len(rps[k]["hourly"].get(f, [])) and rps[k]["hourly"][f][i] is not None]
                    if vals:
                        pl_row[f] = st.median(vals)
        pl_out[ts] = pl_row
    return hourly_out, pl_out


def peak_max_h(therm, day):
    peak = 0
    for ts, t in therm.items():
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
    d = json.loads(Path("/tmp/all_regions_refpoints.json").read_text())
    regions = d["regions"]
    pt_map = {int(k): tuple(v) for k, v in d["pt_to_region"].items()}
    responses = d["responses"]

    # Split nach Region
    per_region = {}
    for flat_idx, resp in enumerate(responses):
        rid, rp_idx = pt_map[flat_idx]
        per_region.setdefault(rid, [None]*7)[rp_idx] = resp

    # Spot-Median Werte (E) und Status-quo (A_archive) bereits berechnet
    spot_data = json.loads(Path("/tmp/region_today_vs_spotmed.json").read_text())
    spot_by_disp = {r["region"]: r for r in spot_data}

    results = []
    for rid, info in regions.items():
        rps = per_region.get(rid)
        if not rps or any(r is None for r in rps):
            continue
        elev_ref = info["elev_ref"]
        disp = info["display"]

        e_data = spot_by_disp.get(disp, {})
        spot_med = e_data.get("spot_med")
        n_spots = e_data.get("n_spots", 0)
        a_archive = e_data.get("region_mh")  # Status quo aus vorigem Lauf

        row = {"rid": rid, "display": disp, "elev_ref": elev_ref,
               "n_spots": n_spots, "spot_med_E": int(spot_med) if spot_med else None,
               "status_quo_A_archive": a_archive}

        for variant in ["A", "B", "D"]:
            try:
                hourly, pld = aggregate_variant(variant, rps, elev_ref)
                therm = compute_daily_thermals(hourly, pld, elev_ref, config.PRESSURE_LEVELS, region_id=rid)
                row[f"max_h_{variant}"] = peak_max_h(therm, TARGET_DATE)
            except Exception as e:
                row[f"max_h_{variant}"] = None
                row[f"err_{variant}"] = str(e)
        results.append(row)

    Path("/tmp/all_variants_results.json").write_text(json.dumps(results, indent=2, default=str))

    # === Tabellen-Output ===
    # Sortiert nach Region-Display
    print(f"\n{'='*120}")
    print(f"Vergleich Status quo (A) vs. Refpoint-Median (B) vs. Sheridan-Lapse (D) vs. Spot-Median (E)")
    print(f"{'='*120}\n")
    print(f"{'Region':<28} {'n_Sp':<5} {'A_quo':<7} {'B_med':<7} {'D_lap':<7} {'E_spotmed':<10} "
          f"{'B−A':<6} {'D−A':<6} {'E−A':<6}")
    print("-" * 120)

    def fmt(v):
        return f"{v}" if v is not None else "—"

    sorted_rows = sorted(results, key=lambda r: r["display"])
    for r in sorted_rows:
        a = r.get("max_h_A")
        b = r.get("max_h_B")
        de = r.get("max_h_D")
        e = r.get("spot_med_E")
        ba = (b - a) if (a and b) else None
        da = (de - a) if (a and de) else None
        ea = (e - a) if (a and e) else None
        def fd(x):
            return f"{x:+d}" if x is not None else "—"
        print(f"{r['display']:<28} {r['n_spots']!s:<5} {fmt(a):<7} {fmt(b):<7} {fmt(de):<7} {fmt(e):<10} "
              f"{fd(ba):<6} {fd(da):<6} {fd(ea):<6}")

    # Aggregat-Statistik (Bias gegen E, Spot-Median als Anker)
    print(f"\n\n=== BIAS gegen Spot-Median (E) ===\n")
    print(f"{'Variante':<25} {'Mittel-Bias':<13} {'Median |Bias|':<14} {'max |Bias|':<11} {'Treffer ±200m'}")
    print("-" * 80)
    for variant in ["A", "B", "D"]:
        diffs = []
        hits = 0
        for r in results:
            v = r.get(f"max_h_{variant}")
            e = r.get("spot_med_E")
            if v and e:
                d = v - e
                diffs.append(d)
                if abs(d) <= 200:
                    hits += 1
        if diffs:
            label = {"A": "Status quo (1 RP)", "B": "Roh-Median 7 RPs",
                     "D": "Sheridan-Lapse 7 RPs"}[variant]
            print(f"{label:<25} {st.mean(diffs):+6.0f}      {st.mean([abs(x) for x in diffs]):6.0f}        "
                  f"{max(abs(x) for x in diffs):6.0f}      {hits}/{len(diffs)}")

    # Wallis-Fokus mit Pilot-Realität
    print(f"\n\n=== WALLIS gegen Pilot-Realität 3500–4000m ===\n")
    wallis = ["Unterwallis", "Zentralwallis", "Mattertal / Saastal", "Oberwallis / Goms"]
    print(f"{'Region':<22} {'A':<6} {'B':<6} {'D':<6} {'E':<6}")
    for disp in wallis:
        for r in results:
            if r["display"] == disp:
                def hit(v):
                    if v is None: return "—"
                    if 3500 <= v <= 4000: return "OK"
                    return f"{v-3750:+d}"
                print(f"{disp:<22} {hit(r.get('max_h_A')):<6} {hit(r.get('max_h_B')):<6} "
                      f"{hit(r.get('max_h_D')):<6} {hit(r.get('spot_med_E')):<6}")


if __name__ == "__main__":
    main()
