#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Genauigkeits-Auswertung Forecast vs. XContest — getrennt nach Spot und Region.

Liest die Tages-TSVs aus validation/xcontest/_raw/, joint den eingefrorenen
Forecast aus data/weather_archive/ und misst, was wir an bewiesen geflogenen
Tagen vorhergesagt hatten. Schreibt nichts — reine Auswertung.

METHODIK — einseitig, und das ist keine Bequemlichkeit:
XContest zeigt nur die guten Fluege. Viele Fluege ab Spot X beweisen, dass X
fliegbar war (Lower Bound). **Keine** Fluege ab X beweist nichts — kann Wetter
sein, kann Wochentag, Pilotendichte oder Topografie sein. Darum wird hier
ausschliesslich gemessen, wo Realitaet bewiesen ist:

  - Harter Fehlalarm : wir sagten not_safe, real wurde weit geflogen
  - Unterschaetzung  : wir sagten Flugeinschaetzung <=2, real 100+ km
  - Treffer          : Flugeinschaetzung >=4 und real weit geflogen

Was hier NICHT gemessen werden kann: Ueberschaetzung ("wir sagten super, es kam
nichts"). Dafuer braucht es eine Quelle fuer Nicht-Fluege, die XContest nicht ist.

Usage: PYTHONUTF8=1 python scripts/xc_accuracy.py [--min-km 60]
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import xc_aggregate as xa  # noqa: E402

POLY = ROOT / "data" / "regionen_polygone_mapped.geojson"

# Snapshot vor dem Analyse-Pass gezogen -> Ratings sind Artefakte, keine
# Prognose (status=error 487/494, siehe README "Bekannte Daten-Luecken").
BROKEN_SNAPSHOTS = {"2026-06-20"}

FAR_KM = 60.0        # ab hier gilt ein Tag am Spot als bewiesen produktiv
STRONG_KM = 100.0    # ab hier ist eine tiefe Flugeinschaetzung nicht mehr haltbar


def region_id_map():
    """Anzeigename -> id im regions-Block des Snapshots."""
    gj = json.loads(POLY.read_text(encoding="utf-8"))
    return {f["properties"]["region"]: f["properties"]["id"] for f in gj["features"]}


def load_archive(date):
    path = xa.ARCHIVE / f"{date}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def pct(n, total):
    return "%5.1f%%" % (100.0 * n / total) if total else "    -"


def main(argv):
    min_km = FAR_KM
    if "--min-km" in argv:
        min_km = float(argv[argv.index("--min-km") + 1])

    rid = region_id_map()
    dates = sorted(p.stem for p in xa.RAW.glob("*.tsv")
                   if len(p.stem) == 10 and p.stem[4] == "-")

    # ---- Sammler ----
    spot_rows = []          # nur Zeilen mit gejointem Forecast
    region_days = []        # (date, region, launches, best_km, region-Rating-Felder)
    day_log = []
    skipped = Counter()

    for date in dates:
        arch = load_archive(date)
        if arch is None:
            skipped["kein_snapshot"] += 1
            day_log.append((date, "kein Snapshot", 0, 0, 0))
            continue
        flags = xa.DATE_FLAGS.get(date, {"xc_ok": True, "exp_ok": True})
        flights = xa.load_day(date)
        agg = xa.aggregate(flights)
        rows, _diag = xa.build_rows(date, agg, arch)

        joined = [r for r in rows if r["finding_type"] != "coverage_gap"]
        # Tage ohne Analyse-Pass (Juli, 20.06) liefern leere our_*-Felder
        rated = [r for r in joined if str(r["our_status"] or "").strip()]
        if not rated:
            skipped["ohne_analyse_block"] += 1
            day_log.append((date, "Snapshot ohne analysis", len(flights), 0, 0))
            continue

        for r in rated:
            r["_exp_ok"] = flags["exp_ok"]
            spot_rows.append(r)

        # ---- Region-Ebene: alle Fluege des Tages, auch die ohne DB-Spot ----
        per_region = defaultdict(lambda: {"launches": 0, "best_km": 0.0, "spots": set()})
        for r in rows:
            reg = (r["region"] or "").strip()
            if not reg:
                continue
            p = per_region[reg]
            p["launches"] += int(r["launches"])
            p["best_km"] = max(p["best_km"], float(r["best_km"]))
            p["spots"].add(r["spot"])

        regions_block = arch.get("regions") or {}
        for reg, p in per_region.items():
            rb = regions_block.get(rid.get(reg, ""), {})
            if not rb:
                continue
            region_days.append({
                "date": date, "region": reg,
                "launches": p["launches"], "best_km": p["best_km"],
                "n_spots": len(p["spots"]),
                "status": rb.get("status") or "",
                "safety": rb.get("rating"),
                "exp": rb.get("experience_rating") if flags["exp_ok"] else None,
                "no_go": "|".join(rb.get("no_go_reasons") or []),
            })
        day_log.append((date, "ok", len(flights), len(rated), len(per_region)))

    # ---------------------------------------------------------------- Report
    print("=" * 78)
    print("GENAUIGKEIT FORECAST vs. XCONTEST — einseitig (nur bewiesene Fluege)")
    print("=" * 78)
    ok_days = [d for d in day_log if d[1] == "ok"]
    print("Tage mit Rohdaten: %d | auswertbar: %d | kein Snapshot: %d | "
          "Snapshot ohne analysis: %d"
          % (len(dates), len(ok_days), skipped["kein_snapshot"],
             skipped["ohne_analyse_block"]))
    print("Spot-Tage mit gejointem Forecast: %d | Region-Tage mit Fluegen: %d"
          % (len(spot_rows), len(region_days)))

    # ---- Spot-Ebene ----
    print("\n" + "-" * 78)
    print("SPOT-EBENE — was sagten wir an Spots, ab denen real geflogen wurde?")
    print("-" * 78)
    strong = [r for r in spot_rows if float(r["best_km"]) >= min_km]
    print("Spot-Tage gesamt: %d | davon mit Flug >=%.0f km: %d"
          % (len(spot_rows), min_km, len(strong)))

    for label, sel in (("alle Spot-Tage", spot_rows),
                       ("nur >=%.0f km" % min_km, strong)):
        c = Counter(r["our_status"] for r in sel)
        tot = len(sel)
        print("\n  Status-Verteilung (%s, n=%d):" % (label, tot))
        for st in ("safe", "conditional", "not_safe"):
            print("    %-12s %5d  %s" % (st, c.get(st, 0), pct(c.get(st, 0), tot)))
        print("    -> harter Fehlalarm (not_safe trotz Flug): %s" % pct(c.get("not_safe", 0), tot))

    # Flugeinschaetzung vs. reale Distanz
    exp_rows = [r for r in spot_rows
                if r["_exp_ok"] and str(r["our_experience_rating"]).strip()]
    print("\n  Flugeinschaetzung vs. real geflogene Distanz (n=%d Spot-Tage):" % len(exp_rows))
    print("    %-6s %6s %10s %10s %8s" % ("rating", "n", "median km", "max km", ">=100km"))
    buckets = defaultdict(list)
    for r in exp_rows:
        buckets[int(float(r["our_experience_rating"]))].append(float(r["best_km"]))
    for k in sorted(buckets):
        v = buckets[k]
        print("    %-6d %6d %10.1f %10.1f %8d"
              % (k, len(v), median(v), max(v), sum(1 for x in v if x >= STRONG_KM)))

    under = [r for r in exp_rows
             if float(r["best_km"]) >= STRONG_KM
             and float(r["our_experience_rating"]) <= 2]
    hit = [r for r in exp_rows
           if float(r["best_km"]) >= STRONG_KM
           and float(r["our_experience_rating"]) >= 4]
    strong_exp = [r for r in exp_rows if float(r["best_km"]) >= STRONG_KM]
    print("\n  Bei real >=%.0f km (n=%d): Treffer (rating>=4) %s | "
          "Unterschaetzt (rating<=2) %s"
          % (STRONG_KM, len(strong_exp), pct(len(hit), len(strong_exp)),
             pct(len(under), len(strong_exp))))

    # ---- Region-Ebene ----
    print("\n" + "-" * 78)
    print("REGION-EBENE — was sagten wir in Regionen, in denen real geflogen wurde?")
    print("-" * 78)
    rstrong = [d for d in region_days if d["best_km"] >= min_km]
    print("Region-Tage gesamt: %d | davon mit Flug >=%.0f km: %d"
          % (len(region_days), min_km, len(rstrong)))
    for label, sel in (("alle Region-Tage", region_days),
                       ("nur >=%.0f km" % min_km, rstrong)):
        c = Counter(d["status"] for d in sel)
        tot = len(sel)
        print("\n  Status-Verteilung (%s, n=%d):" % (label, tot))
        for st in ("safe", "conditional", "not_safe"):
            print("    %-12s %5d  %s" % (st, c.get(st, 0), pct(c.get(st, 0), tot)))

    rexp = [d for d in region_days if d["exp"] is not None]
    print("\n  Region-Flugeinschaetzung vs. bester Flug der Region (n=%d):" % len(rexp))
    print("    %-6s %6s %10s %10s %10s" % ("rating", "n", "median km", "max km", "med. Fluege"))
    rb = defaultdict(list)
    for d in rexp:
        rb[int(d["exp"])].append((d["best_km"], d["launches"]))
    for k in sorted(rb):
        v = rb[k]
        print("    %-6d %6d %10.1f %10.1f %10.1f"
              % (k, len(v), median([x[0] for x in v]), max(x[0] for x in v),
                 median([x[1] for x in v])))

    # ---- Regionale Schieflage: wo liegen wir wie oft daneben? ----
    print("\n  Pro Region — Anteil not_safe an Tagen mit Fluegen >=%.0f km:" % min_km)
    per_reg = defaultdict(lambda: {"n": 0, "notsafe": 0, "km": []})
    for d in rstrong:
        e = per_reg[d["region"]]
        e["n"] += 1
        e["km"].append(d["best_km"])
        if d["status"] == "not_safe":
            e["notsafe"] += 1
    print("    %-30s %5s %9s %10s" % ("Region", "Tage", "not_safe", "med. km"))
    for reg, e in sorted(per_reg.items(), key=lambda kv: -kv[1]["notsafe"] / max(kv[1]["n"], 1)):
        if e["n"] < 3:
            continue
        print("    %-30s %5d %9s %10.1f"
              % (reg[:30], e["n"], pct(e["notsafe"], e["n"]), median(e["km"])))

    # ---- Tages-Ebene: Flugvolumen als (schwaches) Gegensignal ----
    print("\n" + "-" * 78)
    print("TAGES-EBENE — Flugvolumen als Indiz fuer Ueberschaetzung")
    print("-" * 78)
    print("Die Flugzahl eines Tages ist ein Indiz, kein Beweis: sie haengt auch am")
    print("Wochentag. In diesen Daten ist der Wetter-Effekt aber deutlich groesser")
    print("als der Wochentags-Effekt, damit wird die Richtung 'wir zu optimistisch'")
    print("wenigstens naeherungsweise pruefbar. Ausgeschlossen: Tage mit Stub-")
    print("Flugeinschaetzung (DATE_FLAGS exp_ok=False) — deren Note ist ein Artefakt.")
    day_rows = []
    for date in dates:
        flags = xa.DATE_FLAGS.get(date, {"exp_ok": True})
        if not flags.get("exp_ok", True) or date in BROKEN_SNAPSHOTS:
            continue
        arch = load_archive(date)
        if arch is None:
            continue
        rb = arch.get("regions") or {}
        exps = [v.get("experience_rating") for v in rb.values()
                if v.get("experience_rating")]
        if not exps:
            continue
        n_flights = len(xa.load_day(date))
        wd = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"][
            __import__("datetime").date(*map(int, date.split("-"))).weekday()]
        day_rows.append((date, wd, n_flights, sum(exps) / len(exps)))

    if day_rows:
        we = [d[2] for d in day_rows if d[1] in ("Sa", "So")]
        wk = [d[2] for d in day_rows if d[1] not in ("Sa", "So")]
        if we and wk:
            print("\n  Median Fluege — Wochenende %.0f (n=%d) vs. Werktag %.0f (n=%d)"
                  % (median(we), len(we), median(wk), len(wk)))

        def ranks(v):
            order = sorted(range(len(v)), key=lambda i: v[i])
            out = [0] * len(v)
            for pos, i in enumerate(order):
                out[i] = pos + 1
            return out

        n = len(day_rows)
        if n > 2:
            rx = ranks([d[2] for d in day_rows])
            ry = ranks([d[3] for d in day_rows])
            rho = 1 - 6 * sum((a - b) ** 2 for a, b in zip(rx, ry)) / (n * (n * n - 1))
            print("  Rang-Korrelation Flugzahl <-> unsere Tagesnote: %.2f (n=%d Tage)"
                  % (rho, n))

        print("\n  %-12s %-3s %8s %8s  %s"
              % ("Datum", "Tag", "Fluege", "Note", "Befund"))
        over = under = 0
        for date, wd, fl, e in sorted(day_rows, key=lambda d: -d[2]):
            verdict = ""
            if e >= 3.5 and fl < 40:
                verdict = "UEBERSCHAETZT"
                over += 1
            elif e <= 2.0 and fl >= 100:
                verdict = "UNTERSCHAETZT (stark)"
                under += 1
            elif e <= 2.5 and 40 <= fl < 100:
                verdict = "unterschaetzt"
            print("  %-12s %-3s %8d %8.2f  %s" % (date, wd, fl, e, verdict))
        print("\n  -> Ueberschaetzte Tage: %d | stark unterschaetzte Tage: %d"
              % (over, under))
    print("-" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
