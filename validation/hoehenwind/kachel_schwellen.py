# -*- coding: utf-8 -*-
"""Schwellen der Tageskachel (Höhenwind 700 hPa, 12:00) validieren.

Regeln der Kachel (Vorschlag 05.11.2026), gerechnet über die Messpunkte (Spots):
  1. Anteil Punkte mit Wind (>= WIND_KMH) < X        -> "Kaum Wind · Richtung wechselt"
  2. Einigkeit R der Punkte mit Wind < Y             -> "Richtung wechselt"
  3. Anteil schwacher Punkte >= Z                    -> "↗ SW · teils schwach"
  4. sonst                                           -> "↗ SW"
Richtung = Vektor-Mittel NUR der Punkte mit Wind.

Wahrheit: SwissMetNet-Gipfelstationen (richtung_vs_staerke.STATIONS), gemessen 11:30-12:30.
  ruhig        = höchstens 1 von 6 Stationen misst >= WIND_KMH
  teils schwach= mindestens 2 von 6 Stationen messen < WIND_KMH
  Richtung     = Vektor-Mittel der Stationen, die >= WIND_KMH messen; Pfeil richtig bei <= 45°

Prognose: Open-Meteo historical-forecast-api (frei), icon_d2, Stichprobe jedes 3. Spots
aus config.CSV_PATH (Kontingent der freien API). Schreibt SCHWELLEN_REPORT.md + schwellen.json.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
import sys
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
import richtung_vs_staerke as rv  # noqa: E402

WIND_KMH = 10
VON, BIS = "2026-01-01", "2026-11-04"
CHUNK = 25
STEP = 3


def spots() -> list[tuple[float, float]]:
    import config
    with open(config.CSV_PATH, encoding="utf-8-sig") as f:
        rows = sorted(csv.DictReader(f), key=lambda r: (r.get("analyse_region") or "", r["site_name"]))
    seen, out = set(), []
    for r in rows[::STEP]:
        key = (round(float(r["latitude"]), 2), round(float(r["longitude"]), 2))
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def spot_noon(pts) -> dict:
    """{date: [(kmh, dir), ...]} 700 hPa um 12:00 Ortszeit an allen Punkten."""
    by_day: dict = {}
    for i in range(0, len(pts), CHUNK):
        part = pts[i:i + CHUNK]
        q = urllib.parse.urlencode({
            "latitude": ",".join(str(p[0]) for p in part), "longitude": ",".join(str(p[1]) for p in part),
            "models": rv.MODEL, "timezone": "Europe/Zurich", "start_date": VON, "end_date": BIS,
            "hourly": "wind_speed_700hPa,wind_direction_700hPa"})
        name = f"om_spots_{rv.MODEL}_{VON}_{BIS}_{i}_{len(part)}.json"
        cached = (rv.CACHE / name).exists()
        url = f"https://historical-forecast-api.open-meteo.com/v1/forecast?{q}"
        for attempt in range(3):
            try:
                data = json.loads(rv.fetch(url, name))
                break
            except ValueError:          # abgeschnittene Antwort: Cache weg, nochmal
                (rv.CACHE / name).unlink(missing_ok=True)
                time.sleep(10)
        else:
            raise RuntimeError(f"Open-Meteo liefert für Punkte ab {i} keine vollständige Antwort")
        if not cached:
            time.sleep(2)
        for loc in (data if isinstance(data, list) else [data]):
            h = loc["hourly"]
            for j, t in enumerate(h["time"]):
                if t.endswith("T12:00"):
                    s, d = h["wind_speed_700hPa"][j], h["wind_direction_700hPa"][j]
                    if s is not None and d is not None:
                        by_day.setdefault(t[:10], []).append((s, d))
        print(f"  Punkte {i + len(part)}/{len(pts)}", flush=True)
    return by_day


def truth(obs, day):
    vals = [rv.obs_noon(obs[a], day) for a in rv.STATIONS]
    vals = [v for v in vals if v]
    if len(vals) < 5:
        return None
    windy = [v for v in vals if v[0] >= WIND_KMH]
    return {"ruhig": len(windy) <= 1, "teils_schwach": len(vals) - len(windy) >= 2,
            "dir": rv.vec_mean([(v[0], v[1]) for v in windy])[1] if len(windy) >= 2 else None}


def features(samples):
    windy = [x for x in samples if x[0] >= WIND_KMH]
    share_wind = len(windy) / len(samples)
    vm = rv.vec_mean(windy) if windy else None
    return {"share_wind": share_wind, "R": vm[2] if vm else 0.0, "dir": vm[1] if vm else None}


def label(f, X, Y, Z):
    if f["share_wind"] < X:
        return "kaum_wind"
    if f["R"] < Y:
        return "wechselt"
    return "pfeil_teils" if (1 - f["share_wind"]) >= Z else "pfeil"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pts = spots()
    print(f"{len(pts)} Messpunkte", flush=True)
    model = spot_noon(pts)
    obs = {a: rv.station_obs(a) for a in rv.STATIONS}
    days = []
    for d, samples in sorted(model.items()):
        t = truth(obs, dt.date.fromisoformat(d))
        if t and len(samples) >= 0.9 * len(pts):
            days.append((d, features(samples), t))
    n = len(days)

    # X: "Kaum Wind" gegen "ruhig gemessen"
    x_tab = []
    for X in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6):
        shown = [t["ruhig"] for _, f, t in days if f["share_wind"] < X]
        calm_all = sum(t["ruhig"] for _, _, t in days)
        hit = sum(shown)
        x_tab.append({"X": X, "gezeigt": len(shown), "davon_ruhig_pct": round(100 * hit / len(shown)) if shown else None,
                      "ruhige_erkannt_pct": round(100 * hit / calm_all) if calm_all else None})

    # Y: Pfeilfehler nach Einigkeit R (nur Tage mit Wahrheitsrichtung, Anteil Wind >= 0.2)
    y_rows = [(f["R"], rv.ang(f["dir"], t["dir"])) for _, f, t in days
              if f["dir"] is not None and t["dir"] is not None and f["share_wind"] >= 0.2]
    y_tab = []
    for lo, hi in ((0, .5), (.5, .6), (.6, .7), (.7, .8), (.8, .9), (.9, 1.01)):
        e = [x for r, x in y_rows if lo <= r < hi]
        if e:
            y_tab.append({"R": f"{lo:.1f}–{min(hi, 1):.1f}", "n": len(e),
                          "daneben_pct": round(100 * sum(x > 45 for x in e) / len(e))})

    # Z: "teils schwach" gegen ">= 2 Stationen schwach gemessen" (nur Tage mit Pfeil)
    z_tab = []
    for Z in (0.2, 0.3, 0.4, 0.5, 0.6):
        rows = [((1 - f["share_wind"]) >= Z, t["teils_schwach"]) for _, f, t in days if f["share_wind"] >= 0.2]
        tp = sum(a and b for a, b in rows); fp = sum(a and not b for a, b in rows)
        fn = sum(b and not a for a, b in rows); tn = sum(not a and not b for a, b in rows)
        z_tab.append({"Z": Z, "treffer_pct": round(100 * (tp + tn) / len(rows)),
                      "gezeigt_davon_richtig_pct": round(100 * tp / (tp + fp)) if tp + fp else None,
                      "schwache_erkannt_pct": round(100 * tp / (tp + fn)) if tp + fn else None})

    res = {"messpunkte": len(pts), "tage": n, "wind_kmh": WIND_KMH, "X": x_tab, "Y": y_tab, "Z": z_tab,
           "days": [{"d": d, **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in f.items()},
                     "t_ruhig": t["ruhig"], "t_teils": t["teils_schwach"], "t_dir": t["dir"]} for d, f, t in days]}
    (HERE / "schwellen.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("messpunkte", "tage", "X", "Y", "Z")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
