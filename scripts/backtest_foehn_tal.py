#!/usr/bin/env python3
"""
backtest_foehn_tal.py — Modell-Föhnindex pro Tal gegen den amtlichen Föhnindex.

Frage: Erkennt ein Föhnindex, der am Talpunkt selbst gerechnet wird, den Föhn
mit weniger Fehlalarmen als die heutige nationale Warnung (Δp Lugano−Zürich)?

Modell-Index (angelehnt an Dürr 2008, am Modell kalibriert):
  Talpunkt  = data/foehn_talpunkte.geojson (= Station)
  Kammpunkt = Gütsch 2286 m (Dürr: Referenz für die Nordseite)
  Föhn, wenn  Δθ = θ(Tal) − θ(Kamm) ≥ dθ_min
          und Windrichtung Tal im Föhnsektor (Mitte = mittlere Richtung der
              Station bei Föhn, Breite variabel)
          und Böe Tal ≥ böe_min
          und rel. Feuchte Tal ≤ rh_max
  Schwellen werden per Gittersuche auf einem TRAININGSZEITRAUM eingestellt
  (bestes CSI) und auf einem getrennten TESTZEITRAUM gemessen.

Vergleich auf denselben Teststunden (Flugfenster, Wahrheit wie
backtest_foehn.py: Föhnstunde = ≥3/6 Zehnminutenwerte Index 2, Mischluft
weder Treffer noch Fehlalarm):
  national      = evaluate_foehn (Produktivlogik)
  tal           = Modell-Index am Talpunkt
  national∧tal  = Warnung nur, wenn beide anschlagen

Modelle: icon_d2 (2 km, ganze Periode → Train 2024–2025, Test 2026),
         meteoswiss_icon_ch1 (1 km, erst ab 08/2025 → Train 08/2025–03/2026,
         Test 04–09/2026; Gegenprobe, kurze Reihe).

Ausgabe: validation/foehn/AUTO_REPORT_TAL.md + scoreboard_tal.json
Modelldaten-Cache: validation/foehn/modell/tal_<ABK>_<modell>.json (Klasse C)
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import config  # noqa: E402
from backtest_foehn import (  # noqa: E402
    STATIONS, VDIR, in_flight_window, load_model, load_truth, model_levels,
)

API = "https://historical-forecast-api.open-meteo.com/v1/forecast"
VARS = "temperature_2m,surface_pressure,relative_humidity_2m,wind_speed_10m,wind_direction_10m,wind_gusts_10m"
KAMM = ("GUE", 46.6525, 8.6155)  # Gütsch ob Andermatt

MODELLE = {
    # modell: (abruf_start, abruf_ende, train_bis_exkl, test_ab)
    "icon_d2": ("2024-01-01", "2026-09-26", "2026-01-01", "2026-01-01"),
    "meteoswiss_icon_ch1": ("2025-08-01", "2026-09-26", "2026-04-01", "2026-04-01"),
}


# ---------------------------------------------------------------- Daten

def talpunkte() -> dict[str, tuple[float, float]]:
    gj = json.loads(config.FOEHN_TALPUNKTE_PATH.read_text(encoding="utf-8"))
    out = {}
    for f in gj["features"]:
        lon, lat = f["geometry"]["coordinates"]
        out[f["properties"]["id"].upper()] = (lat, lon)
    return out


def fetch_point(abbr: str, lat: float, lon: float, modell: str) -> dict:
    """Stundenreihe UTC am Punkt, gecacht. Abruf jahresweise."""
    path = VDIR / "modell" / f"tal_{abbr}_{modell}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    start, ende = MODELLE[modell][:2]
    merged: dict[str, list] = {}
    y0, y1 = int(start[:4]), int(ende[:4])
    for y in range(y0, y1 + 1):
        s = max(start, f"{y}-01-01")
        e = min(ende, f"{y}-12-31")
        url = (f"{API}?latitude={lat}&longitude={lon}&hourly={VARS}&models={modell}"
               f"&start_date={s}&end_date={e}&timezone=GMT&wind_speed_unit=kmh")
        for versuch in range(4):
            try:
                d = json.load(urllib.request.urlopen(url, timeout=120))
                break
            except Exception as ex:  # Rate-Limit / Timeout
                print(f"  [retry {versuch + 1}] {abbr} {y}: {ex}")
                time.sleep(20 * (versuch + 1))
        else:
            raise RuntimeError(f"Abruf {abbr} {modell} {y} fehlgeschlagen")
        for k, v in d["hourly"].items():
            merged.setdefault(k, []).extend(v)
        time.sleep(1)
    out = {"latitude": lat, "longitude": lon, "model": modell, "hourly": merged}
    path.write_text(json.dumps(out), encoding="utf-8")
    return out


def theta(t_c, p_hpa):
    if t_c is None or p_hpa is None or p_hpa <= 0:
        return None
    return (t_c + 273.15) * (1000.0 / p_hpa) ** 0.2857


def features(tal: dict, kamm: dict) -> dict[str, dict]:
    """{'YYYY-MM-DDTHH': {dth, dir, gust, rh}}"""
    ht, hk = tal["hourly"], kamm["hourly"]
    idx_k = {t: i for i, t in enumerate(hk["time"])}
    out = {}
    for i, t in enumerate(ht["time"]):
        j = idx_k.get(t)
        if j is None:
            continue
        th_t = theta(ht["temperature_2m"][i], ht["surface_pressure"][i])
        th_k = theta(hk["temperature_2m"][j], hk["surface_pressure"][j])
        if th_t is None or th_k is None or ht["wind_direction_10m"][i] is None:
            continue
        out[t[:13]] = {
            "dth": th_t - th_k,
            "dir": ht["wind_direction_10m"][i],
            "gust": ht["wind_gusts_10m"][i] or 0.0,
            "rh": ht["relative_humidity_2m"][i] if ht["relative_humidity_2m"][i] is not None else 100.0,
        }
    return out


# ---------------------------------------------------------------- Bewertung

def stunden(truth: dict, feats: dict, national: dict, side: str, von: str, bis: str) -> list[dict]:
    """Bewertbare Flugfenster-Stunden im Zeitraum [von, bis) mit Wahrheit + beiden Prüflingen."""
    rows = []
    for key, (nf, nm, nt) in truth.items():
        if not (von <= key[:10] < bis):
            continue
        if nt < 4 or key not in feats or key not in national or not in_flight_window(key):
            continue
        foehn = nf >= 3
        misch = (not foehn) and (nf + nm) >= 3
        rows.append({"foehn": foehn, "misch": misch, "f": feats[key],
                     "nat": national[key][side] in ("caution", "danger")})
    return rows


def ang_diff(a, b):
    return abs((a - b + 180) % 360 - 180)


def tal_warnt(f: dict, p: dict) -> bool:
    return (f["dth"] >= p["dth_min"]
            and ang_diff(f["dir"], p["sektor_mitte"]) <= p["sektor_halb"]
            and f["gust"] >= p["boe_min"]
            and f["rh"] <= p["rh_max"])


def score(rows: list[dict], warn) -> dict:
    hit = miss = fa = 0
    for r in rows:
        if r["misch"]:
            continue
        w = warn(r)
        if r["foehn"]:
            hit += w
            miss += not w
        else:
            fa += w
    pod = hit / (hit + miss) if hit + miss else None
    far = fa / (fa + hit) if fa + hit else None
    csi = hit / (hit + miss + fa) if hit + miss + fa else None
    return {"hit": hit, "miss": miss, "fa": fa,
            "pod": None if pod is None else round(100 * pod, 1),
            "far": None if far is None else round(100 * far, 1),
            "csi": None if csi is None else round(100 * csi, 1)}


def sektor_mitte(rows: list[dict]) -> float:
    """Vektor-Mittel der Modell-Windrichtung in Föhnstunden (Training)."""
    sx = sy = 0.0
    for r in rows:
        if r["foehn"]:
            a = math.radians(r["f"]["dir"])
            sx += math.sin(a)
            sy += math.cos(a)
    return round(math.degrees(math.atan2(sx, sy)) % 360)


def kalibrieren(train: list[dict]) -> dict:
    mitte = sektor_mitte(train)
    best = None
    gitter = itertools.product(
        [x / 2 for x in range(-16, 5)],      # dθ_min −8 … +2 K
        [30, 45, 60, 90, 180],               # Sektor ± Grad (180 = egal)
        [0, 10, 20, 30, 40, 50, 60],         # Böe km/h
        [100, 80, 70, 60, 50],               # RH max %
    )
    for dth, halb, boe, rh in gitter:
        p = {"dth_min": dth, "sektor_mitte": mitte, "sektor_halb": halb, "boe_min": boe, "rh_max": rh}
        s = score(train, lambda r: tal_warnt(r["f"], p))
        if s["csi"] is not None and (best is None or s["csi"] > best[0]["csi"]):
            best = (s, p)
    return best[1]


def run(modell: str, stationen: list[str]) -> dict:
    _, _, train_bis, test_ab = MODELLE[modell]
    start, ende = MODELLE[modell][:2]
    nord, sued = load_model()
    national = model_levels(nord, sued)
    pts = talpunkte()
    kamm = fetch_point(KAMM[0], KAMM[1], KAMM[2], modell)
    res = {}
    for abbr in stationen:
        name, region, side = STATIONS[abbr]
        truth = load_truth(abbr)
        lat, lon = pts[abbr]
        feats = features(fetch_point(abbr, lat, lon, modell), kamm)
        train = stunden(truth, feats, national, side, start, train_bis)
        test = stunden(truth, feats, national, side, test_ab, "2026-09-27")
        p = kalibrieren(train)
        res[abbr] = {
            "name": name, "modell": modell, "params": p,
            "train": {"zeitraum": [start, train_bis], "stunden": len(train),
                      "tal": score(train, lambda r: tal_warnt(r["f"], p)),
                      "national": score(train, lambda r: r["nat"])},
            "test": {"zeitraum": [test_ab, "2026-09-26"], "stunden": len(test),
                     "foehn_h": sum(r["foehn"] for r in test),
                     "national": score(test, lambda r: r["nat"]),
                     "tal": score(test, lambda r: tal_warnt(r["f"], p)),
                     "national_und_tal": score(test, lambda r: r["nat"] and tal_warnt(r["f"], p))},
        }
        print(f"{modell} {abbr}: {res[abbr]['test']}")
    return res


def report(alle: dict) -> str:
    L = ["# Föhn pro Tal — AUTO_REPORT_TAL (maschinell erzeugt, nicht editieren)\n",
         "Modell-Föhnindex am Talpunkt (Δθ Tal−Gütsch, Windsektor, Böe, Feuchte; Schwellen "
         "auf dem Trainingszeitraum per Gittersuche auf bestes CSI eingestellt) gegen die nationale "
         "Warnung `evaluate_foehn`, gemessen auf einem **getrennten Testzeitraum**. Wahrheit = "
         "MeteoSchweiz-Föhnindex, Flugfenster "
         f"{config.FLIGHT_HOURS_START}–{config.FLIGHT_HOURS_END} Uhr lokal, Mischluft ausgeklammert.\n",
         "Treffer % = POD, FAR % = Anteil Warnstunden ohne Föhn, CSI = Treffer/(Treffer+verpasst+Fehlalarm).\n"]
    for modell, res in alle.items():
        L.append(f"## {modell}\n")
        L.append("| Station | Test | Föhn-h | national Treffer/FAR/CSI | tal Treffer/FAR/CSI | national∧tal Treffer/FAR/CSI | Fehlalarm-h national → tal |")
        L.append("|---|---|---|---|---|---|---|")
        for abbr, r in res.items():
            t = r["test"]
            f = lambda s: f"{s['pod']} / {s['far']} / {s['csi']}"  # noqa: E731
            L.append(f"| {r['name']} | {t['zeitraum'][0]}…{t['zeitraum'][1]} ({t['stunden']} h) | {t['foehn_h']} | "
                     f"{f(t['national'])} | {f(t['tal'])} | {f(t['national_und_tal'])} | "
                     f"{t['national']['fa']} → {t['tal']['fa']} |")
        L.append("\nEingestellte Schwellen (Training):\n")
        L.append("| Station | Training | dθ min K | Sektor | Böe min km/h | RH max % | Train tal CSI | Train national CSI |")
        L.append("|---|---|---|---|---|---|---|---|")
        for abbr, r in res.items():
            p, tr = r["params"], r["train"]
            sek = "egal" if p["sektor_halb"] >= 180 else f"{p['sektor_mitte']}° ± {p['sektor_halb']}°"
            L.append(f"| {r['name']} | {tr['zeitraum'][0]}…{tr['zeitraum'][1]} ({tr['stunden']} h) | {p['dth_min']} | {sek} | "
                     f"{p['boe_min']} | {p['rh_max']} | {tr['tal']['csi']} | {tr['national']['csi']} |")
        L.append("")
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stationen", default="ALT,VAD")
    ap.add_argument("--modelle", default=",".join(MODELLE))
    a = ap.parse_args()
    stationen = [s.strip().upper() for s in a.stationen.split(",")]
    alle = {m: run(m, stationen) for m in a.modelle.split(",")}
    (VDIR / "scoreboard_tal.json").write_text(json.dumps(alle, ensure_ascii=False, indent=1), encoding="utf-8")
    txt = report(alle)
    (VDIR / "AUTO_REPORT_TAL.md").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
