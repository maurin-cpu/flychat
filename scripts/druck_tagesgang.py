"""Mittlerer Tagesgang des Luftdrucks (pressure_msl) je Synoptik-Zone und Monat.

Warum: Ueber den Alpen schwankt der auf Meereshoehe reduzierte Druck jeden Tag
um 1-2 hPa (Aufheizung, Alpines Pumpen, Reduktionsartefakt) — die reine
Gezeit waere 0,4 hPa. Jede Drucktendenz oder jeder Drucksprung innerhalb
eines Tages misst ohne Abzug dieses Tagesgangs vor allem die Tageszeit
(Befund 23.09.2026: 06->22 h im September um +0,7..+1,0 hPa verzerrt).

Ergebnis: data/druck_tagesgang.json
  {"generated_at", "window": [von, bis], "zones": {zone: {"MM": [24 Werte]}},
   "n_days": {zone: {"MM": n}}, "models": {zone: {"MM": {"model": n_days}}}}
Werte = Anomalie zum Tagesmittel in hPa, Lokalzeit-Stunde 0..23, Median ueber
die Referenzpunkte der Zone je Stunde (wie engine.synoptic_context.
detect_frontsignatur). Quelle: Open-Meteo historical-forecast-api,
meteoswiss_icon_ch1 je Tag, sonst icon_d2.

Laufen: python scripts/druck_tagesgang.py [--days 365] — ca. 1 Minute.
Nachziehen: einmal je Quartal reicht; die Datei ist klein und getrackt.
"""
import argparse
import json
import statistics
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import config  # noqa: E402
from engine.synoptic_context import _zone_of_region  # noqa: E402

OUT = config.DATA_DIR / "druck_tagesgang.json"
MODELS = ("meteoswiss_icon_ch1", "icon_d2")
POINTS_PER_REGION = 2
API = "https://historical-forecast-api.open-meteo.com/v1/forecast?"


def _points_by_zone() -> dict:
    g = json.load(open(config.REGIONEN_GEOJSON_PATH, encoding="utf-8"))
    out = defaultdict(list)
    for f in g.get("features") or []:
        props = f.get("properties") or {}
        refs = props.get("reference_points") or []
        z = _zone_of_region({"reference_points": refs})
        if z not in config.SYNOPTIC_ZONES or not refs:
            continue
        idx = sorted({0, len(refs) // 2})[:POINTS_PER_REGION]
        out[z].extend(tuple(refs[i]) for i in idx)
    return out


def _fetch(points, start, end, chunk_days: int = 60) -> list:
    """Ein Jahr in 60-Tage-Stuecken — die API bricht grosse Antworten ab
    (IncompleteRead bei ~0,5 MB)."""
    merged: list = []
    a = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    while a <= stop:
        b = min(a + timedelta(days=chunk_days - 1), stop)
        q = {"latitude": ",".join(f"{p[0]:.4f}" for p in points),
             "longitude": ",".join(f"{p[1]:.4f}" for p in points),
             "hourly": "pressure_msl", "models": ",".join(MODELS),
             "start_date": a.isoformat(), "end_date": b.isoformat(),
             "timezone": "Europe/Zurich"}
        with urllib.request.urlopen(API + urllib.parse.urlencode(q), timeout=180) as r:
            data = json.load(r)
        data = data if isinstance(data, list) else [data]
        if not merged:
            merged = data
        else:
            for m, d in zip(merged, data):
                for k, v in d["hourly"].items():
                    m["hourly"][k] = (m["hourly"].get(k) or []) + (v or [])
        a = b + timedelta(days=1)
    return merged


def _series_by_day(hourly: dict, model: str) -> dict:
    key = f"pressure_msl_{model}"
    out = defaultdict(lambda: [None] * 24)
    for t, v in zip(hourly.get("time") or [], hourly.get(key) or []):
        out[t[:10]][int(t[11:13])] = v
    return out


def build(days: int) -> dict:
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    zones, n_days, models = {}, {}, {}
    for z, points in sorted(_points_by_zone().items()):
        data = _fetch(points, start.isoformat(), end.isoformat())
        per_model = {m: [_series_by_day(d["hourly"], m) for d in data] for m in MODELS}
        month_cyc = defaultdict(lambda: [[] for _ in range(24)])
        month_src = defaultdict(lambda: defaultdict(int))
        for d in sorted({k for s in per_model[MODELS[0]] for k in s}):
            for m in MODELS:
                series = [s[d] for s in per_model[m] if d in s and None not in s[d]]
                if len(series) >= max(2, len(points) // 2):
                    break
            else:
                continue
            med = [statistics.median(s[h] for s in series) for h in range(24)]
            mean = statistics.mean(med)
            for h in range(24):
                month_cyc[d[5:7]][h].append(med[h] - mean)
            month_src[d[5:7]][m] += 1
        zones[z] = {mm: [round(statistics.mean(v), 2) for v in hs]
                    for mm, hs in sorted(month_cyc.items()) if hs[0]}
        n_days[z] = {mm: len(hs[0]) for mm, hs in sorted(month_cyc.items())}
        models[z] = {mm: dict(src) for mm, src in sorted(month_src.items())}
        print(f"{z:20s} {len(points):2d} Punkte  Monate: " +
              " ".join(f"{mm}:{n}" for mm, n in n_days[z].items()))
    return {"generated_at": datetime.now().isoformat(timespec="seconds"),
            "window": [start.isoformat(), end.isoformat()],
            "source": "open-meteo historical-forecast-api", "models": models,
            "n_days": n_days, "zones": zones}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    res = build(a.days)
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("geschrieben:", a.out)
