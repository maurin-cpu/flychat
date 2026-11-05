# -*- coding: utf-8 -*-
"""Einigkeit der Windrichtung: je Punkt oder je Region (eine Stimme pro Region)?

Wie kachel_schwellen.py (dieselben Messpunkte, Cache, Wahrheit), aber die Einigkeit
wird zusätzlich über Regionen gerechnet:
  1. je Region: Median der u- und v-Komponenten ihrer Punkte (ein Ausreisser treibt nichts)
  2. Region hat Wind, wenn die Median-Stärke >= 10 km/h
  3. Einigkeit = Länge des Mittels der Einheitsvektoren dieser Regionen (jede Region gleich viel)
Vergleich: Pfeilfehler (> 45°) an Tagen über / unter der Schwelle, getrennt nach Halbjahr.
Schreibt einigkeit_regionen.json.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))
import kachel_schwellen as ks  # noqa: E402
import richtung_vs_staerke as rv  # noqa: E402


def spot_regions() -> list[str]:
    """Region je Punkt, in derselben Reihenfolge und Auswahl wie ks.spots()."""
    import config
    with open(config.CSV_PATH, encoding="utf-8-sig") as f:
        rows = sorted(csv.DictReader(f), key=lambda r: (r.get("analyse_region") or "", r["site_name"]))
    seen, out = set(), []
    for r in rows[::ks.STEP]:
        key = (round(float(r["latitude"]), 2), round(float(r["longitude"]), 2))
        if key not in seen:
            seen.add(key)
            out.append(r.get("analyse_region") or "?")
    return out


def uv(s, d):
    return s * math.sin(math.radians(d)), s * math.cos(math.radians(d))


def region_stats(samples, regions):
    """-> (Einigkeit über Regionen, Richtung, Anzahl Regionen mit Wind)."""
    by = {}
    for (s, d), reg in zip(samples, regions):
        by.setdefault(reg, []).append(uv(s, d))
    units = []
    for reg, xs in by.items():
        if len(xs) < 2:
            continue
        u = statistics.median(x[0] for x in xs)
        v = statistics.median(x[1] for x in xs)
        sp = math.hypot(u, v)
        if sp >= ks.WIND_KMH:
            units.append((u / sp, v / sp))
    if len(units) < 2:
        return None
    u = sum(x[0] for x in units) / len(units)
    v = sum(x[1] for x in units) / len(units)
    return math.hypot(u, v), math.degrees(math.atan2(u, v)) % 360, len(units)


def spot_samples_ordered(pts):
    """Wie ks.spot_noon, aber Reihenfolge der Punkte erhalten (für die Region-Zuordnung)."""
    by_day = {}
    for i in range(0, len(pts), ks.CHUNK):
        part = pts[i:i + ks.CHUNK]
        name = f"om_spots_{rv.MODEL}_{ks.VON}_{ks.BIS}_{i}_{len(part)}.json"
        data = json.loads((rv.CACHE / name).read_bytes())
        for k, loc in enumerate(data if isinstance(data, list) else [data]):
            h = loc["hourly"]
            for j, t in enumerate(h["time"]):
                if t.endswith("T12:00"):
                    by_day.setdefault(t[:10], [None] * len(pts))[i + k] = (
                        h["wind_speed_700hPa"][j], h["wind_direction_700hPa"][j])
    return by_day


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pts, regs = ks.spots(), spot_regions()
    assert len(pts) == len(regs)
    ks.spot_noon(pts)                         # sorgt nur dafür, dass der Cache vollständig ist
    model = spot_samples_ordered(pts)
    obs = {a: rv.station_obs(a) for a in rv.STATIONS}
    rows = []
    for d, arr in sorted(model.items()):
        pairs = [(x, r) for x, r in zip(arr, regs) if x and x[0] is not None and x[1] is not None]
        if len(pairs) < 0.9 * len(pts):
            continue
        t = ks.truth(obs, dt.date.fromisoformat(d))
        if not t or t["dir"] is None:
            continue
        samples = [x for x, _ in pairs]
        f = ks.features(samples)
        if f["share_wind"] < 0.2:             # "Kaum Wind" — hier nicht Thema
            continue
        rs = region_stats(samples, [r for _, r in pairs])
        if not rs:
            continue
        rows.append({"d": d, "R_punkt": f["R"], "dir_punkt": f["dir"], "R_region": rs[0],
                     "dir_region": rs[1], "n_reg": rs[2], "t_dir": t["dir"]})

    def rate(xs, key):
        e = [rv.ang(x[key], x["t_dir"]) for x in xs]
        return (len(e), round(100 * sum(v > 45 for v in e) / len(e)) if e else None)

    out = {"tage": len(rows), "regionen_im_mittel": round(statistics.mean(r["n_reg"] for r in rows), 1),
           "pfeil_punkt_alle": rate(rows, "dir_punkt"), "pfeil_region_alle": rate(rows, "dir_region"),
           "schwellen": []}
    for kind in ("punkt", "region"):
        for Y in (0.6, 0.7, 0.8, 0.85, 0.9, 0.95):
            row = {"art": kind, "Y": Y}
            for half, sel in (("alle", lambda r: True), ("jan_jun", lambda r: r["d"] < "2026-07-01"),
                              ("jul_nov", lambda r: r["d"] >= "2026-07-01")):
                xs = [r for r in rows if sel(r)]
                lo = [r for r in xs if r[f"R_{kind}"] < Y]
                hi = [r for r in xs if r[f"R_{kind}"] >= Y]
                row[half] = {"unter": rate(lo, f"dir_{kind}"), "ueber": rate(hi, f"dir_{kind}")}
            out["schwellen"].append(row)
    (HERE / "einigkeit_regionen.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Tage {out['tage']}, Regionen mit Wind im Mittel {out['regionen_im_mittel']}")
    print("Pfeil daneben, alle Tage: Punkt", out["pfeil_punkt_alle"], "Region", out["pfeil_region_alle"])
    print("art     Y    | alle: unter (n,%) über (n,%) | jan-jun unter | jul-nov unter | jul-nov über")
    for r in out["schwellen"]:
        print(f"{r['art']:7s} {r['Y']:.2f} | {r['alle']['unter']} {r['alle']['ueber']} | "
              f"{r['jan_jun']['unter']} {r['jan_jun']['ueber']} | {r['jul_nov']['unter']} {r['jul_nov']['ueber']}")


if __name__ == "__main__":
    main()
