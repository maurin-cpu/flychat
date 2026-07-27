"""Validiert die prognostizierte Steigrate gegen echte XContest-Flüge.

Zwei getrennte Fragen — die Reihenfolge ist wichtig:

1. TRENNSCHÄRFE (rangbasiert): Erkennt der Forecast, WO an einem Tag die beste
   Thermik war? Gemessen als Spearman-Korrelation zwischen unserer regionalen
   Steigraten-Prognose und der real geflogenen Bestleistung (km) je Region.
   Rangbasiert = unabhängig von jeder Skalierung.

2. NIVEAU (skalenbasiert): Stimmt der absolute Wert? Verglichen wird gegen das
   aus der XC-Geschwindigkeit invertierte erreichte Steigen (Kurbel-Gleit-Zyklus,
   V_air = V_cruise * c/(c+w)). Nur für Flüge, bei denen der Zyklus das Flugbild
   dominiert (>= MIN_KM, >= MIN_H) — kurze schnelle Abgleiter verfälschen sonst.

Datenquellen: data/weather_archive/YYYY-MM-DD.json (unser Forecast, Snapshot vom
Morgen) und xcontest_validation/_raw/YYYY-MM-DD.tsv (aus Paste via
scripts/_parse_xc_paste.py). Ausgewertet werden nur Tage, an denen beides vorliegt.

Nur-Lese-Skript: schreibt nichts in Prod-Caches.

Aufruf:  python scripts/validate_climb_vs_xcontest.py [--detour 1.25] [--csv out.csv]
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import statistics as st
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "data" / "weather_archive"
RAW = ROOT / "xcontest_validation" / "_raw"

# --- Inversion XC-Speed -> erreichtes Steigen ---------------------------------
# Gleitschirm-Polare (EN-B/C Mittelklasse): Reisegeschwindigkeit und zugehöriges
# Eigensinken. V_air = V_CRUISE * c/(c + W_SINK)  ->  c = W_SINK*V_air/(V_CRUISE-V_air)
V_CRUISE_KMH = 38.0
W_SINK_MS = 1.15
# Umwegfaktor: geflogener Weg / gewertete Strecke (Thermik-Suche, Drift, Dreieck).
DEFAULT_DETOUR = 1.25
# Nur Flüge, in denen der Kurbel-Gleit-Zyklus das Flugbild dominiert.
MIN_KM = 20.0
MIN_H = 1.5

# XContest-Startplatznamen, die in fluggebiete_dhv.csv anders oder abgeschnitten
# heissen. Nur verifizierte Auflösungen — geraten wird hier nichts.
ALIASES = {
    "cret du midi": "Crêt-du-Midi",
    "crap sogn": "Flims- Laax - Crap Sogn Gion",
    "cari (car": "Carì, diint",
    "schynige": "Schynige Platte -Kamel_Chrüterwand (Interlaken)",
    "dreibunde": "Dreibuendenstein-2120",
    "tschenten": "Tschentenegg",
}
# Mehrdeutige Namen (mehrere reale Startplätze, Region nicht entscheidbar).
AMBIGUOUS = {"scheidegg", "rothorn", "brunni", "niederhorn"}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return " ".join(c for c in s if c.isalnum() or c.isspace()).strip()


def load_spot_index() -> dict[str, tuple[str, str]]:
    """Spotname (normalisiert) -> (analyse_region, terrain_type). Aus dem jüngsten Archiv."""
    files = sorted(glob.glob(str(ARCHIVE / "*.json")))
    if not files:
        raise SystemExit("Kein weather_archive gefunden.")
    spots = json.load(open(files[-1], encoding="utf-8"))["spots"]
    idx = {}
    for name, v in spots.items():
        idx[norm(name)] = (v.get("analyse_region") or "?", v.get("terrain_type") or "?")
    return idx


def match_launch(launch: str, idx: dict) -> tuple[str, str] | None:
    key = norm(launch.replace("...", ""))
    if not key or key == "?" or key in AMBIGUOUS:
        return None
    for alias, target in ALIASES.items():
        if key.startswith(alias):
            hit = idx.get(norm(target))
            if hit:
                return hit
    if key in idx:
        return idx[key]
    cands = [v for k, v in idx.items() if k.startswith(key)]
    if len(cands) == 1:
        return cands[0]
    cands = [v for k, v in idx.items() if key.startswith(k) and len(k) >= 5]
    if len(cands) == 1:
        return cands[0]
    return None


def hours(hhmm: str) -> float | None:
    try:
        h, m = hhmm.split(":")
        return int(h) + int(m) / 60
    except Exception:
        return None


def invert_climb(v_xc_kmh: float, detour: float) -> float | None:
    v_air = v_xc_kmh * detour
    if v_air >= V_CRUISE_KMH - 1.0:
        return None  # Abgleiter/Dynamik — Kurbel-Gleit-Modell nicht anwendbar
    return W_SINK_MS * v_air / (V_CRUISE_KMH - v_air)


def spearman(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 4:
        return None

    def ranks(x):
        order = sorted(range(n), key=lambda i: x[i])
        r = [0.0] * n
        i = 0
        while i < n:  # Bindungen -> Durchschnittsrang
            j = i
            while j + 1 < n and x[order[j + 1]] == x[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    ra, rb = ranks(a), ranks(b)
    ma, mb = st.mean(ra), st.mean(rb)
    num = sum((ra[i] - ma) * (rb[i] - mb) for i in range(n))
    den = (sum((x - ma) ** 2 for x in ra) * sum((x - mb) ** 2 for x in rb)) ** 0.5
    return num / den if den else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detour", type=float, default=DEFAULT_DETOUR,
                    help=f"Umwegfaktor geflogener Weg / gewertete km (default {DEFAULT_DETOUR})")
    ap.add_argument("--csv", help="Tages-Ergebnisse als CSV rausschreiben")
    args = ap.parse_args()

    idx = load_spot_index()
    days = sorted(
        d for d in (Path(p).stem for p in glob.glob(str(RAW / "20*.tsv")))
        if (ARCHIVE / f"{d}.json").exists()
    )
    if not days:
        raise SystemExit("Keine Tage mit Archiv UND XContest-TSV gefunden.")

    unmatched: dict[str, int] = defaultdict(int)
    n_flights = n_matched = 0
    per_day = []
    level_pairs = []  # (terrain, fc_max, fc_mean, erreicht)
    day_regions: dict[str, dict[str, tuple[float, float]]] = {}  # day -> reg -> (fc, best_km)

    for day in days:
        arch = json.load(open(ARCHIVE / f"{day}.json", encoding="utf-8"))["spots"]
        fc_max, fc_mean = defaultdict(list), defaultdict(list)
        terrain_of = {}
        for name, v in arch.items():
            reg = v.get("analyse_region") or "?"
            da = v["daily_aggregates"]
            if da.get("climb_rate_max_ms") is not None:
                fc_max[reg].append(da["climb_rate_max_ms"])
            if da.get("climb_rate_mean_flight_ms") is not None:
                fc_mean[reg].append(da["climb_rate_mean_flight_ms"])
            terrain_of[reg] = v.get("terrain_type") or "?"

        best_km: dict[str, float] = {}
        achieved: dict[str, list[float]] = defaultdict(list)
        for row in open(RAW / f"{day}.tsv", encoding="utf-8"):
            parts = row.rstrip("\n").split("\t")
            if len(parts) < 4:
                continue
            launch, km_s, _start, at = parts[0], parts[1], parts[2], parts[3]
            t = hours(at)
            try:
                km = float(km_s)
            except ValueError:
                continue
            if t is None:
                continue
            n_flights += 1
            hit = match_launch(launch, idx)
            if not hit:
                unmatched[launch] += 1
                continue
            n_matched += 1
            reg = hit[0]
            best_km[reg] = max(best_km.get(reg, 0.0), km)
            if km >= MIN_KM and t >= MIN_H:
                c = invert_climb(km / t, args.detour)
                if c:
                    achieved[reg].append(c)

        regs = [r for r in best_km if len(fc_max.get(r, [])) >= 3]
        day_regions[day] = {r: (st.median(fc_max[r]), best_km[r]) for r in regs}
        if len(regs) >= 4:
            rho = spearman([st.median(fc_max[r]) for r in regs], [best_km[r] for r in regs])
            per_day.append((day, len(regs), rho, max(best_km.values())))
        for r, cs in achieved.items():
            if len(fc_max.get(r, [])) >= 3:
                level_pairs.append((terrain_of.get(r, "?"), st.median(fc_max[r]),
                                    st.median(fc_mean[r]) if fc_mean.get(r) else None,
                                    max(cs)))

    # --- Popularitaets-Korrektur -------------------------------------------
    # "Best-km je Region" misst nicht nur die Thermik, sondern auch wie viele
    # XC-Piloten dort starten (Tamaro >> Unterengadin). Dieser konstante
    # Regions-Effekt wird entfernt, indem jeder Tag gegen den EIGENEN Median
    # der Region normalisiert wird (relative Tagesguete statt absoluter km).
    reg_days = defaultdict(list)
    for day, per_reg in day_regions.items():
        for r, (fcm, bkm) in per_reg.items():
            reg_days[r].append((day, fcm, bkm))
    reg_median_km = {r: st.median([x[2] for x in v]) for r, v in reg_days.items() if len(v) >= 4}

    print("\n=== 1b. TRENNSCHAERFE popularitaets-korrigiert ===")
    print("  (a) je Tag ueber die Regionen, real = km relativ zum Regions-Median")
    rel_rhos = []
    for day, per_reg in sorted(day_regions.items()):
        regs = [r for r in per_reg if r in reg_median_km and reg_median_km[r] > 0]
        if len(regs) < 4:
            continue
        rho = spearman([per_reg[r][0] for r in regs],
                       [per_reg[r][1] / reg_median_km[r] for r in regs])
        if rho is not None:
            rel_rhos.append(rho)
    if rel_rhos:
        print(f"      n={len(rel_rhos)} Tage | Median rho {st.median(rel_rhos):+.3f} | "
              f"rho>0 an {sum(1 for r in rel_rhos if r > 0)}/{len(rel_rhos)} Tagen")
    print("  (b) je Region ueber die Tage — trifft der Forecast die guten Tage DORT?")
    reg_rhos = []
    for r, v in sorted(reg_days.items()):
        if len(v) < 6:
            continue
        rho = spearman([x[1] for x in v], [x[2] for x in v])
        if rho is None:
            continue
        reg_rhos.append((r, len(v), rho))
    for r, nd, rho in sorted(reg_rhos, key=lambda x: -x[2]):
        print(f"      {r[:28]:28} n={nd:2d}  rho {rho:+.2f}")
    if reg_rhos:
        rr = [x[2] for x in reg_rhos]
        print(f"      -> Median ueber {len(rr)} Regionen: rho {st.median(rr):+.3f} | "
              f"rho>0 bei {sum(1 for x in rr if x > 0)}/{len(rr)}")

    print(f"\nTage mit Archiv + XContest: {len(days)}  ({days[0]} .. {days[-1]})")
    print(f"Flüge total {n_flights}, Startplatz->Region gematcht {n_matched} "
          f"({100*n_matched/max(1,n_flights):.0f}%)\n")

    print("=== 1. TRENNSCHÄRFE: Spearman(Forecast-Steigen, real geflogene Best-km) je Tag ===")
    print(f"{'Tag':12} {'Regionen':>8} {'rho':>7} {'Tages-Best':>11}")
    rhos = []
    for day, nreg, rho, bkm in per_day:
        print(f"{day:12} {nreg:8d} {('%.2f' % rho) if rho is not None else '   n/a':>7} {bkm:8.1f} km")
        if rho is not None:
            rhos.append(rho)
    if rhos:
        pos = sum(1 for r in rhos if r > 0)
        print(f"\n  n={len(rhos)} Tage | Median rho {st.median(rhos):+.3f} | "
              f"Mittel {st.mean(rhos):+.3f} | rho>0 an {pos}/{len(rhos)} Tagen")
        print("  Referenz: rho=0 -> keine Trennschärfe, rho=1 -> perfekte Rangfolge.")

    print("\n=== 2. NIVEAU: Forecast vs. invertiertes erreichtes Steigen ===")
    print(f"  (nur Flüge >= {MIN_KM:.0f} km und >= {MIN_H} h, Umwegfaktor {args.detour})")
    if level_pairs:
        fmax = [p[1] for p in level_pairs]
        ach = [p[3] for p in level_pairs]
        fmean = [p[2] for p in level_pairs if p[2] is not None]
        print(f"  n={len(level_pairs)} Region-Tage")
        print(f"  Median Forecast Tages-Max   {st.median(fmax):.2f} m/s")
        if fmean:
            print(f"  Median Forecast Flug-Mittel {st.median(fmean):.2f} m/s")
        print(f"  Median erreicht (invertiert) {st.median(ach):.2f} m/s")
        print(f"  -> Verhaeltnis Tages-Max/erreicht {st.median(fmax)/st.median(ach):.2f}")
        print(f"\n  {'Terrain':12} {'n':>4} {'fc_max':>7} {'erreicht':>9} {'Verh.':>6}")
        for tz in ["mittelland", "jura", "voralpen", "alpen", "hochalpin"]:
            s = [p for p in level_pairs if p[0] == tz]
            if len(s) < 5:
                continue
            f_, a_ = st.median([p[1] for p in s]), st.median([p[3] for p in s])
            print(f"  {tz:12} {len(s):4d} {f_:7.2f} {a_:9.2f} {f_/a_:6.2f}")

    if unmatched:
        print("\n=== Nicht gematchte Startplätze (Top 12) — nicht in fluggebiete_dhv.csv "
              "oder mehrdeutig ===")
        for name, cnt in sorted(unmatched.items(), key=lambda x: -x[1])[:12]:
            print(f"  {cnt:4d}x {name}")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["date", "regionen", "spearman_rho", "tages_best_km"])
            for row in per_day:
                w.writerow(row)
        print(f"\nCSV geschrieben: {args.csv}")


if __name__ == "__main__":
    main()
