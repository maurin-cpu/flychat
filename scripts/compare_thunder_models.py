"""Vergleicht unseren Gewitter-Wettercode gegen das Blitzpotenzial (LPI).

WARUM
-----
Fuer Gewitter gibt es keine frei verfuegbare Wahrheit (siehe Kopf von
scripts/fetch_lpi_archive.py und docs/plaene/PLAN_gewitter_anzeige.md).
Ersatzweise halten wir ZWEI UNABHAENGIGE MODELLE gegeneinander:

  A) unser weather_code 95/96/99  — ICON-CH (Schweizer Modell), aus den
     Tages-Snapshots in data/weather_archive/
  B) lightning_potential > 0      — ICON-D2 (deutsches Modell), aus
     data/lpi_archive/lpi_icon_d2.json (via scripts/fetch_lpi_archive.py)

Die Uebereinstimmung ist KEIN Guetemass — sie sagt nicht, welches Modell recht
hat. Sie ist ein Sicherheitsmass: wo beide dasselbe sagen, ist die Aussage
belastbarer.

EBENE — DER ENTSCHEIDENDE PUNKT
-------------------------------
Der Vergleich Spot-gegen-Spot und Stunde-gegen-Stunde ist AUSSAGELOS
("double penalty", ECMWF): eine um 15 km versetzte Zelle zaehlt gleichzeitig
als Verfehler und als Fehlalarm. Gemessen ergab er 1 % Uebereinstimmung.
Auf Region+Tag — der Ebene, auf der wir tatsaechlich anzeigen — sind es 32 %.
Default ist deshalb --level region. Die Spot-Ebene bleibt nur als
Gegenprobe erhalten.

Usage:
    python scripts/compare_thunder_models.py                # Region+Tag
    python scripts/compare_thunder_models.py --level spot   # Gegenprobe
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from spots import sanitize_spot_name  # noqa: E402

THUNDER_CODES = {95, 96, 99}
ARCHIVE_GLOB = os.path.join(ROOT, "data", "weather_archive", "*.json")
LPI_PATH = os.path.join(ROOT, "data", "lpi_archive", "lpi_icon_d2.json")
INDEX_KEYS = ("cape", "convective_inhibition", "lifted_index")


def _quantile(values, p):
    if not values:
        return None
    s = sorted(values)
    return round(s[min(int(len(s) * p), len(s) - 1)], 1)


def load_lpi(path):
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    by_spot, region_of = {}, {}
    for name, v in raw["spots"].items():
        key = sanitize_spot_name(name)
        by_spot[key] = {t: x for t, x
                        in zip(v["time"], v["lightning_potential"])
                        if x is not None}
        region_of[key] = v.get("region")
    return by_spot, region_of, raw.get("_meta", {})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--level", choices=("region", "spot"), default="region")
    ap.add_argument("--lpi", default=LPI_PATH)
    args = ap.parse_args(argv)

    if not os.path.exists(args.lpi):
        print(f"FEHLT: {args.lpi}\nZuerst: python scripts/fetch_lpi_archive.py")
        return 1
    lpi, region_of, meta = load_lpi(args.lpi)
    print(f"LPI-Quelle: {meta.get('model')} | {len(lpi)} Spots | "
          f"ab {meta.get('first_hour_with_value')}")

    files = sorted(glob.glob(ARCHIVE_GLOB))
    print(f"Snapshots : {len(files)}")

    wc_flag = collections.defaultdict(bool)
    lp_flag = collections.defaultdict(bool)
    keys = set()
    matched = unmatched = 0
    idx_with = {k: [] for k in INDEX_KEYS}
    idx_without = {k: [] for k in INDEX_KEYS}

    for path in files:
        with open(path, encoding="utf-8") as fh:
            day_data = json.load(fh)
        day = day_data["_meta"].get("forecast_date")
        for name, spot in day_data.get("spots", {}).items():
            key = sanitize_spot_name(name)
            series = lpi.get(key)
            if series is None:
                unmatched += 1
                continue
            matched += 1
            region = spot.get("analyse_region") or region_of.get(key) or "?"
            group = (region, day) if args.level == "region" else (key, day)
            for hour, vals in (spot.get("hourly_flight") or {}).items():
                stamp = f"{day}T{hour[:2]}:00"
                lpi_val = series.get(stamp)
                if lpi_val is None:
                    continue
                gk = group if args.level == "region" else (key, stamp)
                keys.add(gk)
                if vals.get("weather_code") in THUNDER_CODES:
                    wc_flag[gk] = True
                positive = lpi_val > 0
                if positive:
                    lp_flag[gk] = True
                bucket = idx_with if positive else idx_without
                for k in INDEX_KEYS:
                    if vals.get(k) is not None:
                        bucket[k].append(vals[k])

    both = only_wc = only_lp = neither = 0
    for k in keys:
        a, b = wc_flag[k], lp_flag[k]
        if a and b:
            both += 1
        elif a:
            only_wc += 1
        elif b:
            only_lp += 1
        else:
            neither += 1
    total = len(keys) or 1
    unit = "Region-Tage" if args.level == "region" else "Spot-Stunden"

    print(f"Spot-Eintraege zugeordnet: {matched} | ohne LPI-Gegenstueck: "
          f"{unmatched}")
    print(f"\n=== {unit}: {total} ===")
    print(f"  beide melden Gewitter : {both:6d} ({100 * both / total:5.1f} %)")
    print(f"  NUR unser Wettercode  : {only_wc:6d} "
          f"({100 * only_wc / total:5.1f} %)")
    print(f"  NUR Blitzpotenzial    : {only_lp:6d} "
          f"({100 * only_lp / total:5.1f} %)  <- heute nicht angezeigt")
    print(f"  keiner von beiden     : {neither:6d} "
          f"({100 * neither / total:5.1f} %)")
    if both + only_wc:
        print(f"\n  Von unseren Gewitter-{unit} bestaetigt LPI "
              f"{100 * both / (both + only_wc):.0f} %")
    if both + only_lp:
        print(f"  Von den LPI-{unit} faengt unser Code "
              f"{100 * both / (both + only_lp):.0f} %")
    print(f"\n  Anzeige heute : {100 * (both + only_wc) / total:.1f} % der {unit}")
    print(f"  Mit LPI dazu  : {100 * (both + only_wc + only_lp) / total:.1f} % "
          f"(+{only_lp} {unit})")

    print(f"\n--- Indexwerte, Stunden MIT LPI>0 (n={len(idx_with['cape'])}) ---")
    for k in INDEX_KEYS:
        a = idx_with[k]
        print(f"  {k:24s} P25 {_quantile(a, .25)}  Median {_quantile(a, .5)}"
              f"  P75 {_quantile(a, .75)}")
    print(f"--- Stunden OHNE (n={len(idx_without['cape'])}) ---")
    for k in INDEX_KEYS:
        a = idx_without[k]
        print(f"  {k:24s} P25 {_quantile(a, .25)}  Median {_quantile(a, .5)}"
              f"  P75 {_quantile(a, .75)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
