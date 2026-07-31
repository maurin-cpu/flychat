"""Validiert die Regions-Vorhersage gegen MeteoSchweiz-Stationsmessungen.

Vergleicht ZWEI Auswertungen derselben Modelldaten gegen dieselbe Wahrheit:
  ALT — weather_code des ersten Referenzpunkts (Stand bis Juli 2026)
  NEU — schwerwiegendster Code ueber alle Referenzpunkte

Beide Varianten entstehen durch Aufruf der PRODUKTIVEN Aggregation
(fetch_weather._aggregate_regional_data), einmal mit und einmal ohne
aggregate_weather_code. So misst der Test den echten Codepfad und nicht eine
nachgebaute Kopie davon.

WAHRHEIT
--------
MeteoSchweiz-Stundenmessungen, nie Modelldaten (siehe scripts/
meteoschweiz_stations.py). Vor jeder Auswertung wird die Zeitzuordnung ueber
die Temperatur bewiesen; liegt das Minimum nicht bei Verschiebung 0, bricht
das Skript ab.

  Regen        rre150h0 >= 1.0 mm an einem Tag  -> "es hat geregnet"
  Gewitter     rre150h0 >= 5.0 mm in EINER Stunde -> Hilfsindikator

Der Gewitter-Indikator ist SCHWACH: offene Blitzdaten gibt es nicht, und
Starkregen entsteht auch ohne Gewitter. Ergebnisse entsprechend vorsichtig
lesen — sie zeigen eine Richtung, sie beweisen nichts.

Usage:
    python scripts/validate_thunder_vs_stations.py --past-days 60
"""

from __future__ import annotations

import argparse
import copy
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config
from fetch_weather import (
    THUNDER_CODES,
    _aggregate_regional_data,
    _api_get_with_retry,
)
from source_area import get_all_regions
from spots import load_spots

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from meteoschweiz_stations import (  # noqa: E402
    assign_stations_to_regions,
    check_alignment,
    load_hourly,
    load_stations,
)

CHUNK = 80
RAIN_DAY_MM = 1.0        # Tag gilt als Regentag
THUNDER_PROXY_MM_H = 5.0  # Hilfsindikator "Gewitter" (schwach!)
ALIGN_MAX_ABS_K = 3.0     # Grenze fuer die RESTabweichung (Hoehenversatz ist rausgerechnet)


def fetch_points(points, model, days, past_days):
    """Holt weather_code/precipitation/temperature je Referenzpunkt.

    `models` wird IMMER gesetzt — ohne den Parameter liefert Open-Meteo ECMWF
    IFS statt des Schweizer Modells.
    """
    out = []
    for start in range(0, len(points), CHUNK):
        chunk = points[start:start + CHUNK]
        params = {
            "latitude": ",".join(f"{p[0]:.4f}" for p in chunk),
            "longitude": ",".join(f"{p[1]:.4f}" for p in chunk),
            "models": model,
            "hourly": "weather_code,precipitation,temperature_2m",
            "forecast_days": days,
            "timezone": config.TIMEZONE,
        }
        if past_days:
            params["past_days"] = past_days
        resp = _api_get_with_retry(config.API_URL, params, 120,
                                   label=f"pts[{start}:{start + len(chunk)}]")
        data = resp.json()
        out.extend(data if isinstance(data, list) else [data])
    return out


def _rate(hit, total):
    return f"{100.0 * hit / total:5.1f} %" if total else "    - "


def score(flagged_days, truth_days, all_days):
    """-> (treffer, verpasst, fehlalarm, trefferquote)"""
    hit = len(flagged_days & truth_days)
    missed = len(truth_days - flagged_days)
    false = len(flagged_days - truth_days)
    rate = 100.0 * hit / len(truth_days) if truth_days else None
    return hit, missed, false, rate


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default=config.SURFACE_SECONDARY_MODEL)
    ap.add_argument("--past-days", type=int, default=60)
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--max-km", type=float, default=12.0)
    args = ap.parse_args(argv)

    print("=== Stationen ===")
    stations = load_stations()
    spots = load_spots(config.CSV_PATH)
    mapping = assign_stations_to_regions(stations, spots, max_km=args.max_km)
    by_region = defaultdict(list)
    for abbr, m in mapping.items():
        by_region[m["region"]].append(abbr)
    print(f"{len(stations)} Stationen, {len(mapping)} innerhalb {args.max_km:.0f} km "
          f"eines Fluggebiets, {len(by_region)} Regionen abgedeckt")

    print("Lade Stundenmessungen...")
    obs = {}
    for abbr in mapping:
        h = load_hourly(abbr)
        if h:
            obs[abbr] = h
    print(f"{len(obs)} Stationen mit Messreihe")

    print()
    print("=== Modelldaten ===")
    regions = get_all_regions()
    order, index, per_region = [], {}, {}
    for r in regions:
        pts = [tuple(p) for p in (r.get("reference_points") or [])]
        if not pts:
            continue
        per_region[r["region"]] = pts
        for p in pts:
            key = (round(p[0], 4), round(p[1], 4))
            if key not in index:
                index[key] = len(order)
                order.append(p)
    print(f"{len(per_region)} Regionen, {len(order)} Referenzpunkte, "
          f"Modell={args.model}, {args.past_days} Rueckblicktage")
    raw = fetch_points(order, args.model, args.days, args.past_days)

    # --- Aggregation ueber den PRODUKTIVEN Codepfad, beide Varianten ---
    agg_old, agg_new = {}, {}
    for rname, pts in per_region.items():
        series = [raw[index[(round(p[0], 4), round(p[1], 4))]]
                  for p in pts
                  if index.get((round(p[0], 4), round(p[1], 4)), len(raw)) < len(raw)]
        if not series:
            continue
        agg_old[rname] = _aggregate_regional_data(copy.deepcopy(series))
        agg_new[rname] = _aggregate_regional_data(copy.deepcopy(series),
                                                  aggregate_weather_code=True)

    # --- Zeitachse beweisen (Temperatur) ---
    print()
    print("=== Zeitzuordnung (Beweis ueber Temperatur) ===")
    pairs = []
    for rname, abbrs in by_region.items():
        a = agg_new.get(rname)
        if not a:
            continue
        h = a["hourly"]
        model_temp = {t[:13]: v for t, v in
                      zip(h.get("time", []), h.get("temperature_2m", []))
                      if v is not None}
        for abbr in abbrs:
            if abbr in obs:
                pairs.append((obs[abbr], model_temp))
    best, errors = check_alignment(pairs)
    for s in sorted(errors):
        mark = "  <== Minimum" if s == best else ""
        print(f"  Verschiebung {s:+d} h: Restabweichung {errors[s]:.2f} K{mark}")
    if best != 0:
        print()
        print(f"ABBRUCH: Minimum liegt bei {best:+d} h statt 0 h — die Zeitzuordnung "
              f"stimmt nicht. Jede Trefferquote darauf waere wertlos.")
        return 1
    if errors.get(0, 99) > ALIGN_MAX_ABS_K:
        print()
        print(f"ABBRUCH: Restabweichung bei 0 h ist {errors[0]:.2f} K (> {ALIGN_MAX_ABS_K} K).")
        return 1
    print(f"  OK — Minimum bei 0 h ({errors[0]:.2f} K).")

    # --- Wahrheit je Region und Tag ---
    truth_rain, truth_thunder, obs_days = set(), set(), set()
    for rname, abbrs in by_region.items():
        daily_sum = defaultdict(float)
        daily_peak = defaultdict(float)
        for abbr in abbrs:
            for key, rec in obs.get(abbr, {}).items():
                mm = rec.get("precip_mm")
                if mm is None:
                    continue
                day = key[:10]
                daily_sum[(rname, day, abbr)] += mm
                daily_peak[(rname, day)] = max(daily_peak[(rname, day)], mm)
        for (rn, day, _abbr), s in daily_sum.items():
            obs_days.add((rn, day))
            if s >= RAIN_DAY_MM:
                truth_rain.add((rn, day))
        for (rn, day), pk in daily_peak.items():
            if pk >= THUNDER_PROXY_MM_H:
                truth_thunder.add((rn, day))

    # --- Vorhersage je Region und Tag ---
    def flags(agg):
        rain, thunder = set(), set()
        for rname, a in agg.items():
            h = a["hourly"]
            times = h.get("time", [])
            codes = h.get("weather_code", [])
            precip = h.get("precipitation", [])
            day_sum = defaultdict(float)
            for i, t in enumerate(times):
                day = t[:10]
                if i < len(precip) and precip[i] is not None:
                    day_sum[day] += precip[i]
                if i < len(codes) and codes[i] is not None:
                    try:
                        if int(codes[i]) in THUNDER_CODES:
                            thunder.add((rname, day))
                    except (TypeError, ValueError):
                        pass
            for day, s in day_sum.items():
                if s >= RAIN_DAY_MM:
                    rain.add((rname, day))
        return rain, thunder

    rain_old, th_old = flags(agg_old)
    rain_new, th_new = flags(agg_new)

    # Nur Region-Tage werten, fuer die es ueberhaupt eine Messung gibt.
    rain_old &= obs_days
    rain_new &= obs_days
    th_old &= obs_days
    th_new &= obs_days
    truth_rain &= obs_days
    truth_thunder &= obs_days

    print()
    print(f"=== Bewertete Region-Tage: {len(obs_days)} ===")
    print(f"    davon mit gemessenem Regen (>= {RAIN_DAY_MM} mm/Tag): {len(truth_rain)}")
    print(f"    davon mit >= {THUNDER_PROXY_MM_H} mm in einer Stunde:  {len(truth_thunder)}")

    print()
    print("=== REGEN (darf sich nicht verschlechtern) ===")
    print(f"{'Variante':10} {'Treffer':>8} {'Verpasst':>9} {'Fehlalarm':>10} {'Quote':>8}")
    for label, s in (("ALT", rain_old), ("NEU", rain_new)):
        hit, miss, false, rate = score(s, truth_rain, obs_days)
        print(f"{label:10} {hit:8} {miss:9} {false:10} "
              f"{(f'{rate:5.1f} %' if rate is not None else '    -'):>8}")
    if rain_old == rain_new:
        print("  -> identisch. Die Aenderung fasst Niederschlag nicht an.")

    print()
    print(f"=== GEWITTER (Hilfsindikator >= {THUNDER_PROXY_MM_H} mm/h — schwach) ===")
    print(f"{'Variante':10} {'Treffer':>8} {'Verpasst':>9} {'Fehlalarm':>10} {'Quote':>8}")
    for label, s in (("ALT", th_old), ("NEU", th_new)):
        hit, miss, false, rate = score(s, truth_thunder, obs_days)
        print(f"{label:10} {hit:8} {miss:9} {false:10} "
              f"{(f'{rate:5.1f} %' if rate is not None else '    -'):>8}")
    print(f"  Region-Tage mit Gewitter-Code: ALT {len(th_old)}, NEU {len(th_new)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
