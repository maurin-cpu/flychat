# -*- coding: utf-8 -*-
"""Kachel-Labels gegen Wetterballone (Radiosonden, 700 hPa) statt Gipfelstationen.

Gipfel messen bei schwacher Grossströmung mittags vor allem Hangwind/Thermik; der
Ballon misst die freie Luft auf 700 hPa — genau das, was die Kachel zeigt.

Wahrheit: IGRA2 (NOAA NCEI, data-y2d), 12-UTC-Aufstiege (Payerne auch 11 UTC):
  Payerne (06610), Stuttgart (10739), München (10868), Novara-Cameri (16064).
  Innsbruck steigt nur 03 UTC auf — nicht brauchbar.
Prognose: ICON-D2 an den Spots (Cache aus kachel_schwellen.py), Stunde = Aufstiegszeit.
Zweites Modell: ECMWF IFS 0.25° je Region (ein Punkt pro Region = Mittel ihrer Spots).

Teil 1 (Punkt): ICON-D2 / ECMWF an den Ballon-Orten gegen den Ballon, nach Stärke.
Teil 2 (Kachel): die vier Labels (je Region) gegen die Ballone.
Teil 3 (Modelle uneinig): Pfeilfehler, wenn ICON-D2 und ECMWF > 45° auseinander liegen.
Schreibt radiosonde.json + RADIOSONDE_REPORT.md.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import statistics
import sys
import time
import urllib.parse
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))
import einigkeit_regionen as er  # noqa: E402
import kachel_schwellen as ks  # noqa: E402
import richtung_vs_staerke as rv  # noqa: E402

IGRA = "https://www.ncei.noaa.gov/data/integrated-global-radiosonde-archive/access/data-y2d/{id}-data-beg2026.txt.zip"
SONDES = {"SZM00006610": ("Payerne", 46.81, 6.94), "GMM00010739": ("Stuttgart", 48.83, 9.20),
          "GMM00010868": ("München", 48.24, 11.55), "ITM00016064": ("Novara-Cameri", 45.53, 8.67)}
TZ = ZoneInfo("Europe/Zurich")
X, Y, Z = 0.2, 0.85, 0.3          # Kaum Wind / Richtung wechselt / teils schwach (je Region)


def igra_700(sid: str) -> dict:
    """{datetime_utc (Stunde): (kmh, dir)} am 700-hPa-Standardniveau."""
    import io
    import zipfile
    raw = rv.fetch(IGRA.format(id=sid), f"igra_{sid}.zip")
    txt = zipfile.ZipFile(io.BytesIO(raw)).read(f"{sid}-data.txt").decode("ascii", "replace")
    out, cur = {}, None
    for ln in txt.splitlines():
        if ln.startswith("#"):
            y, m, d, h = int(ln[13:17]), int(ln[18:20]), int(ln[21:23]), int(ln[24:26])
            cur = dt.datetime(y, m, d, h) if h in (11, 12) else None
            continue
        if cur is None or ln[9:15].strip() != "70000":
            continue
        wdir, wspd = int(ln[40:45]), int(ln[46:51])
        if wdir >= 0 and wspd >= 0:
            out[cur] = (wspd / 10 * 3.6, float(wdir))
    return out


def model_points(points, model, name):
    """Stündliche 700-hPa-Werte (UTC) an Punkten: [{datetime_utc: (kmh, dir)}]."""
    q = urllib.parse.urlencode({
        "latitude": ",".join(f"{p[0]:.3f}" for p in points), "longitude": ",".join(f"{p[1]:.3f}" for p in points),
        "models": model, "timezone": "UTC", "start_date": ks.VON, "end_date": ks.BIS,
        "hourly": "wind_speed_700hPa,wind_direction_700hPa"})
    fname = f"om_{name}_{model}_{ks.VON}_{ks.BIS}.json"
    fresh = not (rv.CACHE / fname).exists()
    data = json.loads(rv.fetch(f"https://historical-forecast-api.open-meteo.com/v1/forecast?{q}", fname))
    if fresh:
        time.sleep(2)
    out = []
    for loc in (data if isinstance(data, list) else [data]):
        h, series = loc["hourly"], {}
        for j, t in enumerate(h["time"]):
            s, d = h["wind_speed_700hPa"][j], h["wind_direction_700hPa"][j]
            if s is not None and d is not None:
                series[dt.datetime.fromisoformat(t)] = (s, d)
        out.append(series)
    return out


def spots_at(pts, regs, when_utc):
    """ICON-D2-Spotwerte (Cache, Ortszeit) zur UTC-Stunde when_utc."""
    loc = when_utc.replace(tzinfo=dt.timezone.utc).astimezone(TZ).replace(tzinfo=None)
    key = loc.strftime("%Y-%m-%dT%H:00")
    vals = []
    for i in range(0, len(pts), ks.CHUNK):
        part = pts[i:i + ks.CHUNK]
        name = f"om_spots_{rv.MODEL}_{ks.VON}_{ks.BIS}_{i}_{len(part)}.json"
        data = _load(name)
        for k, l in enumerate(data if isinstance(data, list) else [data]):
            idx = _index(name, l)
            j = idx.get(key)
            s = d = None
            if j is not None:
                s, d = l["hourly"]["wind_speed_700hPa"][j], l["hourly"]["wind_direction_700hPa"][j]
            vals.append(((s, d) if s is not None and d is not None else None, regs[i + k]))
    return vals


_CACHE_JSON, _CACHE_IDX = {}, {}


def _load(name):
    if name not in _CACHE_JSON:
        _CACHE_JSON[name] = json.loads((rv.CACHE / name).read_bytes())
    return _CACHE_JSON[name]


def _index(name, loc):
    key = (name, id(loc))
    if key not in _CACHE_IDX:
        _CACHE_IDX[key] = {t: j for j, t in enumerate(loc["hourly"]["time"])}
    return _CACHE_IDX[key]


def region_vectors(pairs):
    """{Region: (u, v, speed)} aus (wert, region)-Paaren, Median der Komponenten."""
    by = {}
    for x, reg in pairs:
        if x:
            by.setdefault(reg, []).append(er.uv(*x))
    out = {}
    for reg, xs in by.items():
        if len(xs) >= 2:
            u, v = statistics.median(a for a, _ in xs), statistics.median(b for _, b in xs)
            out[reg] = (u, v, math.hypot(u, v))
    return out


def tile(regvec):
    """Kachel-Label + Richtung aus Regionsvektoren (Regel vom 05.11.2026)."""
    n = len(regvec)
    windy = [r for r in regvec.values() if r[2] >= ks.WIND_KMH]
    if not n or len(windy) / n < X:
        return "kaum", None
    units = [(u / s, v / s) for u, v, s in windy]
    uu, vv = sum(a for a, _ in units) / len(units), sum(b for _, b in units) / len(units)
    direction = math.degrees(math.atan2(uu, vv)) % 360
    if math.hypot(uu, vv) < Y:
        return "wechselt", direction
    return ("teils" if 1 - len(windy) / n >= Z else "pfeil"), direction


def plain_mean(pairs):
    """Heutige Kachel: Vektor-Mittel aller Punkte."""
    xs = [x for x, _ in pairs if x]
    return rv.vec_mean(xs)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sondes = {sid: igra_700(sid) for sid in SONDES}
    pts, regs = ks.spots(), er.spot_regions()
    ks.spot_noon(pts)

    # Teil 1: Modell an den Ballon-Orten
    locs = [SONDES[s][1:] for s in SONDES]
    icon_at = model_points(locs, "icon_d2", "sonden")
    ecmwf_at = model_points(locs, "ecmwf_ifs025", "sonden")
    part1 = {}
    for mname, series in (("icon_d2", icon_at), ("ecmwf_ifs025", ecmwf_at)):
        rows = []
        for (sid, obs), ser in zip(sondes.items(), series):
            for t, (os_, od) in obs.items():
                m = ser.get(t)
                if m and os_ >= 3.6:            # Ballon-Windstille: keine Richtung
                    rows.append((m[0], rv.ang(m[1], od)))
        part1[mname] = rv.bin_stats(rows)

    # Regions-Mittelpunkte für ECMWF (ein Punkt je Region)
    cent = {}
    for p, r in zip(pts, regs):
        cent.setdefault(r, []).append(p)
    reg_names = sorted(cent)
    reg_pts = [(statistics.mean(p[0] for p in cent[r]), statistics.mean(p[1] for p in cent[r])) for r in reg_names]
    ecmwf_reg = model_points(reg_pts, "ecmwf_ifs025", "regionen")

    # Teil 2 + 3: Kachel gegen Ballone
    times = sorted(set().union(*[set(o) for o in sondes.values()]))
    days = []
    for t in times:
        if not (ks.VON <= t.date().isoformat() <= ks.BIS):
            continue
        obs = [o[t] for o in sondes.values() if t in o]
        if len(obs) < 3:
            continue
        windy_o = [o for o in obs if o[0] >= ks.WIND_KMH]
        truth = {"ruhig": len(windy_o) <= 1, "teils": (len(obs) - len(windy_o)) / len(obs) >= 0.5,
                 "dir": rv.vec_mean(windy_o)[1] if len(windy_o) >= 2 else None}
        pairs = spots_at(pts, regs, t)
        if sum(1 for x, _ in pairs if x) < 0.9 * len(pts):
            continue
        lab, d_icon = tile(region_vectors(pairs))
        old = plain_mean(pairs)
        # ECMWF-Kachel: Regionspunkte, je Region ein Wert
        ev = {}
        for r, ser in zip(reg_names, ecmwf_reg):
            m = ser.get(t)
            if m:
                u, v = er.uv(*m)
                ev[r] = (u, v, m[0])
        lab_e, d_ecmwf = tile(ev) if ev else (None, None)
        days.append({"t": t.isoformat(), "label": lab, "icon_dir": d_icon,
                     "old_dir": old[1] if old else None, "old_kmh": old[0] if old else None,
                     "ecmwf_label": lab_e, "ecmwf_dir": d_ecmwf, "n_sonden": len(obs),
                     "t_ruhig": truth["ruhig"], "t_teils": truth["teils"], "t_dir": truth["dir"]})

    res = {"tage": len(days), "teil1_punkt": part1, **summarize(days)}
    (HERE / "radiosonde.json").write_text(json.dumps({**res, "days": days}, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    write_report(res)
    print((HERE / "RADIOSONDE_REPORT.md").read_text(encoding="utf-8"))


def _rate(xs, key):
    e = [rv.ang(x[key], x["t_dir"]) for x in xs if x.get(key) is not None and x["t_dir"] is not None]
    return {"n": len(e), "daneben_pct": round(100 * sum(v > 45 for v in e) / len(e)) if e else None}


def _halves(xs, fn):
    return {"alle": fn(xs), "jan_jun": fn([x for x in xs if x["t"] < "2026-07-01"]),
            "jul_nov": fn([x for x in xs if x["t"] >= "2026-07-01"])}


def summarize(days):
    """Treffer je Label gegen die Ballone, heutige Kachel, Modelle uneinig."""
    out = {"label_tage": {k: sum(d["label"] == k for d in days) for k in ("pfeil", "teils", "wechselt", "kaum")}}
    arrow = [d for d in days if d["label"] in ("pfeil", "teils")]
    out["pfeil_neu"] = _halves(arrow, lambda xs: _rate(xs, "icon_dir"))
    out["pfeil_heute_gleiche_tage"] = _halves(arrow, lambda xs: _rate(xs, "old_dir"))
    out["pfeil_heute_alle_ab10"] = _halves([d for d in days if (d["old_kmh"] or 0) >= 10],
                                           lambda xs: _rate(xs, "old_dir"))
    out["wechselt_pfeil_waere"] = _halves([d for d in days if d["label"] == "wechselt"],
                                          lambda xs: _rate(xs, "icon_dir"))

    def share(key, truth):
        def f(xs):
            s = [x for x in xs if x["label"] == key]
            return {"n": len(s), "richtig_pct": round(100 * sum(x[truth] for x in s) / len(s)) if s else None}
        return f
    out["teils_richtig"] = _halves(days, share("teils", "t_teils"))
    out["kaum_richtig"] = _halves(days, share("kaum", "t_ruhig"))
    # Kaum Wind: wie oft zeigt der Ballon an solchen Tagen wenigstens keine klare Richtung?
    out["kaum_ballone_uneinig_oder_ruhig"] = _halves(
        [d for d in days if d["label"] == "kaum"],
        lambda xs: {"n": len(xs), "pct": round(100 * sum(x["t_ruhig"] or x["t_dir"] is None for x in xs) / len(xs))
                    if xs else None})
    # Modelle uneinig (ICON-D2 vs ECMWF > 45°) bei Tagen mit Pfeil
    both = [d for d in arrow if d["ecmwf_dir"] is not None]
    dis = [d for d in both if rv.ang(d["icon_dir"], d["ecmwf_dir"]) > 45]
    agr = [d for d in both if rv.ang(d["icon_dir"], d["ecmwf_dir"]) <= 45]
    out["modelle_uneinig"] = _halves(dis, lambda xs: _rate(xs, "icon_dir"))
    out["modelle_einig"] = _halves(agr, lambda xs: _rate(xs, "icon_dir"))
    # ECMWF sagt "kaum"/"wechselt", ICON zeigt Pfeil
    out["ecmwf_kein_pfeil"] = _halves([d for d in arrow if d["ecmwf_label"] in ("kaum", "wechselt")],
                                      lambda xs: _rate(xs, "icon_dir"))
    # Kaum Wind nur, wenn beide Modelle "kaum" sagen
    out["kaum_beide_modelle"] = _halves([d for d in days if d["label"] == "kaum" and d["ecmwf_label"] == "kaum"],
                                        lambda xs: {"n": len(xs), "richtig_pct": round(
                                            100 * sum(x["t_ruhig"] for x in xs) / len(xs)) if xs else None})
    return out


def write_report(res):
    L = ["# RADIOSONDE_REPORT — Kachel-Labels gegen Wetterballone (700 hPa)", "",
         "_Maschinell erzeugt von `radiosonde.py` — nicht von Hand editieren._", "",
         f"{res['tage']} Aufstiege 12 UTC (Payerne, Stuttgart, München, Novara-Cameri; ≥3 je Termin), "
         f"{ks.VON} bis {ks.BIS}. „Daneben“ = Richtungsfehler > 45°.", "",
         "## Teil 1 — Modell an den Ballon-Orten", ""]
    for m, tab in res["teil1_punkt"].items():
        L += [f"### {m}", "", rv._table(tab), ""]
    L += ["## Teil 2/3 — Kachel gegen Ballone", "", f"Label-Tage: {res['label_tage']}", "",
          "| Prüfung | alle | Jan–Jun | Jul–Nov |", "|---|---|---|---|"]
    for k, v in res.items():
        if isinstance(v, dict) and "alle" in v:
            L.append(f"| {k} | {v['alle']} | {v['jan_jun']} | {v['jul_nov']} |")
    (HERE / "RADIOSONDE_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
