"""Zieht das Blitzpotenzial (LPI) aus ICON-D2 rueckwirkend und legt es ab.

WARUM DIESES SKRIPT
-------------------
Der LPI (lightning_potential, J/kg) ist der einzige Modellwert, der direkt die
Ladungstrennung in der Wolke beschreibt statt nur die Zutaten (CAPE/CIN/LI).
Laut Literatur trifft er den ZEITPUNKT gut (~70 % der Faelle innerhalb 45 min
am beobachteten Blitzbeginn), den ORT dagegen schlecht (brauchbar erst ab
~220 km Skala, ASR 19, 29). Deshalb: NIE am Punkt lesen, immer ueber eine
Flaeche aggregieren.

DRINGLICHKEIT
-------------
Open-Meteo haelt `past_days` maximal 92 Tage vor — und LPI faktisch noch
kuerzer. Gemessen am 2026-08-01 begannen die Werte erst am 04.06.; der Mai war
bereits weg. Das Fenster wandert taeglich weiter. Was hier nicht gezogen wird,
ist unwiederbringlich verloren. Der eigentliche Fix ist deshalb ein taeglicher
Mitschnitt im Scheduler, nicht dieses einmalige Skript.

MODELL
------
LPI liefert bei Open-Meteo NUR icon_d2 (2 km, DWD) — nicht die Schweizer
ICON-CH-Modelle, die wir sonst nutzen. Das ist ein anderes Modell als unsere
Produktivkette; beim Vergleich beachten.

Usage:
    python scripts/fetch_lpi_archive.py                 # alle Spots, 92 Tage
    python scripts/fetch_lpi_archive.py --past-days 60
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config  # noqa: E402
from fetch_weather import _api_get_with_retry  # noqa: E402
from spots import load_spots  # noqa: E402

API_URL = "https://api.open-meteo.com/v1/dwd-icon"
MODEL = "icon_d2"
HOURLY = "lightning_potential,cape,convective_inhibition,weather_code"
CHUNK = 60
DELAY_S = 2.0
OUT_DIR = os.path.join(ROOT, "data", "lpi_archive")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--past-days", type=int, default=92)
    ap.add_argument("--out", default=OUT_DIR)
    args = ap.parse_args(argv)

    spots = load_spots()
    pts = [(s["name"], float(s["latitude"]), float(s["longitude"]),
            s.get("analyse_region") or s.get("region")) for s in spots]
    print(f"[LPI] {len(pts)} Spots, past_days={args.past_days}, Modell {MODEL}")

    os.makedirs(args.out, exist_ok=True)
    per_spot = {}
    for start in range(0, len(pts), CHUNK):
        chunk = pts[start:start + CHUNK]
        params = {
            "latitude": ",".join(f"{p[1]:.4f}" for p in chunk),
            "longitude": ",".join(f"{p[2]:.4f}" for p in chunk),
            "models": MODEL,
            "hourly": HOURLY,
            "past_days": args.past_days,
            "forecast_days": 1,
            "timezone": config.TIMEZONE,
        }
        resp = _api_get_with_retry(API_URL, params, 180,
                                   label=f"lpi[{start}:{start + len(chunk)}]")
        data = resp.json()
        data = data if isinstance(data, list) else [data]
        if len(data) != len(chunk):
            print(f"[LPI] WARNUNG: {len(data)} Antworten fuer {len(chunk)} Punkte")
        for (name, lat, lon, reg), block in zip(chunk, data):
            h = block.get("hourly") or {}
            per_spot[name] = {
                "latitude": lat, "longitude": lon, "region": reg,
                "time": h.get("time") or [],
                "lightning_potential": h.get("lightning_potential") or [],
                "cape": h.get("cape") or [],
                "convective_inhibition": h.get("convective_inhibition") or [],
                "weather_code": h.get("weather_code") or [],
            }
        done = min(start + CHUNK, len(pts))
        print(f"[LPI] {done}/{len(pts)} Spots geholt")
        time.sleep(DELAY_S)

    # --- Kennzahlen, damit der Lauf selbst schon eine Aussage macht ---
    times = next((v["time"] for v in per_spot.values() if v["time"]), [])
    by_hour_max = {}
    for v in per_spot.values():
        for t, x in zip(v["time"], v["lightning_potential"]):
            if x is None:
                continue
            if x > by_hour_max.get(t, -1):
                by_hour_max[t] = x
    pos_hours = {t for t, m in by_hour_max.items() if m > 0}
    days = defaultdict(float)
    for t, m in by_hour_max.items():
        days[t[:10]] = max(days[t[:10]], m)
    pos_days = sorted(d for d, m in days.items() if m > 0)

    first_val = min((t for t in by_hour_max), default=None)
    out = {
        "_meta": {
            "model": MODEL,
            "past_days": args.past_days,
            "n_spots": len(per_spot),
            "hours_requested": len(times),
            "hours_with_any_value": len(by_hour_max),
            "first_hour_with_value": first_val,
            "hours_lpi_positive": len(pos_hours),
            "days_lpi_positive": len(pos_days),
            "days_covered": len(days),
        },
        "spots": per_spot,
    }
    path = os.path.join(args.out, "lpi_icon_d2.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh)

    print("\n=== ERGEBNIS ===")
    print(f"Datei                : {path} "
          f"({os.path.getsize(path) / 1e6:.1f} MB)")
    print(f"Stunden angefragt    : {len(times)}")
    print(f"Stunden mit Werten   : {len(by_hour_max)} "
          f"(ab {first_val})")
    print(f"Stunden mit LPI > 0  : {len(pos_hours)}")
    print(f"Tage mit LPI > 0     : {len(pos_days)} von {len(days)} Tagen")
    if pos_days:
        print(f"Erster/letzter Tag   : {pos_days[0]} .. {pos_days[-1]}")
    top = sorted(by_hour_max.items(), key=lambda kv: -kv[1])[:8]
    print("Top-Stunden          : "
          + ", ".join(f"{t} {m:.0f}" for t, m in top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
