# -*- coding: utf-8 -*-
"""Synoptik-Karte: stimmen ihre Windpfeile (700 hPa) an den Ballon-Orten?

Nachbau der Karte (engine/synoptic_grid.py + static/js/synoptic-wind.js): ECMWF IFS 0.25°
auf dem groben Raster (config.SYNOPTIC_GRID_*), u/v bilinear zwischen den vier Nachbarknoten
interpoliert. Vergleich mit den Radiosonden (radiosonde.SONDES) um 12 UTC; zusätzlich der
Kartenwert "12:00 Ortszeit" (das, was die Karte als Mittag zeigt) und ECMWF direkt am Ballon-Ort.
Schreibt karte_vs_ballon.json.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
import config  # noqa: E402
import radiosonde as rs  # noqa: E402
import richtung_vs_staerke as rv  # noqa: E402


def nodes_around(lat, lon):
    j0 = math.floor((config.SYNOPTIC_GRID_LAT_MAX - lat) / config.SYNOPTIC_GRID_DLAT)
    i0 = math.floor((lon - config.SYNOPTIC_GRID_LON_MIN) / config.SYNOPTIC_GRID_DLON)
    la1 = config.SYNOPTIC_GRID_LAT_MAX - j0 * config.SYNOPTIC_GRID_DLAT      # nördlich
    la2 = la1 - config.SYNOPTIC_GRID_DLAT
    lo1 = config.SYNOPTIC_GRID_LON_MIN + i0 * config.SYNOPTIC_GRID_DLON      # westlich
    lo2 = lo1 + config.SYNOPTIC_GRID_DLON
    fy = (la1 - lat) / config.SYNOPTIC_GRID_DLAT
    fx = (lon - lo1) / config.SYNOPTIC_GRID_DLON
    return [(la1, lo1), (la1, lo2), (la2, lo1), (la2, lo2)], fx, fy


def uv(s, d):
    return -s * math.sin(math.radians(d)), -s * math.cos(math.radians(d))   # wohin (wie die Karte)


def from_uv(u, v):
    return math.hypot(u, v), math.degrees(math.atan2(-u, -v)) % 360


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sondes = {sid: rs.igra_700(sid) for sid in rs.SONDES}
    geo = {sid: nodes_around(*rs.SONDES[sid][1:]) for sid in rs.SONDES}
    nodes = sorted({n for g in geo.values() for n in g[0]})
    series = dict(zip(nodes, rs.model_points(nodes, "ecmwf_ifs025", "kartenknoten")))
    direct = dict(zip(rs.SONDES, rs.model_points([rs.SONDES[s][1:] for s in rs.SONDES], "ecmwf_ifs025", "sonden")))

    def karte(sid, t):
        (n11, n12, n21, n22), fx, fy = geo[sid]
        vals = [series[n].get(t) for n in (n11, n12, n21, n22)]
        if any(v is None for v in vals):
            return None
        (a, b), (c, d), (e, f), (g, h) = [uv(*v) for v in vals]
        top = ((1 - fx) * a + fx * c, (1 - fx) * b + fx * d)
        bot = ((1 - fx) * e + fx * g, (1 - fx) * f + fx * h)
        return from_uv((1 - fy) * top[0] + fy * bot[0], (1 - fy) * top[1] + fy * bot[1])

    rows = {"karte_12utc": [], "karte_12_ortszeit": [], "ecmwf_am_ort": []}
    per_sonde = {}
    for sid, obs in sondes.items():
        for t, (bs, bd) in obs.items():
            if not (rs.ks.VON <= t.date().isoformat() <= rs.ks.BIS) or bs < 3.6:
                continue
            loc12 = dt.datetime.combine(t.date(), dt.time(12)).replace(tzinfo=rs.TZ)
            t_loc = loc12.astimezone(dt.timezone.utc).replace(tzinfo=None)
            for key, m in (("karte_12utc", karte(sid, t)), ("karte_12_ortszeit", karte(sid, t_loc)),
                           ("ecmwf_am_ort", direct[sid].get(t))):
                if m:
                    rows[key].append((m[0], rv.ang(m[1], bd)))
                    if key == "karte_12utc":
                        per_sonde.setdefault(rs.SONDES[sid][0], []).append(rv.ang(m[1], bd))
    res = {k: rv.bin_stats(v) for k, v in rows.items()}
    res["gesamt_daneben_pct"] = {k: round(100 * sum(e > 45 for _, e in v) / len(v)) for k, v in rows.items()}
    res["karte_je_ballon_daneben_pct"] = {k: round(100 * sum(e > 45 for e in v) / len(v)) for k, v in per_sonde.items()}
    (HERE / "karte_vs_ballon.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Gesamt daneben (>45°):", res["gesamt_daneben_pct"])
    print("Karte je Ballon:", res["karte_je_ballon_daneben_pct"])
    for k in ("karte_12utc", "ecmwf_am_ort"):
        print(f"\n{k}\n" + rv._table(res[k]))


if __name__ == "__main__":
    main()
