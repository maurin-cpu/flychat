# -*- coding: utf-8 -*-
"""Backtest der fünf Kachel-Anzeigen (Stand 05.11.2026), je Region gerechnet.

Reihenfolge der Regeln (die erste, die greift, gilt):
  1. schwach     alle Regionen im Flugfenster 06-17 Uhr unter 15 km/h (= Pille "schwacher Wind")
  2. wechselt+   zur Kachelzeit < 20 % der Regionen mit Wind (>= 10 km/h)
                 -> "Richtung wechselt · stellenweise stärker"
  3. wechselt    Einigkeit der Regionen mit Wind < 0,85
  4. teils       >= 30 % der Regionen unter 10 km/h -> "↗ SW · teils schwach"
  5. pfeil       sonst
Kachelzeit = Ballon-Termin 12 UTC (13/14 Uhr Ortszeit), damit die Ballone vergleichbar sind.

Wahrheit:
  Richtung        Ballone (Payerne, Stuttgart, München, Novara), Vektor-Mittel der Ballone >= 10 km/h
  keine Richtung  Ballone: weniger als 2 mit >= 10 km/h ODER deren Einigkeit < 0,85
  schwach         alle Ballone < 15 km/h
  teils schwach   >= 30 % der 15 Gipfel (kaum_wind.STATIONS_B) messen mittags < 10 km/h
Schreibt kachel_backtest.json.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))
import einigkeit_regionen as er  # noqa: E402
import kachel_schwellen as ks  # noqa: E402
import kaum_wind as kw  # noqa: E402
import radiosonde as rs  # noqa: E402
import richtung_vs_staerke as rv  # noqa: E402


def day_peak_by_region(pts, regs, day):
    peak = {}
    for h in range(6, 17):
        t_local = dt.datetime.combine(day, dt.time(h)).replace(tzinfo=rs.TZ)
        t_utc = t_local.astimezone(dt.timezone.utc).replace(tzinfo=None)
        for reg, (u, v, s) in rs.region_vectors(rs.spots_at(pts, regs, t_utc)).items():
            peak[reg] = max(peak.get(reg, 0.0), s)
    return peak


def unit_mean(vecs):
    us = [(u / s, v / s) for u, v, s in vecs if s > 0]
    uu, vv = sum(a for a, _ in us) / len(us), sum(b for _, b in us) / len(us)
    return math.hypot(uu, vv), math.degrees(math.atan2(uu, vv)) % 360


def label(regvec, peak):
    if peak and max(peak.values()) < 15:
        return "schwach", None
    n = len(regvec)
    windy = [r for r in regvec.values() if r[2] >= ks.WIND_KMH]
    if not n or len(windy) / n < 0.2:
        return "wechselt+", None
    R, d = unit_mean(windy)
    if R < 0.85:
        return "wechselt", d
    return ("teils" if 1 - len(windy) / n >= 0.3 else "pfeil"), d


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sondes = {sid: rs.igra_700(sid) for sid in rs.SONDES}
    summits = {a: rv.station_obs(a) for a in kw.STATIONS_B}
    pts, regs = ks.spots(), er.spot_regions()
    ks.spot_noon(pts)
    rows = []
    for t in sorted(set().union(*[set(o) for o in sondes.values()])):
        if not (ks.VON <= t.date().isoformat() <= ks.BIS):
            continue
        obs = [o[t] for o in sondes.values() if t in o]
        if len(obs) < 3:
            continue
        pairs = rs.spots_at(pts, regs, t)
        if sum(1 for x, _ in pairs if x) < 0.9 * len(pts):
            continue
        lab, d = label(rs.region_vectors(pairs), day_peak_by_region(pts, regs, t.date()))
        windy = [o for o in obs if o[0] >= ks.WIND_KMH]
        if len(windy) >= 2:
            uvs = [(*er.uv(*o), o[0]) for o in windy]
            R_t, d_t = unit_mean(uvs)
        else:
            R_t, d_t = 0.0, None
        sm = [v for v in (rv.obs_noon(summits[a], t.date()) for a in kw.STATIONS_B) if v]
        rows.append({"t": t.isoformat(), "label": lab, "dir": d, "t_dir": d_t,
                     "t_keine_richtung": len(windy) < 2 or R_t < 0.85,
                     "t_schwach": all(o[0] < 15 for o in obs),
                     "t_staerker": max(o[0] for o in obs) >= 15,
                     "t_teils": (sum(v[0] < 10 for v in sm) / len(sm) >= 0.3) if len(sm) >= 12 else None})

    def pct(xs):
        xs = [x for x in xs if x is not None]
        return (len(xs), round(100 * sum(xs) / len(xs)) if xs else None)

    res = {"termine": len(rows), "labels": {}}
    for lab in ("pfeil", "teils", "wechselt", "wechselt+", "schwach"):
        sel = [r for r in rows if r["label"] == lab]
        e = {"tage": len(sel), "anteil_pct": round(100 * len(sel) / len(rows))}
        if lab in ("pfeil", "teils"):
            e["richtung_stimmt"] = pct([rv.ang(r["dir"], r["t_dir"]) <= 45 for r in sel if r["t_dir"] is not None])
        if lab == "teils":
            e["teils_schwach_stimmt_gipfel"] = pct([r["t_teils"] for r in sel])
        if lab == "pfeil":
            e["nicht_teils_stimmt_gipfel"] = pct([None if r["t_teils"] is None else not r["t_teils"] for r in sel])
        if lab in ("wechselt", "wechselt+"):
            e["keine_klare_richtung_ballone"] = pct([r["t_keine_richtung"] for r in sel])
            e["pfeil_waere_falsch"] = pct([rv.ang(r["dir"], r["t_dir"]) > 45 for r in sel
                                          if r["dir"] is not None and r["t_dir"] is not None])
        if lab == "wechselt+":
            e["stellenweise_staerker_ballone"] = pct([r["t_staerker"] for r in sel])
        if lab == "schwach":
            e["schwach_stimmt_ballone"] = pct([r["t_schwach"] for r in sel])
        res["labels"][lab] = e
    (HERE / "kachel_backtest.json").write_text(json.dumps({**res, "rows": rows}, ensure_ascii=False, indent=1),
                                               encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
