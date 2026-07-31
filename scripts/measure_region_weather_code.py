"""Misst, wie viele Gewitterstunden die Regions-Aggregation verliert.

Vergleicht fuer jede Region und Stunde zwei Auswertungen DERSELBEN Modelldaten:

  ALT  — weather_code des ersten Referenzpunkts (Verhalten bis Juli 2026:
         _aggregate_regional_data() liess weather_code auf data_list[0] stehen)
  NEU  — schwerwiegendster Code ueber alle Referenzpunkte der Region
         (fetch_weather._severest_weather_code)

Das ist eine reine Pipeline-Messung: sie beantwortet "wie viel vom
Modellsignal kommt an?", NICHT "hatte das Modell recht?". Die Frage, ob
ueberhaupt ein Gewitter war, wird gegen MeteoSchweiz-Stationsmessungen
beantwortet (scripts/validate_thunder_vs_stations.py) — niemals gegen
Modelldaten.

Usage:
    python scripts/measure_region_weather_code.py            # ICON-CH2, 3 Tage
    python scripts/measure_region_weather_code.py --days 5
    python scripts/measure_region_weather_code.py --model icon_d2
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config
from fetch_weather import (
    THUNDER_CODES,
    _api_get_with_retry,
    _severest_weather_code,
)
from source_area import get_all_regions

CHUNK = 80


def fetch_codes(points, model, days, past_days=0):
    """Holt weather_code + precipitation je Punkt. -> [{time, weather_code, ...}]

    `models` wird IMMER explizit gesetzt. Ohne den Parameter liefert Open-Meteo
    ECMWF IFS statt des Schweizer Modells — genau dieser stille Modellwechsel
    hat im Juli 2026 einen Scheinbefund erzeugt, der sich bei der Gegenprobe
    umkehrte.
    """
    results = []
    for start in range(0, len(points), CHUNK):
        chunk = points[start:start + CHUNK]
        params = {
            "latitude": ",".join(f"{p[0]:.4f}" for p in chunk),
            "longitude": ",".join(f"{p[1]:.4f}" for p in chunk),
            "models": model,
            "hourly": "weather_code,precipitation",
            "forecast_days": days,
            "timezone": config.TIMEZONE,
        }
        if past_days:
            params["past_days"] = past_days
        resp = _api_get_with_retry(
            config.API_URL,
            params,
            90,
            label=f"codes[{start}:{start + len(chunk)}]",
        )
        data = resp.json()
        results.extend(data if isinstance(data, list) else [data])
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default=config.SURFACE_SECONDARY_MODEL,
                    help="Open-Meteo Modell (Default: ICON-CH2)")
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--past-days", type=int, default=0,
                    help="Rueckblick in Tagen (Open-Meteo max 92)")
    args = ap.parse_args(argv)

    regions = get_all_regions()

    # Alle Referenzpunkte einmal sammeln (dedupliziert -> weniger API-Last)
    order, index = [], {}
    per_region = {}
    for r in regions:
        pts = [tuple(p) for p in (r.get("reference_points") or [])]
        per_region[r["id"]] = (r["region"], pts)
        for p in pts:
            key = (round(p[0], 4), round(p[1], 4))
            if key not in index:
                index[key] = len(order)
                order.append(p)

    print(f"{len(regions)} Regionen, {len(order)} eindeutige Referenzpunkte, "
          f"Modell={args.model}, {args.days} Tage "
          f"+ {args.past_days} Rueckblicktage")
    raw = fetch_codes(order, args.model, args.days, args.past_days)
    if len(raw) != len(order):
        print(f"  ! WARNUNG: {len(raw)} Antworten fuer {len(order)} Punkte")

    tot_old = tot_new = 0
    rows = []
    per_day_gain = defaultdict(int)

    for rid, (rname, pts) in per_region.items():
        idxs = [index[(round(p[0], 4), round(p[1], 4))] for p in pts]
        series = [raw[i].get("hourly", {}) for i in idxs if i < len(raw)]
        if not series:
            continue
        times = series[0].get("time", [])
        old_h = new_h = 0
        for i, t in enumerate(times):
            vals = [s.get("weather_code", [])[i]
                    for s in series
                    if i < len(s.get("weather_code", []))]
            if not vals:
                continue
            old = vals[0]
            new = _severest_weather_code(vals)
            o = old is not None and int(old) in THUNDER_CODES
            n = new is not None and int(new) in THUNDER_CODES
            old_h += o
            new_h += n
            if n and not o:
                per_day_gain[t[:10]] += 1
        tot_old += old_h
        tot_new += new_h
        if new_h:
            rows.append((new_h - old_h, old_h, new_h, rname, len(pts)))

    rows.sort(reverse=True)
    print()
    print(f"{'Region':30} {'RPs':>4} {'ALT':>5} {'NEU':>5} {'+':>5}")
    for gain, old_h, new_h, rname, npts in rows:
        print(f"{rname[:30]:30} {npts:4} {old_h:5} {new_h:5} {gain:+5}")

    print()
    print(f"Gewitterstunden gesamt   ALT (nur RP0): {tot_old}")
    print(f"Gewitterstunden gesamt   NEU (alle RP): {tot_new}")
    if tot_new:
        print(f"Anteil, der bisher ankam: {100.0 * tot_old / tot_new:.1f} %")
        print(f"Zusaetzlich erkannt:      {tot_new - tot_old} Stunden")
    else:
        print("Keine Gewitterstunden im Fenster — Messung nicht aussagekraeftig.")
    if per_day_gain:
        print()
        print("Zugewinn nach Tag:")
        for d in sorted(per_day_gain):
            print(f"  {d}: +{per_day_gain[d]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
