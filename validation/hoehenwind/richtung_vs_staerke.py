# -*- coding: utf-8 -*-
"""Ab welcher Windstärke stimmt die Höhenwind-Richtung der Tageskachel?

Richter (Wahrheit): SwissMetNet-Gipfelstationen nahe 700 hPa, Zehnminutenwerte
(MeteoSchweiz OGD). Prognose: Open-Meteo historical-forecast-api, ICON-D2,
Wind 700 hPa an den Stationskoordinaten — dasselbe Modell und dieselbe Fläche
wie die Tageskachel (config.PRESSURE_LEVEL_PRIMARY_MODEL, 12:00 Ortszeit).

Test A (Punkt): Richtungsfehler Modell vs. Messung je Station, nach Modellstärke.
Test B (Kachel): Vektor-Mittel über die Stationen, Modell vs. Messung, nach
gemittelter Modellstärke; dazu R = |Vektormittel| / Skalarmittel des Modells
(sind sich die Stationen einig?).
Zeitachsenbeweis: Modell-T700 gegen gemessene Lufttemperatur, Lag -3..+3 h.

Aufruf:  python validation/hoehenwind/richtung_vs_staerke.py [--von 2026-01-01] [--bis 2026-11-04]
Schreibt AUTO_REPORT.md und ergebnis.json neben dieses Skript. Rohdaten-Cache
im System-Temp (nicht im Repo).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import math
import statistics
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from validation_common import SMN_BASE  # noqa: E402

TZ = ZoneInfo("Europe/Zurich")
UA = {"User-Agent": "wingcast-validation/1.0"}
CACHE = Path(tempfile.gettempdir()) / "wingcast_hoehenwind_cache"
STATIONS = ["JUN", "GOR", "COV", "WFJ", "SAE", "GUE"]
MODEL = "icon_d2"
BINS = [0, 5, 10, 15, 20, 25, 30, 40, 1000]
DANEBEN_DEG = 45          # mehr als ein Achtel daneben = Pfeil zeigt in einen Nachbarsektor
CALM_MS = 0.5             # gemessene Windstille: keine Richtung, separat gezählt


def fetch(url: str, cache_name: str) -> bytes:
    CACHE.mkdir(exist_ok=True)
    p = CACHE / cache_name
    if p.exists() and p.stat().st_size > 0:
        return p.read_bytes()
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    p.write_bytes(data)
    return data


def station_meta() -> dict:
    raw = fetch(f"{SMN_BASE}/ogd-smn_meta_stations.csv", "meta.csv").decode("cp1252", "replace")
    out = {}
    for r in csv.DictReader(io.StringIO(raw), delimiter=";"):
        a = r["station_abbr"].upper()
        if a in STATIONS:
            out[a] = {"name": r["station_name"], "lat": float(r["station_coordinates_wgs84_lat"]),
                      "lon": float(r["station_coordinates_wgs84_lon"]),
                      "elev": float(r.get("station_height_masl") or 0)}
    return out


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def station_obs(abbr: str) -> dict:
    """{datetime_local: (speed_ms, dir_deg, temp_c)} aus den Zehnminutenwerten (UTC)."""
    a = abbr.lower()
    raw = fetch(f"{SMN_BASE}/{a}/ogd-smn_{a}_t_recent.csv", f"{a}_t_recent.csv").decode("utf-8", "replace")
    out = {}
    for r in csv.DictReader(io.StringIO(raw), delimiter=";"):
        ts = r.get("reference_timestamp") or ""
        try:
            t = dt.datetime.strptime(ts, "%d.%m.%Y %H:%M").replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
        out[t.astimezone(TZ).replace(tzinfo=None)] = (_f(r.get("fkl010z0")), _f(r.get("dkl010z0")),
                                                      _f(r.get("tre200s0")))
    return out


def model_series(lat: float, lon: float, von: str, bis: str, abbr: str) -> dict:
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "models": MODEL, "timezone": "Europe/Zurich",
        "hourly": "wind_speed_700hPa,wind_direction_700hPa,temperature_700hPa",
        "start_date": von, "end_date": bis})
    raw = fetch(f"https://historical-forecast-api.open-meteo.com/v1/forecast?{q}",
                f"om_{MODEL}_{abbr}_{von}_{bis}.json")
    h = json.loads(raw)["hourly"]
    out = {}
    for i, t in enumerate(h["time"]):
        out[dt.datetime.fromisoformat(t)] = (h["wind_speed_700hPa"][i], h["wind_direction_700hPa"][i],
                                             h["temperature_700hPa"][i])
    return out


def vec_mean(samples):
    """[(speed, dir)] -> (speed, dir, R). R = |Vektormittel| / Skalarmittel."""
    s = [(v, d) for v, d in samples if v is not None and d is not None]
    if not s:
        return None
    u = sum(v * math.sin(math.radians(d)) for v, d in s) / len(s)
    w = sum(v * math.cos(math.radians(d)) for v, d in s) / len(s)
    sp = math.hypot(u, w)
    scal = sum(v for v, _ in s) / len(s)
    return sp, math.degrees(math.atan2(u, w)) % 360, (sp / scal if scal > 0 else 0.0)


def ang(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


def obs_noon(obs: dict, day: dt.date):
    """Vektor-Mittel 11:30-12:30 Ortszeit (7 Zehnminutenwerte), km/h."""
    base = dt.datetime.combine(day, dt.time(12, 0))
    xs = []
    for m in range(-30, 31, 10):
        v = obs.get(base + dt.timedelta(minutes=m))
        if v and v[0] is not None and v[1] is not None:
            xs.append((v[0] * 3.6, v[1]))
    if len(xs) < 4:
        return None
    return vec_mean(xs)


def bin_label(lo, hi):
    return f">{lo}" if hi >= 1000 else f"{lo}–{hi}"


def bin_stats(rows):
    """rows: [(model_kmh, err_deg)] -> Tabelle je Stärkeklasse."""
    out = []
    for lo, hi in zip(BINS[:-1], BINS[1:]):
        e = [err for v, err in rows if lo <= v < hi]
        if not e:
            out.append({"klasse": bin_label(lo, hi), "n": 0})
            continue
        out.append({"klasse": bin_label(lo, hi), "n": len(e),
                    "median_fehler": round(statistics.median(e)),
                    "daneben_pct": round(100 * sum(1 for x in e if x > DANEBEN_DEG) / len(e)),
                    "grob_falsch_pct": round(100 * sum(1 for x in e if x > 90) / len(e))})
    return out


def lag_proof(obs: dict, mod: dict) -> dict:
    """Korrelation Modell-T700 (Stunde t) gegen gemessene T (Stunde t+lag)."""
    res = {}
    for lag in range(-3, 4):
        a, b = [], []
        for t, (_, _, tm) in mod.items():
            o = obs.get(t + dt.timedelta(hours=lag))
            if tm is not None and o and o[2] is not None:
                a.append(tm)
                b.append(o[2])
        if len(a) > 100:
            res[lag] = round(statistics.correlation(a, b), 4)
    return res


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--von", default="2026-01-01")
    ap.add_argument("--bis", default=(dt.date.today() - dt.timedelta(days=1)).isoformat())
    args = ap.parse_args()

    meta = station_meta()
    days = [dt.date.fromisoformat(args.von) + dt.timedelta(days=i)
            for i in range((dt.date.fromisoformat(args.bis) - dt.date.fromisoformat(args.von)).days + 1)]

    obs, mod, lags = {}, {}, {}
    for a in STATIONS:
        m = meta[a]
        print(f"lade {a} {m['name']} ({m['elev']:.0f} m)", flush=True)
        obs[a] = station_obs(a)
        mod[a] = model_series(m["lat"], m["lon"], args.von, args.bis, a)
        lags[a] = lag_proof(obs[a], mod[a])

    # Test A — je Station
    rows_all, per_station, calm, missing = [], {}, 0, 0
    pairs = {}   # (day) -> {abbr: (mod_kmh, mod_dir, obs_kmh, obs_dir)}
    for a in STATIONS:
        rows = []
        for d in days:
            mv = mod[a].get(dt.datetime.combine(d, dt.time(12, 0)))
            ov = obs_noon(obs[a], d)
            if not mv or mv[0] is None or mv[1] is None or ov is None:
                missing += 1
                continue
            if ov[0] < CALM_MS * 3.6:
                calm += 1
                continue
            err = ang(mv[1], ov[1])
            rows.append((mv[0], err))
            pairs.setdefault(d, {})[a] = (mv[0], mv[1], ov[0], ov[1])
        per_station[a] = {"n": len(rows), "tabelle": bin_stats(rows)}
        rows_all += rows
    test_a = bin_stats(rows_all)

    # Test B — Kachel-Ebene: Vektor-Mittel über die Stationen (nur Tage mit >= 4 Stationen)
    rows_b, rows_b_r = [], []
    for d, st in pairs.items():
        if len(st) < 4:
            continue
        mm = vec_mean([(v[0], v[1]) for v in st.values()])
        om = vec_mean([(v[2], v[3]) for v in st.values()])
        err = ang(mm[1], om[1])
        rows_b.append((mm[0], err))
        rows_b_r.append((mm[2], mm[0], err))
    test_b = bin_stats(rows_b)
    r_tab = []
    for lo, hi in ((0, .5), (.5, .7), (.7, .85), (.85, .95), (.95, 1.01)):
        e = [err for r, _, err in rows_b_r if lo <= r < hi]
        if e:
            r_tab.append({"R": f"{lo:.2f}–{min(hi, 1):.2f}", "n": len(e),
                          "median_fehler": round(statistics.median(e)),
                          "daneben_pct": round(100 * sum(1 for x in e if x > DANEBEN_DEG) / len(e))})

    res = {"zeitraum": [args.von, args.bis], "modell": MODEL, "stationen": meta,
           "daneben_grenze_deg": DANEBEN_DEG, "windstille_ausgelassen": calm, "fehlend": missing,
           "zeitachse_korrelation_lag_h": lags, "test_a_alle": test_a, "test_a_je_station": per_station,
           "test_b_kachel": test_b, "test_b_nach_R": r_tab, "test_b_tage": len(rows_b)}
    (HERE / "ergebnis.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    write_report(res)
    print((HERE / "AUTO_REPORT.md").read_text(encoding="utf-8"))


def _table(tab, key="klasse", head="Modellstärke km/h"):
    lines = [f"| {head} | n | Median-Fehler | daneben (>{DANEBEN_DEG}°) | grob falsch (>90°) |",
             "|---|---|---|---|---|"]
    for r in tab:
        if not r.get("n"):
            lines.append(f"| {r[key]} | 0 | – | – | – |")
        else:
            lines.append(f"| {r[key]} | {r['n']} | {r['median_fehler']}° | {r['daneben_pct']} % | "
                         f"{r.get('grob_falsch_pct', '–')}{' %' if 'grob_falsch_pct' in r else ''} |")
    return "\n".join(lines)


def write_report(res):
    st = res["stationen"]
    L = ["# AUTO_REPORT — Höhenwind-Richtung vs. Stärke",
         "", "_Maschinell erzeugt von `richtung_vs_staerke.py` — nicht von Hand editieren._", "",
         f"Zeitraum {res['zeitraum'][0]} bis {res['zeitraum'][1]}, 12:00 Ortszeit. "
         f"Prognose: Open-Meteo historical-forecast-api, `{res['modell']}`, Wind 700 hPa. "
         "Wahrheit: SwissMetNet, Vektor-Mittel der Zehnminutenwerte 11:30–12:30.",
         "", "Stationen: " + ", ".join(f"{a} {v['name']} ({v['elev']:.0f} m)" for a, v in st.items()) + ".",
         f"Ausgelassen: {res['windstille_ausgelassen']} Fälle gemessene Windstille, "
         f"{res['fehlend']} Fälle ohne Messung oder Prognose.",
         "", "Zufall wäre: Median 90°, 75 % daneben, 50 % grob falsch.",
         "", "## Zeitachsenbeweis (Korrelation Modell-T700 ↔ gemessene Temperatur, Lag in h)", "",
         "| Station | " + " | ".join(f"{l:+d}" for l in range(-3, 4)) + " |",
         "|---|" + "---|" * 7]
    for a, lag in res["zeitachse_korrelation_lag_h"].items():
        best = max(lag, key=lambda k: lag[k]) if lag else None
        L.append(f"| {a} | " + " | ".join(
            (f"**{lag[k]:.3f}**" if k == best else f"{lag[k]:.3f}") if k in lag else "–"
            for k in range(-3, 4)) + " |")
    L += ["", "## Test A — je Station (alle Stationen zusammen)", "", _table(res["test_a_alle"]), ""]
    for a, v in res["test_a_je_station"].items():
        L += [f"### {a} {st[a]['name']} (n={v['n']})", "", _table(v["tabelle"]), ""]
    L += [f"## Test B — Kachel-Ebene: Vektor-Mittel über die Stationen ({res['test_b_tage']} Tage)", "",
          _table(res["test_b_kachel"], head="gemittelte Modellstärke km/h"), "",
          "### Nach Einigkeit der Stationen im Modell (R = |Vektormittel| / Skalarmittel)", "",
          "| R | n | Median-Fehler | daneben |", "|---|---|---|---|"]
    for r in res["test_b_nach_R"]:
        L.append(f"| {r['R']} | {r['n']} | {r['median_fehler']}° | {r['daneben_pct']} % |")
    (HERE / "AUTO_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
