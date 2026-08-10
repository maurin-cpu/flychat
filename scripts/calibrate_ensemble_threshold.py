"""Kalibriert die Ensemble-Gewitterschwelle gegen MeteoSchweiz-Stationsmessungen.

Der Auftrag verlangt ausdruecklich, die Schwellen VOR einem Livegang zu pruefen.
Bis dahin sind config.ENSEMBLE_THUNDER_* geraten (Startpunkt 20/40/60 %).

ACHTUNG — RUECKWIRKEND GEHT DAS NICHT (gemessen 2026-07-31)
-----------------------------------------------------------
Der erste Versuch dieser Kalibrierung war WERTLOS und sah trotzdem sauber aus:
alle Schwellen von 5 % bis 75 % lieferten exakt 0 Treffer.

Ursache: `past_days` fuellt beim Ensemble-Endpunkt die Vergangenheit mit EINER
einzigen Reihe. Aelter als rund drei Tage sind alle 21 Member identisch — es
gibt dort kein Ensemble, dessen Streuung man auswerten koennte. Gemessen an
einem Punkt der Zentralschweizer Alpen:

    05.07. / 15.07. / 19.07. / 25.07. / 27.07.  ->  24 von 24 Stunden identisch
    28.07.                                      ->  10 von 24 Stunden mit Streuung
    29.07. / 31.07.                             ->  23 von 24 Stunden mit Streuung

Das Skript prueft die Member-Streuung deshalb SELBST und wirft Tage ohne
Streuung raus. Bleiben zu wenige uebrig, bricht es ab statt eine Tabelle voller
Nullen auszugeben.

Der belastbare Weg ist VORWAERTS sammeln: scripts/snapshot_weather.py
archiviert `thunder_ensemble` taeglich mit. Sobald genug Tage beisammen sind,
laesst sich gegen die Stationsmessungen kalibrieren — dann mit echten Membern.

Verfahren
---------
Fuer jede Region und jeden vergangenen Tag:
  * Ensemble-Anteil (ICON-CH2-EPS, 21 Member mit Code 95/96/99 im Flugfenster)
  * deterministischer weather_code derselben Region (Vergleichsmassstab)
gegen die Stationsmessung derselben Region und desselben Tages.

Wahrheit: MeteoSchweiz-Stundenwerte. Hilfsindikator "Station meldet >= 5 mm in
EINER Stunde". Dieser Indikator ist SCHWACH — offene Blitzdaten gibt es nicht,
und Starkregen entsteht auch ohne Gewitter. Die Zahlen zeigen eine Richtung,
sie beweisen nichts.

Die Zeitzuordnung wird nicht erneut bewiesen; das macht
scripts/validate_thunder_vs_stations.py (Minimum bei 0 h, Restabweichung
1.85 K). Beide Skripte nutzen dieselbe Lade-Funktion.

Usage:
    python scripts/calibrate_ensemble_threshold.py --past-days 30
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import convection as et
from fetch_weather import THUNDER_CODES, _api_get_with_retry
from source_area import get_all_regions
from spots import load_spots
from meteoschweiz_stations import (  # noqa: E402
    assign_stations_to_regions,
    load_hourly,
    load_stations,
)

THUNDER_PROXY_MM_H = 5.0
THRESHOLDS = [5, 10, 15, 19, 20, 25, 30, 40, 50, 60, 75]
# Unter so vielen auswertbaren Region-Tagen ist jede Schwellen-Empfehlung Zufall.
MIN_USABLE_DAYS = 200


def has_member_spread(hourly, var="weather_code"):
    """True, wenn die Member an mindestens einer Stunde auseinanderlaufen.

    Ohne Streuung liegt kein Ensemble vor, sondern eine einzige, 21-fach
    kopierte Reihe (so fuellt Open-Meteo die Vergangenheit). Solche Tage
    duerfen nicht in eine Kalibrierung eingehen — sie liefern still 0 %.
    """
    keys = et.member_keys(hourly, var)
    if len(keys) < 2:
        return set()
    times = hourly.get("time", [])
    days_with_spread = set()
    for i, t in enumerate(times):
        vals = {hourly[k][i] for k in keys
                if i < len(hourly[k]) and hourly[k][i] is not None}
        if len(vals) > 1:
            days_with_spread.add(t[:10])
    return days_with_spread


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--past-days", type=int, default=30)
    ap.add_argument("--max-km", type=float, default=12.0)
    args = ap.parse_args(argv)

    regions = get_all_regions()
    by_name_pts = {}
    for r in regions:
        pts = [tuple(p) for p in (r.get("reference_points") or [])]
        if pts:
            by_name_pts[r["region"]] = pts

    print(f"Ensemble holen: {len(by_name_pts)} Regionen, {args.past_days} Rueckblicktage")
    print("(freier Endpunkt, kleine Chunks — das dauert)")

    # Ensemble ueber den PRODUKTIVEN Codepfad, nur mit past_days erweitert.
    order, index = [], {}
    for pts in by_name_pts.values():
        for p in pts:
            k = (round(p[0], 4), round(p[1], 4))
            if k not in index:
                index[k] = len(order)
                order.append(p)

    raw = []
    n_chunks = (len(order) + et.ENSEMBLE_CHUNK - 1) // et.ENSEMBLE_CHUNK
    import time
    for ci, s in enumerate(range(0, len(order), et.ENSEMBLE_CHUNK)):
        ch = order[s:s + et.ENSEMBLE_CHUNK]
        params = {
            "latitude": ",".join(f"{p[0]:.4f}" for p in ch),
            "longitude": ",".join(f"{p[1]:.4f}" for p in ch),
            "models": config.ENSEMBLE_MODEL,
            "hourly": "weather_code",
            "forecast_days": 1,
            "past_days": args.past_days,
            "timezone": config.TIMEZONE,
        }
        resp = et._get_with_retry(params, label=f"{s}-{s + len(ch)}")
        data = resp.json()
        raw.extend(data if isinstance(data, list) else [data])
        print(f"  Chunk {ci + 1}/{n_chunks}", flush=True)
        if ci < n_chunks - 1:
            time.sleep(et.ENSEMBLE_DELAY)

    # Deterministischer Vergleichsmassstab (gleicher Zeitraum, gleiches Modell)
    det = []
    for s in range(0, len(order), 80):
        ch = order[s:s + 80]
        resp = _api_get_with_retry(config.API_URL, {
            "latitude": ",".join(f"{p[0]:.4f}" for p in ch),
            "longitude": ",".join(f"{p[1]:.4f}" for p in ch),
            "models": config.ENSEMBLE_MODEL,
            "hourly": "weather_code",
            "forecast_days": 1, "past_days": args.past_days,
            "timezone": config.TIMEZONE,
        }, 120, label=f"det{s}")
        d = resp.json()
        det.extend(d if isinstance(d, list) else [d])

    # --- Wahrheit ---
    stations = load_stations()
    spots = load_spots(config.CSV_PATH)
    mapping = assign_stations_to_regions(stations, spots, max_km=args.max_km)
    by_region = defaultdict(list)
    for a, m in mapping.items():
        by_region[m["region"]].append(a)

    truth, obs_days = set(), set()
    for rname, abbrs in by_region.items():
        peak = defaultdict(float)
        for a in abbrs:
            for key, rec in load_hourly(a).items():
                mm = rec.get("precip_mm")
                if mm is None:
                    continue
                obs_days.add((rname, key[:10]))
                peak[(rname, key[:10])] = max(peak[(rname, key[:10])], mm)
        for k, v in peak.items():
            if v >= THUNDER_PROXY_MM_H:
                truth.add(k)

    # --- Ensemble-Anteil + deterministisch je Region-Tag ---
    prob = {}
    det_flag = set()
    for rname, pts in by_name_pts.items():
        idxs = [index[(round(p[0], 4), round(p[1], 4))] for p in pts]
        hourlies = [raw[i]["hourly"] for i in idxs if i < len(raw)]
        if not hourlies:
            continue
        times = hourlies[0]["time"]
        merged = et.merge_points_per_member(hourlies, "weather_code")
        for day in sorted({t[:10] for t in times}):
            res = et.thunder_probability(merged, times, day)
            if res["probability_pct"] is not None:
                prob[(rname, day)] = res["probability_pct"]

        dser = [det[i]["hourly"] for i in idxs if i < len(det)]
        if dser:
            dt = dser[0]["time"]
            for i, t in enumerate(dt):
                hh = int(t[11:13])
                if not (config.FLIGHT_HOURS_START <= hh < config.FLIGHT_HOURS_END):
                    continue
                for s in dser:
                    arr = s.get("weather_code", [])
                    if i < len(arr) and arr[i] is not None and int(arr[i]) in THUNDER_CODES:
                        det_flag.add((rname, t[:10]))
                        break

    # --- Tage ohne Member-Streuung aussortieren (siehe Modul-Kopf) ---
    spread_days = set()
    for h in raw:
        spread_days |= has_member_spread(h.get("hourly") or {})
    all_ens_days = {d for (_r, d) in prob}
    ohne = sorted(all_ens_days - spread_days)
    print()
    print(f"Ensemble-Tage gesamt: {len(all_ens_days)} | mit echter Member-Streuung: "
          f"{len(all_ens_days & spread_days)}")
    if ohne:
        print(f"  VERWORFEN (alle Member identisch, kein Ensemble): {len(ohne)} Tage "
              f"{ohne[0]} .. {ohne[-1]}")

    prob = {k: v for k, v in prob.items() if k[1] in spread_days}
    truth &= obs_days & {(r, d) for (r, d) in truth if d in spread_days}
    scored = {k: v for k, v in prob.items() if k in obs_days}

    if len(scored) < MIN_USABLE_DAYS:
        print()
        print(f"ABBRUCH: nur {len(scored)} auswertbare Region-Tage "
              f"(mindestens {MIN_USABLE_DAYS} noetig).")
        print("Rueckwirkend ist diese Kalibrierung nicht moeglich — Open-Meteo liefert")
        print("im Ensemble-Archiv keine echten Member (siehe Modul-Kopf). Der Weg ist")
        print("VORWAERTS sammeln: snapshot_weather.py archiviert thunder_ensemble")
        print("taeglich; in einigen Wochen ist genug beisammen.")
        return 2

    print()
    print(f"Bewertete Region-Tage: {len(scored)} | mit >= {THUNDER_PROXY_MM_H} mm/h gemessen: {len(truth)}")
    print()
    print(f"{'Schwelle':>9} {'markiert':>9} {'Treffer':>8} {'Verpasst':>9} {'Fehlal.':>8} {'Quote':>7} {'Praez.':>7}")
    for th in THRESHOLDS:
        flagged = {k for k, v in scored.items() if v >= th}
        hit = len(flagged & truth)
        miss = len(truth - flagged)
        false = len(flagged - truth)
        quote = 100 * hit / len(truth) if truth else 0
        praez = 100 * hit / len(flagged) if flagged else 0
        mark = "  <== aktuell" if th == config.ENSEMBLE_THUNDER_MENTION_PCT else ""
        print(f"{th:8}% {len(flagged):9} {hit:8} {miss:9} {false:8} "
              f"{quote:6.1f}% {praez:6.1f}%{mark}")

    dflag = det_flag & obs_days
    hit = len(dflag & truth)
    print(f"{'determ.':>9} {len(dflag):9} {hit:8} {len(truth - dflag):9} "
          f"{len(dflag - truth):8} {100 * hit / len(truth) if truth else 0:6.1f}% "
          f"{100 * hit / len(dflag) if dflag else 0:6.1f}%  <== heutiges Gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
