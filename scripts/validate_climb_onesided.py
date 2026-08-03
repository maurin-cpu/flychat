"""Einseitiger Validierungstest: Erkennt der Forecast, WO gute Thermik war?

Methodisch zwingend einseitig — der README von validation/xcontest/ haelt fest:
"Wenige oder keine Fluege ab Spot X != Spot war schlecht" (Pilotendichte,
Topografie, Wochentag). Zulaessig ist nur der umgekehrte Schluss: viele/weite
Fluege ab X => X war an dem Tag gut. Gemessen wird daher der Perzentil-Rang der
BEWIESEN guten Regionen in unserer Tages-Rangliste. 50 % = Zufall, kleiner = besser.

Zwei Datenquellen:
  1. validation/xcontest/_raw/strong_flights_*.tsv — pro Tag+Startplatz der beste
     Gleitschirmflug ab 60 km (HG/RW-Klassen bereits ausgefiltert).
  2. validation/xcontest/observations.csv — die gepflegte Spot->Region-Zuordnung
     der Mai/Juni-Tage.

Kontroll-Test: dieselbe Metrik mit Groessen, die trennen MUESSEN (wenig Regen,
wenig Boeen). Liefern die ebenfalls ~50 %, ist die Metrik zu verrauscht und kein
Befund belastbar.

Nur-Lese-Skript.
"""
from __future__ import annotations

import csv
import glob
import json
import statistics as st
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "data" / "weather_archive"
VAL = ROOT / "validation/xcontest"

THRESHOLDS = (60.0, 100.0)
MIN_SPOTS_PER_REGION = 3

# Startplatznamen, die in fluggebiete_dhv.csv anders/abgekuerzt heissen.
ALIASES = {
    "cret du midi": "Crêt-du-Midi", "crap sogn": "Flims- Laax - Crap Sogn Gion",
    "schynige": "Schynige Platte -Kamel_Chrüterwand (Interlaken)",
    "tschenten": "Tschentenegg", "dreibunde": "Dreibuendenstein-2120",
    "cari": "Carì, diint", "grand cha": "Grand Chavalard",
    "klein tsc": "Klein Titschuggen", "bargli ch": "Bärgli-Chrüz",
    "laupersdo": "Laupersdorf", "mulkerbla": "Mülkerblatten",
}
# Namen, die auf mehrere reale Startplaetze passen -> nicht zuordenbar.
AMBIGUOUS = {"scheidegg", "rothorn", "brunni", "niederhorn", "spitz", "tritt",
             "moor", "unbekannt", "unknown"}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return "".join(c for c in s if c.isalnum() or c.isspace()).strip()


def load_spot_index():
    files = sorted(glob.glob(str(ARCHIVE / "*.json")))
    spots = json.load(open(files[-1], encoding="utf-8"))["spots"]
    return {norm(n): (v.get("analyse_region") or "?") for n, v in spots.items()}


def match_launch(launch: str, idx) -> str | None:
    key = norm(launch)
    if not key or key in ("", "?") or key in AMBIGUOUS:
        return None
    for alias, target in ALIASES.items():
        if key.startswith(alias):
            hit = idx.get(norm(target))
            if hit:
                return hit
    if key in idx:
        return idx[key]
    for pred in (lambda k: k.startswith(key), lambda k: key.startswith(k) and len(k) >= 5):
        cands = {v for k, v in idx.items() if pred(k)}
        if len(cands) == 1:
            return cands.pop()
    return None


_DAY_CACHE: dict[str, dict | None] = {}


def _day_medians(day: str):
    """Pro Tag EINMAL das Archiv lesen -> {var: {region: Median}}. Gecacht."""
    if day in _DAY_CACHE:
        return _DAY_CACHE[day]
    f = ARCHIVE / f"{day}.json"
    if not f.exists():
        _DAY_CACHE[day] = None
        return None
    spots = json.load(open(f, encoding="utf-8"))["spots"]
    acc: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for _n, v in spots.items():
        reg = norm(v.get("analyse_region") or "?")
        for var, x in v["daily_aggregates"].items():
            if x is not None:
                acc[var][reg].append(x)
    out = {var: {r: st.median(vals) for r, vals in per.items()
                 if len(vals) >= MIN_SPOTS_PER_REGION}
           for var, per in acc.items()}
    _DAY_CACHE[day] = out
    return out


def day_ranking(day: str, var: str, ascending: bool = False):
    """Regionen des Tages nach `var` sortiert -> {region: Perzentil-Rang}."""
    med = _day_medians(day)
    if not med:
        return None
    fc = med.get(var) or {}
    if not fc:
        return None
    order = sorted(fc.items(), key=lambda x: (x[1] if ascending else -x[1]))
    return {r: 100 * (i + 1) / len(order) for i, (r, _) in enumerate(order)}


def collect_proven_good(idx):
    """(day, region) -> beste km + airtime des Tages. Beide Quellen, dedupliziert."""
    best: dict[tuple[str, str], tuple[float, str]] = {}
    unmatched = defaultdict(int)

    for path in sorted(glob.glob(str(VAL / "_raw" / "strong_flights_*.tsv"))):
        for row in csv.DictReader(open(path, encoding="utf-8"), delimiter="\t"):
            try:
                km = float(row["km"])
            except (TypeError, ValueError):
                continue
            reg = match_launch(row["launch"], idx)
            if not reg:
                unmatched[row["launch"]] += 1
                continue
            key = (row["date"], norm(reg))
            if key not in best or km > best[key][0]:
                best[key] = (km, row.get("airtime") or "")

    for row in csv.DictReader(open(VAL / "observations.csv", encoding="utf-8", errors="replace")):
        try:
            km = float(row.get("best_km") or "")
        except ValueError:
            continue
        reg = (row.get("region") or "").strip()
        day = (row.get("date") or "").strip()
        if not reg or not day:
            continue
        key = (day, norm(reg))
        if key not in best or km > best[key][0]:
            best[key] = (km, row.get("top_airtime") or "")
    return best, unmatched


def percentile_test(best, var, ascending, thresh, label, verbose=False):
    pct, detail = [], []
    for (day, reg), (km, air) in best.items():
        if km < thresh:
            continue
        rk = day_ranking(day, var, ascending)
        if not rk:
            continue
        p = rk.get(reg) or next((v for k, v in rk.items() if k[:14] == reg[:14]), None)
        if p is None:
            continue
        pct.append(p)
        detail.append((day, reg, km, p, air))
    if not pct:
        print(f"  {label:44} keine Faelle")
        return None, []
    print(f"  {label:44} n={len(pct):4d}  Median {st.median(pct):3.0f}%   "
          f"oberes Drittel {100*sum(1 for x in pct if x <= 33.3)/len(pct):2.0f}%  "
          f"unteres Drittel {100*sum(1 for x in pct if x > 66.7)/len(pct):2.0f}%")
    return st.median(pct), detail


def main():
    idx = load_spot_index()
    best, unmatched = collect_proven_good(idx)
    days = sorted({d for d, _ in best})
    with_arch = [d for d in days if (ARCHIVE / f"{d}.json").exists()]
    print(f"Region-Tage mit bewiesenen Fluegen: {len(best)}  "
          f"({len(days)} Tage, davon {len(with_arch)} mit Archiv)")
    print(f"Zeitraum {with_arch[0]} .. {with_arch[-1]}\n")

    for thresh in THRESHOLDS:
        print(f"=== Bewiesen gut = beste Region-Leistung >= {thresh:.0f} km ===")
        print("  (50 % = Zufall; kleiner = unsere Rangliste trifft es)")
        _m, det = percentile_test(best, "climb_rate_max_ms", False, thresh,
                                  "unser Steigen (Tages-Max, Median je Region)")
        percentile_test(best, "max_thermal_height_max_m", False, thresh, "max. Thermikhoehe")
        percentile_test(best, "productive_thermal_h", False, thresh, "produktive Thermik-Stunden")
        print("  -- Kontrolle: Groessen, die trennen MUESSEN --")
        percentile_test(best, "wind_gust_max_kmh", True, thresh, "wenig Boeen zuerst")
        percentile_test(best, "precip_sum_mm", True, thresh, "wenig Regen zuerst")
        percentile_test(best, "shortwave_rad_max", False, thresh, "viel Strahlung zuerst")
        percentile_test(best, "cloud_low_mean_pct", True, thresh, "wenig tiefe Wolken zuerst")
        print()
        if thresh == 100.0 and det:
            print("  Die klarsten Faelle (>=100 km), schlechtester Rang zuerst:")
            for day, reg, km, p, _air in sorted(det, key=lambda x: -x[3])[:12]:
                print(f"    {day}  {reg[:26]:26} {km:6.1f} km  unser Perzentil {p:3.0f}%")
            print()

    if unmatched:
        tot = sum(unmatched.values())
        print(f"Nicht zuordenbare Startplaetze: {tot} Zeilen, "
              f"{len(unmatched)} Namen (nicht in fluggebiete_dhv.csv oder mehrdeutig)")
        for n, c in sorted(unmatched.items(), key=lambda x: -x[1])[:10]:
            print(f"  {c:3d}x {n}")


if __name__ == "__main__":
    main()
